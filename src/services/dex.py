"""
src/services/dex.py
Свапы через KyberSwap. Мультичейн: polygon | base | linea.

KyberSwap MetaAggregationRouterV2 имеет один и тот же адрес во всех
поддерживаемых сетях, поэтому KYBER_ROUTER — константа.
Router также берётся из ответа /route/build на всякий случай.
"""

import time
from typing import Optional

from eth_account import Account
from web3 import Web3
from web3.exceptions import TransactionNotFound

from src.core.http import get as http_get, post as http_post
from src.core.logger import get_logger
from src.core.notifier import notify_error, notify_money, notify_success
from src.core.proxy import get_proxy_for_wallet
from src.core.rpc import (
    DEFAULT_CHAIN,
    get_native_symbol,
    get_web3,
)
from src.core.safe_tx import safe_send
from src.core.tx_logger import log_transaction, update_transaction_status
from src.modules.executor.erc20 import (
    TOKENS,
    approve,
    get_allowance,
    get_token_info,
)


log = get_logger(__name__)

KYBER_BASE = "https://aggregator-api.kyberswap.com"

# Chain в URL Kyber API (совпадает с ключами CHAINS в rpc.py)
KYBER_CHAIN_MAP: dict[str, str] = {
    "polygon": "polygon",
    "base": "base",
    "linea": "linea",
}

# MetaAggregationRouterV2 — один адрес во всех EVM-сетях
KYBER_ROUTER = "0x6131B5fae19EA4f9D964eAc0408E4408b66337b5"

# Нативный токен (ERC-7528 псевдо-адрес) — единый для всех EVM
NATIVE_TOKEN = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"

# Удобные алиасы для обратной совместимости
USDC_POLYGON = TOKENS["polygon"]["USDC"]
USDT_POLYGON = TOKENS["polygon"]["USDT"]
WMATIC_POLYGON = TOKENS["polygon"]["WMATIC"]


# ============================================================
# Хелперы
# ============================================================

def _is_native(token: str) -> bool:
    return token.lower() in (
        NATIVE_TOKEN.lower(), "matic", "native", "pol", "eth",
    )


def _normalize_token(token: str) -> str:
    if _is_native(token):
        return NATIVE_TOKEN
    return Web3.to_checksum_address(token)


def _kyber_chain(chain: str) -> str:
    """Маппинг chain → имя в URL Kyber."""
    if chain not in KYBER_CHAIN_MAP:
        raise ValueError(f"KyberSwap не поддерживает chain: {chain}")
    return KYBER_CHAIN_MAP[chain]


def _api_get(chain: str, path: str, params: dict):
    url = f"{KYBER_BASE}/{_kyber_chain(chain)}{path}"
    response = http_get(url, params=params)
    if response is None:
        return None
    if response.status_code != 200:
        log.error(f"KyberSwap [{chain}] {response.status_code}: {response.text[:200]}")
        return None
    try:
        return response.json()
    except Exception as e:
        log.error(f"KyberSwap [{chain}] non-JSON: {e}")
        return None


def _api_post(chain: str, path: str, body: dict):
    url = f"{KYBER_BASE}/{_kyber_chain(chain)}{path}"
    response = http_post(url, json=body)
    if response is None:
        return None
    if response.status_code != 200:
        log.error(
            f"KyberSwap POST [{chain}] {response.status_code}: {response.text[:200]}"
        )
        return None
    try:
        return response.json()
    except Exception as e:
        log.error(f"KyberSwap POST [{chain}] non-JSON: {e}")
        return None


# ============================================================
# Quote
# ============================================================

