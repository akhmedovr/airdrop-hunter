"""
src/services/dex.py
Свапы токенов через KyberSwap Aggregator API на Polygon.

KyberSwap API: публичный, БЕЗ API-ключа, без KYC.
Документация: https://docs.kyberswap.com/Aggregator/aggregator-api

Возможности:
    - get_quote()   — курс обмена
    - swap()        — полный свап: approve (если надо) + транзакция

Использование:
    from src.services.dex import get_quote, swap

    quote = get_quote(USDC_POLYGON, "native", 1.0)
    swap(from_label="farm-01", token_in=USDC_POLYGON,
         token_out="native", amount=1.0, slippage=1.0)
"""

import time
from typing import Optional

from web3 import Web3
from web3.exceptions import TransactionNotFound

from src.core.http import get as http_get, post as http_post
from src.core.logger import get_logger
from src.core.notifier import notify_error, notify_money, notify_success
from src.core.rpc import get_web3
from src.modules.executor.erc20 import (
    approve,
    get_allowance,
    get_token_info,
)

log = get_logger(__name__)

# KyberSwap Aggregator
KYBER_BASE = "https://aggregator-api.kyberswap.com"
POLYGON_CHAIN = "polygon"

# KyberSwap Router на Polygon (MetaAggregationRouterV2)
KYBER_ROUTER = "0x6131B5fae19EA4f9D964eAc0408E4408b66337b5"

# Native MATIC в KyberSwap указывается так же, как в 1inch
NATIVE_TOKEN = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"

# Известные токены Polygon
USDC_POLYGON = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDT_POLYGON = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
WMATIC_POLYGON = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"
WETH_POLYGON = "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619"


def _is_native(token: str) -> bool:
    """Проверяет, что токен — native (MATIC)."""
    return token.lower() in (NATIVE_TOKEN.lower(), "matic", "native", "pol")


def _normalize_token(token: str) -> str:
    """Приводит токен к формату для KyberSwap."""
    if _is_native(token):
        return NATIVE_TOKEN
    return Web3.to_checksum_address(token)


def _api_get(path: str, params: dict) -> Optional[dict]:
    """GET-запрос к KyberSwap API."""
    url = f"{KYBER_BASE}/{POLYGON_CHAIN}{path}"
    response = http_get(url, params=params)

    if response is None:
        log.error(f"KyberSwap не ответил: {path}")
        return None

    if response.status_code != 200:
        log.error(f"KyberSwap {response.status_code}: {response.text[:200]}")
        return None

    try:
        return response.json()
    except Exception as e:
        log.error(f"KyberSwap вернул не-JSON: {e}")
        return None


def _api_post(path: str, json_data: dict) -> Optional[dict]:
    """POST-запрос к KyberSwap API."""
    url = f"{KYBER_BASE}/{POLYGON_CHAIN}{path}"
    response = http_post(url, json=json_data)

    if response is None:
        log.error(f"KyberSwap не ответил (POST): {path}")
        return None

    if response.status_code != 200:
        log.error(f"KyberSwap {response.status_code}: {response.text[:200]}")
        return None

    try:
        return response.json()
    except Exception as e:
        log.error(f"KyberSwap вернул не-JSON (POST): {e}")
        return None


def get_quote(
    token_in: str,
    token_out: str,
    amount: float,
    from_address: Optional[str] = None,
) -> Optional[dict]:
    """
    Получает курс обмена через KyberSwap.

    Возвращает:
        {
            'from_symbol': 'USDC',
            'from_amount': 1.0,
            'to_symbol': 'MATIC',
            'to_amount': 0.85,
            'price': 0.85,
            'route_summary': {...},  # для последующего build
        }
        или None при ошибке.
    """
    token_in_norm = _normalize_token(token_in)
    token_out_norm = _normalize_token(token_out)

    # Decimals / symbol для INPUT
    if _is_native(token_in):
        from_decimals = 18
        from_symbol = "MATIC"
    else:
        info = get_token_info(token_in_norm)
        if info is None:
            return None
        from_decimals = info["decimals"]
        from_symbol = info["symbol"]

    # Decimals / symbol для OUTPUT
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
    # from_address нужен для точной симуляции
    if from_address:
        params["to"] = Web3.to_checksum_address(from_address)

    data = _api_get("/api/v1/routes", params)
    if data is None:
        return None

    if data.get("code") != 0:
        log.error(f"KyberSwap вернул ошибку: {data.get('message')}")
        return None

    route_summary = data.get("data", {}).get("routeSummary")
    if route_summary is None:
        log.error("KyberSwap: нет routeSummary в ответе")
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


def swap(
    from_label: str,
    token_in: str,
    token_out: str,
    amount: float,
    slippage: float = 1.0,
    wait: bool = True,
    notify: bool = True,
) -> Optional[str]:
    """
    Выполняет свап токенов через KyberSwap.

    Args:
        from_label: метка кошелька-отправителя
        token_in: адрес токена ИЛИ 'native'/'matic'
        token_out: адрес токена ИЛИ 'native'
        amount: сумма токена IN (человеческие единицы)
        slippage: проскальзывание в % (1.0 = 1%)
        wait: ждать ли receipt
        notify: уведомлять ли

    Returns:
        tx_hash hex или None.
    """
    from eth_account import Account
    from src.modules.wallets.manager import get_all_wallets, get_private_key

    w3 = get_web3()

    # 1. Определяем адрес
    from_address = None
    for w in get_all_wallets():
        if w.label.lower() == from_label.lower():
            from_address = Web3.to_checksum_address(w.address)
            break

    if from_address is None:
        if notify:
            notify_error(f"Кошелёк не найден: {from_label}")
        return None

    private_key = get_private_key(from_address)
    if private_key is None:
        if notify:
            notify_error("Не удалось расшифровать ключ")
        return None

    token_in_norm = _normalize_token(token_in)
    token_out_norm = _normalize_token}")
