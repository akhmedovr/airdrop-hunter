"""
src/services/dex.py
Свапы через KyberSwap (Polygon).
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
from src.core.rpc import get_web3
from src.core.safe_tx import safe_send
from src.core.tx_logger import log_transaction, update_transaction_status
from src.modules.executor.erc20 import approve, get_allowance, get_token_info


log = get_logger(__name__)

KYBER_BASE = "https://aggregator-api.kyberswap.com"
POLYGON_CHAIN = "polygon"
KYBER_ROUTER = "0x6131B5fae19EA4f9D964eAc0408E4408b66337b5"
NATIVE_TOKEN = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
USDC_POLYGON = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDT_POLYGON = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
WMATIC_POLYGON = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"


def _is_native(token):
    return token.lower() in (NATIVE_TOKEN.lower(), "matic", "native", "pol")


def _normalize_token(token):
    if _is_native(token):
        return NATIVE_TOKEN
    return Web3.to_checksum_address(token)


def _api_get(path, params):
    url = KYBER_BASE + "/" + POLYGON_CHAIN + path
    response = http_get(url, params=params)
    if response is None:
        return None
    if response.status_code != 200:
        log.error("KyberSwap " + str(response.status_code) + ": " + response.text[:200])
        return None
    try:
        return response.json()
    except Exception as e:
        log.error("KyberSwap non-JSON: " + str(e))
        return None


def _api_post(path, body):
    url = KYBER_BASE + "/" + POLYGON_CHAIN + path
    response = http_post(url, json=body)
    if response is None:
        return None
    if response.status_code != 200:
        log.error("KyberSwap POST " + str(response.status_code) + ": " + response.text[:200])
        return None
    try:
        return response.json()
    except Exception as e:
        log.error("KyberSwap non-JSON POST: " + str(e))
        return None


def get_quote(token_in, token_out, amount, from_address=None):
    token_in_norm = _normalize_token(token_in)
    token_out_norm = _normalize_token(token_out)

    if _is_native(token_in):
        from_decimals = 18
        from_symbol = "MATIC"
    else:
        info = get_token_info(token_in_norm)
        if info is None:
            return None
        from_decimals = info["decimals"]
        from_symbol = info["symbol"]

    if _is_native(token_out):
        to_decimals = 18
        to_symbol = "MATIC"
    else:
        info = get_token_info(token_out_norm)
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

    data = _api_get("/api/v1/routes", params)
    if data is None:
        return None
    if data.get("code") != 0:
        log.error("KyberSwap error: " + str(data.get("message")))
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


def swap(from_label, token_in, token_out, amount, slippage=2.0, wait=True, notify=True):
    """
    Свап через KyberSwap.

    slippage — в процентах (2.0 = 2%). Для мелких сумм поднимаем до 3%.
    """
    from src.modules.wallets.manager import get_all_wallets, get_private_key

    from_address = None
    for w in get_all_wallets():
        if w.label.lower() == from_label.lower():
            from_address = Web3.to_checksum_address(w.address)
            break

    if from_address is None:
        if notify:
            notify_error("Wallet not found: " + from_label)
        return None

    proxy = get_proxy_for_wallet(from_address)
    w3 = get_web3(proxy=proxy)
    private_key = get_private_key(from_address)
    if private_key is None:
        if notify:
            notify_error("Cannot decrypt key")
        return None

    token_in_norm = _normalize_token(token_in)

    quote = get_quote(token_in, token_out, amount, from_address)
    if quote is None:
        if notify:
            notify_error("KyberSwap no quote")
        return None

    log.info(
        "Quote: " + str(quote["from_amount"]) + " " + quote["from_symbol"]
        + " -> " + str(quote["to_amount"]) + " " + quote["to_symbol"]
    )

    if not _is_native(token_in):
        current = get_allowance(from_address, KYBER_ROUTER, token_in_norm)
        if current is None or current < amount:
            tx = approve(
                owner_label_or_address=from_label,
                spender=KYBER_ROUTER,
                token_address=token_in_norm,
                amount=None,
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
    build_data = _api_post("/api/v1/route/build", build_body)
    if build_data is None:
        return None
    if build_data.get("code") != 0:
        log.error("KyberSwap build: " + str(build_data.get("message")))
        return None

    tx_info = build_data["data"]
    router_address = Web3.to_checksum_address(tx_info["routerAddress"])
    calldata = tx_info["data"]

    # === ФИКС: amountIn из build_data может отсутствовать.
    # Берём его из routeSummary (там он всегда есть). ===
    amount_in_raw = int(
        tx_info.get("amountIn")
        or quote["route_summary"].get("amountIn")
        or 0
    )
    if amount_in_raw == 0:
        log.error("KyberSwap: amountIn=0 — не могу собрать транзакцию")
        if notify:
            notify_error("KyberSwap: amountIn=0")
        return None

    log.debug(
        f"swap: amount_in_raw={amount_in_raw}, "
        f"native_in={_is_native(token_in)}, "
        f"router={router_address}"
    )

    nonce = w3.eth.get_transaction_count(from_address, "pending")

    tx = {
        "from": from_address,
        "to": router_address,
        "data": calldata,
        "value": amount_in_raw if _is_native(token_in) else 0,
        "nonce": nonce,
        "chainId": w3.eth.chain_id,
        "gas": 400000,
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
        log.exception("Sign error")
        if notify:
            notify_error("Sign: " + str(e)[:150])
        return None

    try:
        tx_hash = safe_send(w3, signed)
    except Exception as e:
        log.exception("Send error")
        if notify:
            notify_error("Send: " + str(e)[:150])
        return None

    tx_hash_hex = tx_hash.hex()
    log.success("Swap TX: " + tx_hash_hex)

    log_transaction(
        wallet_address=from_address,
        tx_hash=tx_hash_hex,
        tx_type="swap",
        token_from=quote["from_symbol"],
        token_to=quote["to_symbol"],
        amount_from=quote["from_amount"],
        amount_to=quote["to_amount"],
        chain="polygon",
    )

    if notify:
        notify_money(
            "Swap " + str(quote["from_amount"]) + " " + quote["from_symbol"]
            + " -> " + str(quote["to_amount"]) + " " + quote["to_symbol"]
            + " tx: " + tx_hash_hex[:20]
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

        if receipt and receipt.get("status") == 1:
            gas_used = receipt.get("gasUsed", 0)
            eff_price = receipt.get("effectiveGasPrice", 0)
            fee_matic = float(Web3.from_wei(gas_used * eff_price, "ether"))
            update_transaction_status(
                tx_hash_hex, status="success", gas_usd=fee_matic
            )
            if notify:
                notify_success("Swap confirmed")
        elif receipt:
            update_transaction_status(tx_hash_hex, status="failed")
            if notify:
                notify_error("Swap failed")
        else:
            update_transaction_status(tx_hash_hex, status="failed")

    return tx_hash_hex


__all__ = [
    "get_quote",
    "swap",
    "KYBER_ROUTER",
    "NATIVE_TOKEN",
    "USDC_POLYGON",
    "USDT_POLYGON",
    "WMATIC_POLYGON",
]


if __name__ == "__main__":
    log.info("Test KyberSwap")
    q = get_quote(
        USDC_POLYGON, "native", 1.0,
        "0xAd7d42846688D8b69aCf24f279be2EF97bD4cE9F",
    )
    if q:
        print(q)