def get_quote(
    token_in: str,
    token_out: str,
    amount: float,
    chain: str = DEFAULT_CHAIN,
    from_address: Optional[str] = None,
) -> Optional[dict]:
    """
    Запрашивает quote у KyberSwap.

    amount — в человеческих единицах (1.0 = 1 токен).
    Возвращает dict с from_symbol/from_amount/to_symbol/to_amount/route_summary.
    """
    token_in_norm = _normalize_token(token_in)
    token_out_norm = _normalize_token(token_out)
    native_sym = get_native_symbol(chain)

    # Откуда
    if _is_native(token_in):
        from_decimals = 18
        from_symbol = native_sym
    else:
        info = get_token_info(token_in_norm, chain=chain)
        if info is None:
            return None
        from_decimals = info["decimals"]
        from_symbol = info["symbol"]

    # Куда
    if _is_native(token_out):
        to_decimals = 18
        to_symbol = native_sym
    else:
        info = get_token_info(token_out_norm, chain=chain)
        if info is None:
            return None
        to_decimals = info["decimals"]
        to_symbol = info["symbol"]

    amount_raw = int(amount * (10 ** from_decimals))
    params = {
        "tokenIn": token_in_norm,
        "tokenOut": token_out_norm,
        "amountIn": str(amount_raw),
    }
    if from_address:
        params["to"] = Web3.to_checksum_address(from_address)

    data = _api_get(chain, "/api/v1/routes", params)
    if data is None:
        return None
    if data.get("code") != 0:
        log.error(f"KyberSwap [{chain}] error: {data.get('message')}")
        return None

    route_summary = data.get("data", {}).get("routeSummary")
    if route_summary is None:
        return None

    to_amount_raw = int(route_summary["amountOut"])
    to_amount = to_amount_raw / (10 ** to_decimals)

    return {
        "from_symbol": from_symbol,
        "from_amount": amount,
        "to_symbol": to_symbol,
        "to_amount": to_amount,
        "price": to_amount / amount if amount > 0 else 0,
        "route_summary": route_summary,
    }


# ============================================================
# Swap
# ============================================================

