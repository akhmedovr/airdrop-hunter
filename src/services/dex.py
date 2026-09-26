"""
src/services/dex.py
Свапы токенов через 1inch API на Polygon.

Возможности:
    - get_quote()   — курс обмена (сколько получишь за X токенов)
    - swap()        — полный свап: approve (если надо) + транзакция

1inch API: публичный, без API-ключа, лимит ~1 запрос/сек.
Endpoint: https://api.1inch.dev/swap/v6.0/{chain_id}

Использование:
    from src.services.dex import get_quote, swap

    quote = get_quote(USDC, MATIC, 1.0)
    print(quote['to_amount'], quote['to_symbol'])

    swap(from_label="farm-01", token_in=USDC, token_out=NATIVE,
         amount=1.0, slippage=1.0)
"""

from typing import Optional

from web3 import Web3
from web3.exceptions import TransactionNotFound

from src.core.http import get as http_get
from src.core.logger import get_logger
from src.core.notifier import notify_error, notify_money, notify_success
from src.core.rpc import get_web3
from src.modules.executor.erc20 import (
    MAX_UINT256,
    approve,
    get_allowance,
    get_token_info,
)

log = get_logger(__name__)

# Константы 1inch
ONEINCH_BASE = "https://api.1inch.dev/swap/v6.0"
POLYGON_CHAIN_ID = 137

# 1inch Router v6 на Polygon
ONEINCH_ROUTER = "0x111111125421cA6dc452d289314280a0f8842A65"

# Native MATIC в 1inch указывается как "0xEeeeeEeee..."
NATIVE_TOKEN = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"

# Известные токены Polygon
USDC_POLYGON = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDT_POLYGON = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
WMATIC_POLYGON = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"


def _is_native(token: str) -> bool:
    """Проверяет, что токен — native (MATIC)."""
    return token.lower() in (NATIVE_TOKEN.lower(), "matic", "native", "pol")


def _normalize_token(token: str) -> str:
    """
    Приводит токен к формату для 1inch:
    - 'matic' / 'native' / 'pol' → NATIVE_TOKEN
    - адрес → checksum
    """
    if _is_native(token):
        return NATIVE_TOKEN
    return Web3.to_checksum_address(token)


def _api_get(path: str, params: dict) -> Optional[dict]:
    """
    GET-запрос к 1inch API.
    Возвращает dict или None.
    """
    url = f"{ONEINCH_BASE}/{POLYGON_CHAIN_ID}{path}"
    response = http_get(url, params=params)

    if response is None:
        log.error(f"1inch не ответил: {path}")
        return None

    if response.status_code != 200:
        log.error(f"1inch {response.status_code}: {response.text[:200]}")
        return None

    try:
        return response.json()
    except Exception as e:
        log.error(f"1inch вернул не-JSON: {e}")
        return None