(token_out)

    # 2. Quote
    quote = get_quote(token_in, token_out, amount, from_address)
    if quote is None:
        if notify:
            notify_error(f"KyberSwap не дал quote для {amount} {token_in}")
        return None

    log.info(
        f"Quote: {quote['from_amount']} {quote['from_symbol']} → "
        f"{quote['to_amount']:.6f} {quote['to_symbol']}"
    )

    # 3. Approve (только для не-native)
    if not _is_native(token_in):
        current = get_allowance(from_address, KYBER_ROUTER, token_in_norm)
        if current is None or current < amount:
            log.info(f"Нужен approve {token_in_norm[:10]}...")
            if notify:
                notify_success(f       "✍️ Шаг 1/2: if approve {quote['from_symbol']}")
            tx = approve(
                notify owner_label_or_address=from:
_label,
                spender=KYBER_ROUTER,
                           token_address=token_in_norm,
                amount=None,  # unlimited
                wait=True,
                notify=notify,
            )
            if tx is None:
                log.error("Approve не удался")
                return None

    # 4. Build calldata
    build_body = {
        "routeSummary": quote["route_summary"],
        "sender": from_address,
        "recipient": from_address,
        "slippageTolerance": int(slippage * 100),  # 1% = 100 bps
    }

    build_data = _api_post("/api/v1/route/build", build_body)
    if build_data is None:
        if notify:
            notify_error("KyberSwap не дал build data")
        return None

    if build_data.get("code") != 0:
        log.error(f"KyberSwap build error: {build_data.get('message') notify_error(f"KyberSwap build: {build_data.get('message')}")
        return None

    tx_info = build_data["data"]
    router_address = Web3.to_checksum_address(tx_info["routerAddress"])
    calldata = tx_info["data"]
    # amountIn нужен для value при native input
    amount_in_raw = int(tx_info.get("amountIn", 0))

    # 5. Собираем транзакцию
    nonce = w3.eth.get_transaction_count(from_address, "pending")
    chain_id = w3.eth.chain_id

    tx: dict = {
        "from": from_address,
        "to": router_address,
        "data": calldata,
        "value": amount_in_raw if _is_native(token_in) else 0,
        "nonce": nonce,
        "chainId": chain_id,
        "gas": int(tx_info.get("gas", "300000")) if isinstance(tx_info.get("gas"), str) else 300_000,
    }

    # +20% газа
    tx["gas"] = int(tx["gas"] * 1.2)

    # EIP-1559
    latest = w3.eth.get_block("latest")
    base_fee = latest.get("baseFeePerGas")
    if base_fee:
        priority = w3.to_wei(30, "gwei")
        tx["maxFeePerGas"] = base_fee * 2 + priority
        tx["maxPriorityFeePerGas"] = priority
        tx["type"] = 2
    else:
        tx["gasPrice"] = w3.eth.gas_price

    # 6. Подпись
    try:
        signed = Account.sign_transaction(tx, private_key)
    except Exception as e:
        log.exception("Ошибка подписи swap")
        if notify:
            notify_error(f"Ошибка подписи: {str(e)[:150]}")
        return None

    # 7. Отправка
    try:
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    except Exception as e:
        log.exception("Ошибка отправки swap")
        if notify:
            notify_error(f"Ошибка swap: {str(e)[:150]}")
        return None

    tx_hash_hex = tx_hash.hex()
    log.success(f"Swap TX: {tx_hash_hex}")

    if notify:
        notify_money(
            f"🔄 Swap {quote['from_amount']} {quote['from_symbol']} → "
            f"{quote['to_amount']:.4f} {quote['to_symbol']}\n"
            f"tx: {tx_hash_hex[:20]}..."
        )

    # 8. Receipt
    if wait:
        started = time.time()
        receipt = None
        while time.time() - started < 180:
            try:
                receipt = w3.eth.get_transaction_receipt(tx_hash)
                break
            except TransactionNotFound:
                time.sleep(3)

        if receipt is None:
            if notify:
                notify_error("Swap не подтверждён за 180с")
            return tx_hash_hex

        if receipt.get("status") == 1:
            gas_used = receipt.get("gasUsed", 0)
            eff = receipt.get("effectiveGasPrice", 0)
            fee = float(Web3.from_wei(gas_used * eff, "ether"))
            if notify:
                notify_success(
                    f"✅ Swap подтверждён\n"
                    f"Комиссия: {fee:.6f} MATIC"
                )
        else:
            if notify:
                notify_error("❌ Swap провалился (status=0)")

    return tx_hash_hex


__all__ = [
    "get_quote",
    "swap",
    "KYBER_ROUTER",
    "NATIVE_TOKEN",
    "USDC_POLYGON",
    "USDT_POLYGON",
    "WMATIC_POLYGON",
    "WETH_POLYGON",
]


if __name__ == "__main__":
    # Быстрый тест: python -m src.services.dex
    log.info("Тест KyberSwap — только чтение, без транзакций")

    quote = get_quote(USDC_POLYGON, "native", 1.0)
    if quote:
        print(f"✅ KyberSwap работает")
        print(f"   1 {quote['from_symbol']} → {quote['to_amount']:.6f} {quote['to_symbol']}")
        print(f"   Курс: {quote['price']:.6f}")
    else:
        print("❌ Не удалось получить quote")

    quote2 = get_quote("native", USDC_POLYGON, 1.0)
    if quote2:
        print(f"   1 MATIC → {quote2['to_amount']:.6f} USDC")