def swap(
    from_label: str,
    token_in: str,
    token_out: str,
    amount: float,
    chain: str = DEFAULT_CHAIN,
    slippage: float = 5.0,
    wait: bool = True,
    notify: bool = True,
) -> Optional[str]:
    """
    Свап через KyberSwap в указанной сети.

    slippage — в процентах (5.0 = 5%).
    """
    from src.modules.wallets.manager import get_all_wallets, get_private_key

    from_address = None
    for w in get_all_wallets():
        if w.label.lower() == from_label.lower():
            from_address = Web3.to_checksum_address(w.address)
            break

    if from_address is None:
        if notify:
            notify_error(f"Wallet not found: {from_label}")
        return None

    proxy = get_proxy_for_wallet(from_address)
    w3 = get_web3(chain=chain, proxy=proxy)
    private_key = get_private_key(from_address)
    if private_key is None:
        if notify:
            notify_error("Cannot decrypt key")
        return None

    token_in_norm = _normalize_token(token_in)

    quote = get_quote(token_in, token_out, amount, chain=chain, from_address=from_address)
    if quote is None:
        if notify:
            notify_error(f"KyberSwap [{chain}] no quote")
        return None

    log.info(
        f"[{chain}] Quote: {quote['from_amount']} {quote['from_symbol']} "
        f"-> {quote['to_amount']} {quote['to_symbol']}"
    )

    # Approve если нужно
    if not _is_native(token_in):
        current = get_allowance(from_address, KYBER_ROUTER, token_in_norm, chain=chain)
        if current is None or current < amount:
            tx = approve(
                owner_label_or_address=from_label,
                spender=KYBER_ROUTER,
                token_address=token_in_norm,
                amount=None,
                chain=chain,
                wait=True,
                notify=notify,
            )
            if tx is None:
                return None

    build_body = {
        "routeSummary": quote["route_summary"],
        "sender": from_address,
        "recipient": from_address,
        "slippageTolerance": int(slippage * 100),
    }
    build_data = _api_post(chain, "/api/v1/route/build", build_body)
    if build_data is None:
        return None
    if build_data.get("code") != 0:
        log.error(f"KyberSwap [{chain}] build: {build_data.get('message')}")
        return None

    tx_info = build_data["data"]
    router_address = Web3.to_checksum_address(tx_info["routerAddress"])
    calldata = tx_info["data"]

    # amountIn может отсутствовать в build_data — берём из routeSummary
    amount_in_raw = int(
        tx_info.get("amountIn")
        or quote["route_summary"].get("amountIn")
        or 0
    )
    if amount_in_raw == 0:
        log.error(f"KyberSwap [{chain}]: amountIn=0 — не могу собрать транзакцию")
        if notify:
            notify_error("KyberSwap: amountIn=0")
        return None

    log.debug(
        f"[{chain}] amount_in_raw={amount_in_raw}, "
        f"native_in={_is_native(token_in)}, router={router_address}"
    )

    nonce = w3.eth.get_transaction_count(from_address, "pending")

    tx = {
        "from": from_address,
        "to": router_address,
        "data": calldata,
        "value": amount_in_raw if _is_native(token_in) else 0,
        "nonce": nonce,
        "chainId": w3.eth.chain_id,
        "gas": 800000,
    }

    latest = w3.eth.get_block("latest")
    base_fee = latest.get("baseFeePerGas")
    if base_fee:
        priority = w3.to_wei(30, "gwei")
        tx["maxFeePerGas"] = base_fee * 2 + priority
        tx["maxPriorityFeePerGas"] = priority
        tx["type"] = 2
    else:
        tx["gasPrice"] = w3.eth.gas_price

    try:
        signed = Account.sign_transaction(tx, private_key)
    except Exception as e:
        log.exception(f"Sign error [{chain}]")
        if notify:
            notify_error(f"Sign: {str(e)[:150]}")
        return None

    try:
        tx_hash = safe_send(w3, signed)
    except Exception as e:
        log.exception(f"Send error [{chain}]")
        if notify:
            notify_error(f"Send: {str(e)[:150]}")
        return None

    tx_hash_hex = tx_hash.hex()
    log.success(f"[{chain}] Swap TX: {tx_hash_hex}")

    log_transaction(
        wallet_address=from_address,
        tx_hash=tx_hash_hex,
        tx_type="swap",
        token_from=quote["from_symbol"],
        token_to=quote["to_symbol"],
        amount_from=quote["from_amount"],
        amount_to=quote["to_amount"],
        chain=chain,
    )

    if notify:
        notify_money(
            f"🔄 Swap [{chain}]\n"
            f"{quote['from_amount']} {quote['from_symbol']} → "
            f"{quote['to_amount']} {quote['to_symbol']}\n"
            f"tx: {tx_hash_hex[:20]}..."
        )

    if wait:
        started = time.time()
        receipt = None
        while time.time() - started < 180:
            try:
                receipt = w3.eth.get_transaction_receipt(tx_hash)
                break
            except TransactionNotFound:
                time.sleep(3)

        native_sym = get_native_symbol(chain)
        if receipt and receipt.get("status") == 1:
            gas_used = receipt.get("gasUsed", 0)
            eff_price = receipt.get("effectiveGasPrice", 0)
            fee_native = float(Web3.from_wei(gas_used * eff_price, "ether"))
            update_transaction_status(
                tx_hash_hex, status="success", gas_usd=fee_native
            )
            if notify:
                notify_success(
                    f"✅ Swap [{chain}] confirmed\n"
                    f"Комиссия: {fee_native:.8f} {native_sym}"
                )
        elif receipt:
            update_transaction_status(tx_hash_hex, status="failed")
            if notify:
                notify_error(f"❌ Swap [{chain}] failed")
        else:
            update_transaction_status(tx_hash_hex, status="failed")

    return tx_hash_hex


__all__ = [
    "get_quote",
    "swap",
    "KYBER_ROUTER",
    "KYBER_CHAIN_MAP",
    "NATIVE_TOKEN",
    "USDC_POLYGON",
    "USDT_POLYGON",
    "WMATIC_POLYGON",
]


if __name__ == "__main__":
    log.info("Test KyberSwap multi-chain")

    for chain in ("polygon", "base", "linea"):
        usdc = TOKENS[chain]["USDC"]
        print(f"\n=== {chain.upper()} ===")
        q = get_quote(usdc, "native", 1.0, chain=chain)
        if q:
            print(
                f"✅ 1 {q['from_symbol']} → {q['to_amount']:.6f} {q['to_symbol']}"
            )
        else:
            print(f"❌ не смог получить quote")
