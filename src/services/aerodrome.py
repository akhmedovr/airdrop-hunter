"""
src/services/aerodrome.py
Свапы через Aerodrome Finance (главный DEX на Base).

Поддерживает только chain="base". Для других сетей — src.services.dex (KyberSwap).

Почему Aerodrome, а не Kyber:
    - Aerodrome — нативный DEX Base, участвует в снапшотах Base
    - Для дропа Base и дропа Aerodrome on-chain активность через Aerodrome
      весит больше, чем через агрегатор Kyber

Функции:
    - get_quote_aerodrome() — оценка курса через getAmountsOut
    - swap_aerodrome()      — свап native ETH -> токен или токен -> native ETH

Ограничения (MVP):
    - Только токен <-> ETH (native), без token <-> token
    - Только volatile pools (stable=False)
    - Slippage по умолчанию 5%
"""

import time
from typing import Optional

from eth_account import Account
from web3 import Web3
from web3.exceptions import TransactionNotFound

from src.core.logger import get_logger
from src.core.notifier import notify_error, notify_money, notify_success
from src.core.proxy import get_proxy_for_wallet
from src.core.rpc import get_web3
from src.core.safe_tx import safe_send
from src.core.tx_logger import log_transaction, update_transaction_status
from src.modules.executor.erc20 import (
    TOKENS,
    approve,
    get_allowance,
    get_token_info,
)


log = get_logger(__name__)


# ============================================================
# Константы Aerodrome (Base)
# ============================================================

AERODROME_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
AERODROME_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
WETH_BASE = "0x4200000000000000000000000000000000000006"

# ERC-7528 псевдо-адрес нативного ETH
NATIVE_ETH = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"

# Внутренний символ для native в этой сети
NATIVE_SYM = "ETH"

RECEIPT_TIMEOUT = 180
PRIORITY_FEE_GWEI = 30

# Минимальный ABI Router — только нужные функции
AERODROME_ROUTER_ABI = [
    # swapExactETHForTokens(uint256,address[],address,uint256)
    {
        "inputs": [
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "routes", "type": "tuple[]", "components": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "stable", "type": "bool"},
                {"name": "factory", "type": "address"},
            ]},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "name": "swapExactETHForTokens",
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
        "stateMutability": "payable",
        "type": "function",
    },
    # swapExactTokensForETH(uint256,uint256,tuple[],address,uint256)
    {
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "routes", "type": "tuple[]", "components": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "stable", "type": "bool"},
                {"name": "factory", "type": "address"},
            ]},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"},
        ],
        "name": "swapExactTokensForETH",
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    # getAmountsOut(uint256,tuple[])
    {
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "routes", "type": "tuple[]", "components": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "stable", "type": "bool"},
                {"name": "factory", "type": "address"},
            ]},
        ],
        "name": "getAmountsOut",
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function",
    },
]


# ============================================================
# Хелперы
# ============================================================

def _is_native(token: str) -> bool:
    return token.lower() in (
        NATIVE_ETH.lower(), "eth", "native", "weth",
        "0x4200000000000000000000000000000000000006",
    )


def _build_route(token_in_addr: str, token_out_addr: str) -> list[dict]:
    """
    Строит routes для Aerodrome: один хоп, volatile pool.
    Если token_in = native ETH, в route используется WETH (обёртка).
    """
    # Aerodrome routes всегда работают с WETH, не с native pseudo-address
    t_from = WETH_BASE if _is_native(token_in_addr) else Web3.to_checksum_address(token_in_addr)
    t_to = WETH_BASE if _is_native(token_out_addr) else Web3.to_checksum_address(token_out_addr)

    return [{
        "from": t_from,
        "to": t_to,
        "stable": False,
        "factory": AERODROME_FACTORY,
    }]


def _resolve_token(sym: str) -> tuple[str, int]:
    """
    Символ -> (checksum address, decimals).
    'ETH' -> pseudo-адрес native.
    """
    s = sym.upper().strip()

    if s in ("ETH", "NATIVE", "WETH"):
        return NATIVE_ETH, 18

    base_tokens = TOKENS.get("base", {})
    if s not in base_tokens:
        raise ValueError(
            f"Неизвестный токен '{sym}' в Base. Доступные: "
            f"ETH, {', '.join(base_tokens.keys())}"
        )
    addr = base_tokens[s]
    info = get_token_info(addr, chain="base")
    if info is None:
        raise ValueError(f"Не смог получить info токена {sym}")
    return addr, info["decimals"]


