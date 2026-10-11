"""
src/core/auto_swap.py
Авто-свапы по расписанию (см. DESIGN_AUTOSWAP.md). Мультичейн.

Параметры:
    - 1 свап/день (максимум 2), окно 10:00–22:00 МСК = 07:00–19:00 UTC
    - Кубик 30% на каждый час — делать сейчас или нет
    - Lazy day 15% — весь день без активности
    - Cooldown 4 часа между свапами
    - Стоп при балансе ниже минимального (POL: 5, ETH: 0.002)
    - 3 провала подряд → пауза 24 часа

Состояние (lazy_day, paused_until) — в data/auto_swap_state.json.
Счётчики (swaps today, cooldown, failed streak) — из БД (Transaction).

Ручной запуск (dry-run):
    python -c "from src.core.auto_swap import do_auto_swap; do_auto_swap('farm-01', force=True)"

Сети:
    - polygon — активна (farm-01, farm-02)
    - base, linea — код готов, но ждём пополнения ETH
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import desc, func, select

from src.core.database import SessionLocal, Transaction, Wallet
from src.core.logger import get_logger
from src.core.notifier import notify_error, notify_warning
from src.core.rpc import DEFAULT_CHAIN, get_balance_native, get_native_symbol
from src.modules.executor.erc20 import TOKENS
from src.services.dex import NATIVE_TOKEN, swap


log = get_logger(__name__)


# ============================================================
# Константы (согласованы в DESIGN_AUTOSWAP.md)
# ============================================================

STATE_FILE = Path("data/auto_swap_state.json")

MAX_SWAPS_PER_DAY = 2
COOLDOWN_HOURS = 4
FAILED_STREAK_LIMIT = 3
PAUSE_AFTER_FAILED_HOURS = 24

LAZY_DAY_CHANCE = 0.15
DICE_CHANCE = 0.30

# Окно в UTC (10:00–22:00 МСК = 07:00–19:00 UTC)
WINDOW_START_UTC_HOUR = 7
WINDOW_END_UTC_HOUR = 19

# Минимальный баланс нативной валюты для автосвапа (per chain)
MIN_BALANCE_NATIVE: dict[str, float] = {
    "polygon": 5.0,     # 5 POL
    "base": 0.002,      # 0.002 ETH (~$6-7)
    "linea": 0.002,     # 0.002 ETH
}

# Диапазоны сумм по паре (per chain)
# POL: 1.0–3.0 для тестов; USDT/USDC: 0.3–1.0
# ETH (Base/Linea): 0.0005–0.0015 ETH (чтобы комиссия окупалась)
AMOUNT_RANGES: dict[str, dict[tuple[str, str], tuple[float, float]]] = {
    "polygon": {
        ("POL", "USDT"): (1.0, 3.0),
        ("POL", "USDC"): (1.0, 3.0),
        ("USDT", "POL"): (0.3, 1.0),
        ("USDC", "POL"): (0.3, 1.0),
        ("USDT", "USDC"): (0.3, 1.0),
        ("USDC", "USDT"): (0.3, 1.0),
    },
    "base": {
        ("ETH", "USDC"): (0.0005, 0.0015),
        ("USDC", "ETH"): (0.3, 1.0),
        ("USDC", "USDT"): (0.3, 1.0),
        ("USDT", "USDC"): (0.3, 1.0),
    },
    "linea": {
        ("ETH", "USDC"): (0.0005, 0.0015),
        ("USDC", "ETH"): (0.3, 1.0),
        ("USDC", "USDT"): (0.3, 1.0),
        ("USDT", "USDC"): (0.3, 1.0),
    },
}

# Газ-буфер для native-свапов (per chain)
NATIVE_GAS_BUFFER: dict[str, float] = {
    "polygon": 1.0,    # 1 POL резерв
    "base": 0.0002,    # 0.0002 ETH
    "linea": 0.0002,
}


# ============================================================
# Вспомогательные
# ============================================================

def _native_sym(chain: str) -> str:
    """Символ native для chain — 'POL' или 'ETH'."""
    s = get_native_symbol(chain)
    # В наших TOKENS/range используем POL (не MATIC) для polygon
    return "POL" if chain == "polygon" else s


def _token_map(chain: str) -> dict[str, str]:
    """
    Маппинг 'POL'/'ETH'/'USDT'/'USDC' → адрес контракта.
    'POL'/'ETH' → NATIVE_TOKEN (псевдо-адрес).
    """
    native_sym = _native_sym(chain)
    result: dict[str, str] = {native_sym: NATIVE_TOKEN}
    for sym, addr in TOKENS.get(chain, {}).items():
        result[sym] = addr
    return result


# ============================================================
# STATE
# ============================================================

def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"auto_swap: не смог прочитать state: {e}")
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with STATE_FILE.open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"auto_swap: не смог записать state: {e}")


def _state_key(wallet_label: str, chain: str) -> str:
    """Ключ состояния — отдельно на каждый (wallet, chain)."""
    return f"{wallet_label}::{chain}"


def _get_wallet_state(wallet_label: str, chain: str) -> dict:
    state = _load_state()
    key = _state_key(wallet_label, chain)
    return state.get(key, {
        "lazy_day_date": None,
        "is_lazy_day": False,
        "paused_until": None,
    })


def _update_wallet_state(wallet_label: str, chain: str, **kwargs) -> None:
    state = _load_state()
    key = _state_key(wallet_label, chain)
    if key not in state:
        state[key] = {
            "lazy_day_date": None,
            "is_lazy_day": False,
            "paused_until": None,
        }
    state[key].update(kwargs)
    _save_state(state)


# ============================================================
# Проверки (из БД)
# ============================================================

def _get_wallet(wallet_label: str) -> Optional[Wallet]:
    with SessionLocal() as s:
        return s.execute(
            select(Wallet).where(Wallet.label == wallet_label)
        ).scalar_one_or_none()


def _swaps_today(wallet_addr: str, chain: str) -> int:
    """Сколько swap-транзакций в сети chain у кошелька за сегодня (UTC)."""
    today_start = datetime.utcnow().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    with SessionLocal() as s:
        wallet = s.execute(
            select(Wallet).where(Wallet.address == wallet_addr)
        ).scalar_one_or_none()
        if not wallet:
            return 0
        count = s.execute(
            select(func.count(Transaction.id))
            .where(Transaction.wallet_id == wallet.id)
            .where(Transaction.tx_type == "swap")
            .where(Transaction.chain == chain)
            .where(Transaction.created_at >= today_start)
        ).scalar_one()
        return int(count or 0)


def _last_swap_time(wallet_addr: str, chain: str) -> Optional[datetime]:
    """Время последнего swap в сети chain (любой статус)."""
    with SessionLocal() as s:
        wallet = s.execute(
            select(Wallet).where(Wallet.address == wallet_addr)
        ).scalar_one_or_none()
        if not wallet:
            return None
        last = s.execute(
            select(Transaction)
            .where(Transaction.wallet_id == wallet.id)
            .where(Transaction.tx_type == "swap")
            .where(Transaction.chain == chain)
            .order_by(desc(Transaction.created_at))
            .limit(1)
        ).scalar_one_or_none()
        return last.created_at if last else None


def _failed_streak(wallet_addr: str, chain: str) -> int:
    """Сколько failed-свапов подряд в сети chain."""
    with SessionLocal() as s:
        wallet = s.execute(
            select(Wallet).where(Wallet.address == wallet_addr)
        ).scalar_one_or_none()
        if not wallet:
            return 0
        recent = s.execute(
            select(Transaction)
            .where(Transaction.wallet_id == wallet.id)
            .where(Transaction.tx_type == "swap")
            .where(Transaction.chain == chain)
            .order_by(desc(Transaction.created_at))
            .limit(FAILED_STREAK_LIMIT)
        ).scalars().all()

    streak = 0
    for tx in recent:
        if tx.status == "failed":
            streak += 1
        else:
            break
    return streak


# ============================================================
# State-проверки
# ============================================================

def _is_paused(wallet_label: str, chain: str) -> bool:
    st = _get_wallet_state(wallet_label, chain)
    paused_until = st.get("paused_until")
    if not paused_until:
        return False
    try:
        dt = datetime.fromisoformat(paused_until)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < dt:
            return True
        _update_wallet_state(wallet_label, chain, paused_until=None)
        return False
    except Exception:
        _update_wallet_state(wallet_label, chain, paused_until=None)
        return False


def _check_lazy_day(wallet_label: str, chain: str) -> bool:
    """True если сегодня lazy day. Решается раз в сутки (UTC)."""
    today = datetime.utcnow().date().isoformat()
    st = _get_wallet_state(wallet_label, chain)
    if st.get("lazy_day_date") == today:
        return bool(st.get("is_lazy_day", False))

    is_lazy = random.random() < LAZY_DAY_CHANCE
    _update_wallet_state(
        wallet_label, chain,
        lazy_day_date=today,
        is_lazy_day=is_lazy,
    )
    if is_lazy:
        log.info(f"auto_swap: {wallet_label} [{chain}] — сегодня lazy day")
    return is_lazy


# ============================================================
# Выбор пары
# ============================================================

def _choose_pair(
    wallet_addr: str,
    chain: str,
    balance_native: float,
) -> Optional[tuple[str, str, float]]:
    """
    Выбирает случайную пару (sym_in, sym_out, amount) с учётом баланса.
    Возвращает None если ничего не доступно.
    """
    from src.modules.executor.erc20 import get_token_balance

    native_sym = _native_sym(chain)
    gas_buffer = NATIVE_GAS_BUFFER.get(chain, 0.001)

    # Балансы токенов
    balances: dict[str, float] = {native_sym: balance_native}
    for sym in ("USDT", "USDC"):
        addr = TOKENS.get(chain, {}).get(sym)
        if not addr:
            continue
        try:
            balances[sym] = get_token_balance(wallet_addr, addr, chain=chain) or 0.0
        except Exception:
            balances[sym] = 0.0

    ranges = AMOUNT_RANGES.get(chain, {})
    available: list[tuple[str, str, float]] = []

    for (sym_in, sym_out), (lo, hi) in ranges.items():
        # Нужен запас на газ, если свапаем native
        required = hi + gas_buffer if sym_in == native_sym else hi
        if balances.get(sym_in, 0.0) >= required:
            amount = round(random.uniform(lo, hi), 6)
            # Перепроверка после округления
            if amount + (gas_buffer if sym_in == native_sym else 0.0) > balances[sym_in]:
                continue
            available.append((sym_in, sym_out, amount))

    if not available:
        return None
    return random.choice(available)


# ============================================================
# Основная функция
# ============================================================

def do_auto_swap(
    wallet_label: str = "farm-01",
    chain: str = DEFAULT_CHAIN,
    force: bool = False,
) -> Optional[str]:
    """
    Один авто-свап в указанной сети.

    force=True — пропустить проверки (пауза, lazy, лимиты, cooldown, кубик).
    force=False — все проверки, как в проде.
    """
    native_sym = _native_sym(chain)
    log.info(f"auto_swap: старт {wallet_label} [{chain}] (force={force})")

    wallet = _get_wallet(wallet_label)
    if wallet is None:
        log.error(f"auto_swap: кошелёк {wallet_label} не найден в БД")
        return None

    # 1. Пауза
    if not force and _is_paused(wallet_label, chain):
        log.info(f"auto_swap: {wallet_label} [{chain}] на паузе")
        return None

    # 2. Lazy day
    if not force and _check_lazy_day(wallet_label, chain):
        return None

    # 3. Лимит свапов в день
    if not force:
        today_count = _swaps_today(wallet.address, chain)
        if today_count >= MAX_SWAPS_PER_DAY:
            log.info(
                f"auto_swap: {wallet_label} [{chain}] уже "
                f"{today_count} свапов сегодня"
            )
            return None

    # 4. Cooldown
    if not force:
        last = _last_swap_time(wallet.address, chain)
        if last is not None:
            elapsed = datetime.utcnow() - last
            if elapsed < timedelta(hours=COOLDOWN_HOURS):
                log.info(
                    f"auto_swap: {wallet_label} [{chain}] cooldown "
                    f"({elapsed.total_seconds() / 60:.0f} мин)"
                )
                return None

    # 5. Баланс native
    try:
        balance_native = get_balance_native(wallet.address, chain=chain)
    except Exception as e:
        log.error(f"auto_swap: не смог получить баланс [{chain}]: {e}")
        return None

    min_bal = MIN_BALANCE_NATIVE.get(chain, 1.0)
    if balance_native < min_bal:
        msg = (
            f"⚠️ auto_swap: {wallet_label} [{chain}] баланс "
            f"{balance_native:.6f} {native_sym} < {min_bal}. Стоп."
        )
        log.warning(msg)
        notify_warning(msg)
        return None

    # 6. Выбор пары
    pair = _choose_pair(wallet.address, chain, balance_native)
    if pair is None:
        log.warning(
            f"auto_swap: {wallet_label} [{chain}] нет доступных пар "
            f"(мало токенов)"
        )
        return None

    sym_in, sym_out, amount = pair
    tmap = _token_map(chain)
    token_in = tmap[sym_in]
    token_out = tmap[sym_out]

    log.success(
        f"auto_swap: {wallet_label} [{chain}] → "
        f"{amount} {sym_in} → {sym_out}"
    )

    # 7. Свап (без notify — сами уведомим по факту через notify от swap=None)
    try:
        tx_hash = swap(
            from_label=wallet_label,
            token_in=token_in,
            token_out=token_out,
            amount=amount,
            chain=chain,
            slippage=5.0,
            wait=True,
            notify=False,
        )
    except Exception as e:
        log.exception(f"auto_swap: swap [{chain}] упал с исключением: {e}")
        tx_hash = None

    # 8. Обработка результата
    if tx_hash is None:
        log.error(f"auto_swap: {wallet_label} [{chain}] свап НЕ удался")
        streak = _failed_streak(wallet.address, chain)
        if streak >= FAILED_STREAK_LIMIT:
            pause_until = datetime.now(timezone.utc) + timedelta(
                hours=PAUSE_AFTER_FAILED_HOURS
            )
            _update_wallet_state(
                wallet_label, chain,
                paused_until=pause_until.isoformat(),
            )
            notify_error(
                f"🚨 auto_swap: {wallet_label} [{chain}] — {streak} провалов "
                f"подряд. Пауза {PAUSE_AFTER_FAILED_HOURS}ч."
            )
        return None

    log.success(
        f"auto_swap: {wallet_label} [{chain}] OK, TX {tx_hash[:20]}..."
    )
    return tx_hash


# ============================================================
# Джоб для scheduler
# ============================================================

# В проде сейчас активна только Polygon.
# Base/Linea включим, когда пополним ETH.
ACTIVE_CHAINS_FOR_AUTOSWAP: list[str] = ["polygon"]

# Кошелёк для автосвапа (позже сделаем список для farm-02, farm-03)
AUTOSWAP_WALLET = "farm-01"


def auto_swap_job() -> None:
    """
    Вызывается scheduler'ом каждый час.
    Окно UTC: 07:00–19:00 (= 10:00–22:00 МСК).
    Внутри окна — кубик 30% на каждый час.

    Сейчас работает только для Polygon. Base/Linea — после пополнения ETH.
    """
    now_utc = datetime.now(timezone.utc)

    if not (WINDOW_START_UTC_HOUR <= now_utc.hour < WINDOW_END_UTC_HOUR):
        log.debug(f"auto_swap_job: вне окна (UTC {now_utc.hour}ч), пропуск")
        return

    if random.random() >= DICE_CHANCE:
        log.debug("auto_swap_job: кубик не прошёл (70%), пропуск")
        return

    log.info("auto_swap_job: кубик прошёл, запускаю")

    for chain in ACTIVE_CHAINS_FOR_AUTOSWAP:
        try:
            do_auto_swap(AUTOSWAP_WALLET, chain=chain, force=False)
        except Exception as e:
            log.exception(f"auto_swap_job: {chain} упал с исключением: {e}")


__all__ = [
    "do_auto_swap",
    "auto_swap_job",
    "ACTIVE_CHAINS_FOR_AUTOSWAP",
    "AUTOSWAP_WALLET",
]