def get_quote(
    token_in: str,
    token_out: str,
    amount: float,
    from_address: Optional[str] = None,
) -> Optional[dict]:
    """
    Получает курс обмена через 1inch.

    Args:
        token_in: адрес токена ИЛИ 'native'/'matic' для MATIC
        token_out: адрес токена ИЛИ 'native'
        amount: сумма токена IN в человеческих единицах
        from_address: адрес для проверки (опционально)

    Returns:
        {
            'from_symbol': 'USDC',
            'from_amount': 1.0,
            'to_symbol': 'MATIC',
            'to_amount': 0.85,
            'price': 0.85,
            'protocols': [...],
        }
        или None при ошибке.
    """
    token_in_norm = _normalize_token(token_in)
    token_out_norm = _normalize_token(token_out)

    # Определяем decimals для INPUT
    if _is_native(token_in):
        from_decimals = 18
        from_symbol = "MATIC"
    else:
        info = get_token_info(token_in_norm)
        if info is None:
            return None
        from_decimals = info["decimals"]
        from_symbol = info["symbol"]

    # Decimals для OUTPUT
    if _is_native(token_out):
        to_symbol = "MATIC"
    else:
        info = get_token_info(token_out_norm)
        if info is None:
            return None
        to_symbol = info["symbol"]

    amount_raw = int(amount * (10 ** from_decimals))

    params = {
        "src": token_in_norm,
        "dst": token_out_norm,
        "amount": str(amount_raw),
    }

    data = _api_get("/quote", params)
    if data is None:
        return None

    to_amount_raw = int(data["dstAmount"])

    # Decimals для OUTPUT
    if _is_native(token_out):
        to_decimals = 18
    else:
        info = get_token_info(token_out_norm)
        to_decimals = info["decimals"] if info else 18

    to_amount = to_amount_raw / (10 ** to_decimals)

    return {
        "from_symbol": from_symbol,
        "from_amount": amount,
        "to_symbol": to_symbol,
        "to_amount": to_amount,
        "price": to_amount / amount if amount > 0 else 0,
        "protocols": data.get("protocols", []),
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
    Выполняет свап токенов через 1inch.

    Автоматически:
    1. Проверяет balance токена IN
    2. Делает approve на 1inch router (если нужно)
    3. Получает swap calldata
    4. Отправляет транзакцию

    Args:
        from_label: метка кошелька-отправителя
        token_in: адрес токена ИЛИ 'native'/'matic'
        token_out: адрес токена ИЛИ 'native'
        amount: сумма токена IN (человеческие единицы)
        slippage: проскальзывание в % (например 1.0 = 1%)
        wait: ждать ли receipt
        notify: уведомлять ли

    Returns:
        tx_hash hex или None.
    """
    from src.modules.wallets.manager import get_private_key
    from eth_account import Account
    import time

    w3 = get_web3()

    # 1. Определяем адрес
    from src.modules.wallets.manager import get_all_wallets
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
    token_out_norm = _normalize_token(token_out)

    # 2. Получаем quote
    quote = get_quote(token_in, token_out, amount, from_address)
    if quote is None:
        if notify:
            notify_error(f"1inch не дал quote для {amount} {token_in}")
        return None

    log.info(
        f"Quote: {quote['from_amount']} {quote['from_symbol']} → "
        f"{quote['to_amount']:.6f} {quote['to_symbol']}"
    )

    # 3. Approve (только для не-native)
    if not _is_native(token_in):
        current = get_allowance(from_address, ONEINCH_ROUTER, token_in_norm)
        if current is None or current < amount:
            log.info(f"Нужен approve {token_in_norm[:10]}...")
            if notify:
                notify_success(
                    f"✍️ Шаг 1/2: approve {quote['from_symbol']}"
                )
            tx = approve(
                owner_label_or_address=from_label,
                spender=ONEINCH_ROUTER,
                token_address=token_in_norm,
                amount=None,  # unlimited
                wait=True,
                notify=notify,
            )
            if tx is None:
                log.error("Approve не удался")
                return None

    # 4. Получаем swap calldata
    amount_raw = int(amount * (10 ** 18 if _is_native(token_in) else
                                (get_token_info(token_in_norm) or {}).get("decimals", 18)))

    params = {
        "src": token_in_norm,
        "dst": token_out_norm,
        "amount": str(amount_raw),
        "from": from_address,
        "slippage": str(slippage),
        "disableEstimate": "true",  # сами оценим газ
    }

    data = _api_get("/swap", params)
    if data is None:
        if notify:
            notify_error("1inch не дал swap data")
        return None

    tx_data = data["tx"]

    # 5. Собираем транзакцию
    nonce = w3.eth.get_transaction_count(from_address, "pending")
    chain_id = w3.eth.chain_id

    tx = {
        "from": from_address,
        "to": Web3.to_checksum_address(tx_data["to"]),
        "data": tx_data["data"],
        "value": int(tx_data.get("value", 0)),
        "nonce": nonce,
        "chainId": chain_id,
        "gas": int(int(tx_data.get("gas", 300000)) * 1.2),  # +20%
    }

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

    # 6. Подписываем
    try:
        signed = Account.sign_transaction(tx, private_key)
    except Exception as e:
        log.exception("Ошибка подписи swap")
        if notify:
            notify_error(f"Ошибка подписи: {str(e)[:150]}")
        return None

    # 7. Отправляем
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

    # 8. Ждём receipt
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
                notify_error(f"Swap не подтверждён за 180с")
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
    "ONEINCH_ROUTER",
    "NATIVE_TOKEN",
    "USDC_POLYGON",
    "USDT_POLYGON",
    "WMATIC_POLYGON",
]


if __name__ == "__main__":
    # Быстрый тест: python -m src.services.dex
    # Только ЧТЕНИЕ — ничего не отправляем
    log.info("Тест 1inch — только чтение, без транзакций")

    # Quote: 1 USDC → MATIC
    quote = get_quote(USDC_POLYGON, "native", 1.0)
    if quote:
        print(f"✅ 1inch работает")
        print(f"   1 {quote['from_symbol']} → {quote['to_amount']:.6f} {quote['to_symbol']}")
        print(f"   Курс: {quote['price']:.6f}")
    else:
        print("❌ Не удалось получить quote")

    # Quote: 1 MATIC → USDC
    quote2 = get_quote("native", USDC_POLYGON, 1.0)
    if quote2:
        print(f"   1 MATIC → {quote2['to_amount']:.6f} USDC")