# ============================================================
# Quote
# ============================================================

def get_quote_aerodrome(
    token_in: str,
    token_out: str,
    amount: float,
) -> Optional[dict]:
    """
    Quote через Aerodrome.getAmountsOut (view-вызов, без транзакции).
    Возвращает dict с from_symbol/from_amount/to_symbol/to_amount.
    """
    try:
        t_in_addr, t_in_dec = _resolve_token(token_in)
        t_out_addr, t_out_dec = _resolve_token(token_out)
    except ValueError as e:
        log.error(f"aerodrome quote: {e}")
        return None

    if _is_native(token_in) and _is_native(token_out):
        log.error("aerodrome quote: не поддерживаю native -> native")
        return None

    amount_raw = int(amount * (10 ** t_in_dec))
    route = _build_route(t_in_addr, t_out_addr)

    try:
        w3 = get_web3(chain="base")
        router = w3.eth.contract(
            address=Web3.to_checksum_address(AERODROME_ROUTER),
            abi=AERODROME_ROUTER_ABI,
        )
        amounts = router.functions.getAmountsOut(amount_raw, route).call()
        out_raw = int(amounts[-1])
    except Exception as e:
        log.error(f"aerodrome getAmountsOut упал: {e}")
        return None

    to_amount = out_raw / (10 ** t_out_dec)

    return {
        "from_symbol": token_in.upper(),
        "from_amount": amount,
        "to_symbol": token_out.upper(),
        "to_amount": to_amount,
        "price": to_amount / amount if amount > 0 else 0,
    }


# ============================================================
# Swap
# ============================================================

def swap_aerodrome(
    from_label: str,
    token_in: str,
    token_out: str,
    amount: float,
    slippage: float = 5.0,
    wait: bool = True,
    notify: bool = True,
) -> Optional[str]:
    """
    Свап через Aerodrome (Base). Только ETH <-> токен.

    slippage — в процентах (5.0 = 5%).

    Returns tx_hash hex или None.
    """
    from src.modules.wallets.manager import get_all_wallets, get_private_key

    # 1. Проверка направления
    in_native = _is_native(token_in)
    out_native = _is_native(token_out)
    if in_native == out_native:
        msg = "aerodrome: поддерживаю только ETH<->токен (не токен<->токен)"
        log.error(msg)
        if notify:
            notify_error(msg)
        return None

    # 2. Кошелёк
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
    w3 = get_web3(chain="base", proxy=proxy)
    private_key = get_private_key(from_address)
    if private_key is None:
        if notify:
            notify_error("Cannot decrypt key")
        return None

    # 3. Резолв токенов
    try:
        t_in_addr, t_in_dec = _resolve_token(token_in)
        t_out_addr, t_out_dec = _resolve_token(token_out)
    except ValueError as e:
        if notify:
            notify_error(str(e))
        return None

    # 4. Quote
    quote = get_quote_aerodrome(token_in, token_out, amount)
    if quote is None:
        if notify:
            notify_error("Aerodrome: не смог получить quote")
        return None

    log.info(
        f"[aerodrome] Quote: {amount} {token_in} -> "
        f"{quote['to_amount']:.6f} {token_out}"
    )

    # 5. Approve (только для token -> ETH)
    if not in_native:
        current = get_allowance(
            from_address, AERODROME_ROUTER, t_in_addr, chain="base"
        )
        if current is None or current < amount:
            tx = approve(
                owner_label_or_address=from_label,
                spender=AERODROME_ROUTER,
                token_address=t_in_addr,
                amount=None,   # unlimited
                chain="base",
                wait=True,
                notify=notify,
            )
            if tx is None:
                return None

    # 6. Параметры свапа
    route = _build_route(t_in_addr, t_out_addr)
    amount_out_min = int(quote["to_amount"] * (10 ** t_out_dec) * (1 - slippage / 100))
    deadline = int(time.time()) + 1200  # 20 минут

    nonce = w3.eth.get_transaction_count(from_address, "pending")

    # 7. EIP-1559 fees (Base использует EIP-1559)
    latest = w3.eth.get_block("latest")
    base_fee = latest.get("baseFeePerGas")
    fees: dict = {}
    if base_fee:
        priority = w3.to_wei(PRIORITY_FEE_GWEI, "gwei")
        fees = {
            "maxFeePerGas": base_fee * 2 + priority,
            "maxPriorityFeePerGas": priority,
        }

    # 8. Собираем транзакцию
    try:
        if in_native:
            # swapExactETHForTokens — payable, value = amount
            router = w3.eth.contract(
                address=Web3.to_checksum_address(AERODROME_ROUTER),
                abi=AERODROME_ROUTER_ABI,
            )
            tx = router.functions.swapExactETHForTokens(
                amount_out_min, route, from_address, deadline,
            ).build_transaction({
                "from": from_address,
                "value": int(amount * (10 ** 18)),
                "nonce": nonce,
                "chainId": w3.eth.chain_id,
                "gas": 500_000,
                **fees,
            })
            if fees:
                tx["type"] = 2
        else:
            # swapExactTokensForETH — нужно approve заранее
            router = w3.eth.contract(
                address=Web3.to_checksum_address(AERODROME_ROUTER),
                abi=AERODROME_ROUTER_ABI,
            )
            tx = router.functions.swapExactTokensForETH(
                int(amount * (10 ** t_in_dec)),
                amount_out_min,
                route,
                from_address,
                deadline,
            ).build_transaction({
                "from": from_address,
                "nonce": nonce,
                "chainId": w3.eth.chain_id,
                "gas": 500_000,
                **fees,
            })
            if fees:
                tx["type"] = 2
    except Exception as e:
        log.exception("aerodrome: build_transaction упал")
        if notify:
            notify_error(f"Build: {str(e)[:150]}")
        return None

    # 9. Подпись + отправка
    try:
        signed = Account.sign_transaction(tx, private_key)
    except Exception as e:
        log.exception("aerodrome: sign упал")
        if notify:
            notify_error(f"Sign: {str(e)[:150]}")
        return None

    try:
        tx_hash = safe_send(w3, signed)
    except Exception as e:
        log.exception("aerodrome: send упал")
        if notify:
            notify_error(f"Send: {str(e)[:150]}")
        return None

    tx_hash_hex = tx_hash.hex()
    log.success(f"[aerodrome] Swap TX: {tx_hash_hex}")

    # 10. Логируем в БД
    log_transaction(
        wallet_address=from_address,
        tx_hash=tx_hash_hex,
        tx_type="swap",
        token_from=token_in.upper(),
        token_to=token_out.upper(),
        amount_from=amount,
        amount_to=quote["to_amount"],
        chain="base",
    )

    if notify:
        notify_money(
            f"🔄 Aerodrome swap [base]\n"
            f"{amount} {token_in.upper()} → "
            f"{quote['to_amount']:.6f} {token_out.upper()}\n"
            f"tx: {tx_hash_hex[:20]}..."
        )

    # 11. Receipt
    if wait:
        started = time.time()
        receipt = None
        while time.time() - started < RECEIPT_TIMEOUT:
            try:
                receipt = w3.eth.get_transaction_receipt(tx_hash)
                break
            except TransactionNotFound:
                time.sleep(3)

        if receipt and receipt.get("status") == 1:
            gas_used = receipt.get("gasUsed", 0)
            eff_price = receipt.get("effectiveGasPrice", 0)
            fee_eth = float(Web3.from_wei(gas_used * eff_price, "ether"))
            update_transaction_status(
                tx_hash_hex, status="success", gas_usd=fee_eth
            )
            if notify:
                notify_success(
                    f"✅ Aerodrome swap confirmed\n"
                    f"Комиссия: {fee_eth:.8f} ETH"
                )
        elif receipt:
            update_transaction_status(tx_hash_hex, status="failed")
            if notify:
                notify_error("❌ Aerodrome swap failed")
        else:
            update_transaction_status(tx_hash_hex, status="failed")

    return tx_hash_hex


__all__ = [
    "AERODROME_ROUTER",
    "AERODROME_FACTORY",
    "WETH_BASE",
    "get_quote_aerodrome",
    "swap_aerodrome",
]


if __name__ == "__main__":
    # Быстрый тест: python -m src.services.aerodrome
    log.info("Тест Aerodrome — quote (без транзакции)")

    q = get_quote_aerodrome("ETH", "USDC", 0.0002)
    if q:
        print(
            f"✅ Quote: {q['from_amount']} {q['from_symbol']} → "
            f"{q['to_amount']:.6f} {q['to_symbol']}"
        )
    else:
        print("❌ Quote не получен")

    q2 = get_quote_aerodrome("USDC", "ETH", 0.5)
    if q2:
        print(
            f"✅ Quote: {q2['from_amount']} {q2['from_symbol']} → "
            f"{q2['to_amount']:.8f} {q2['to_symbol']}"
        )
    else:
        print("❌ Quote USDC→ETH не получен")
