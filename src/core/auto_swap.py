"""
src/core/auto_swap.py
Авто-свапы по расписанию (см. DESIGN_AUTOSWAP.md).

Параметры:
    - 1 свап/день (максимум 2), окно 10:00–22:00 МСК = 07:00–19:00 UTC
    - Кубик 30% на каждый час — делать сейчас или нет
    - Lazy day 15% — весь день без активности
    - Cooldown 4 часа между свапами
    - Стоп при балансе < 5 POL
    - 3 провала подряд → пауза 24 часа

Состояние (lazy_day, paused_until) — в data/auto_swap_state.json.
Счётчики (swaps today, cooldown, failed streak) — из БД (Transaction).

Ручной запуск (dry-run):
    python -c "from src.core.auto_swap import do_auto_swap; do_auto_swap('farm-01', force=True)"
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
from src.services.dex import NATIVE_TOKEN, USDC_POLYGON, USDT_POLYGON, swap

log = get_logger(__name__)


# ============================================================
# КОНСТАНТЫ (согласованы в DESIGN_AUTOSWAP.md)
# ============================================================

STATE_FILE = Path("data/auto_swap_state.json")

MAX_SWAPS_PER_DAY = 2
MIN_BALANCE_POL = 5.0
COOLDOWN_HOURS = 4
FAILED_STREAK_LIMIT = 3
PAUSE_AFTER_FAILED_HOURS = 24

LAZY_DAY_CHANCE = 0.15
DICE_CHANCE = 0.30

# Окно в UTC (10:00–22:00 МСК = 07:00–19:00 UTC)
WINDOW_START_UTC_HOUR = 7
WINDOW_END_UTC_HOUR = 19

# Диапазоны сумм по паре
AMOUNT_RANGES: dict[tuple[str, str], tuple[float, float]] = {
    ("POL", "USDT"): (1.0, 3.0),
    ("POL", "USDC"): (1.0, 3.0),
    ("USDT", "POL"): (0.3, 1.0),
    ("USDC", "POL"): (0.3, 1.0),
    ("USDT", "USDC"): (0.3, 1.0),
    ("USDC", "USDT"): (0.3, 1.0),
}

TOKEN_MAP: dict[str, str] = {
    "POL": NATIVE_TOKEN,
    "USDT": USDT_POLYGON,
    "USDC": USDC_POLYGON,
}


# ============================================================
# STATE (data/auto_swap_state.json)
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


def _get_wallet_state(wallet_label: str) -> dict:
    state = _load_state()
    return state.get(wallet_label, {
        "lazy_day_date": None,
        "is_lazy_day": False,
        "paused_until": None,
    })


def _update_wallet_state(wallet_label: str, **kwargs) -> None:
    state = _load_state()
    if wallet_label not in state:
        state[wallet_label] = {
            "lazy_day_date": None,
            "is_lazy_day": False,
            "paused_until": None,
        }
    state[wallet_label].update(kwargs)
    _save_state(state)


# ============================================================
# ПРОВЕРКИ (из БД)
# ============================================================

def _get_wallet(wallet_label: str) -> Optional[Wallet]:
    with SessionLocal() as s:
        return s.execute(
            select(Wallet).where(Wallet.label == wallet_label)
        ).scalar_one_or_none()


def _swaps_today(wallet_addr: str) -> int:
    """Сколько swap-транзакций у кошелька за сегодня (UTC)."""
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
            .where(Transaction.created_at >= today_start)
        ).scalar_one()
        return int(count or 0)


def _last_swap_time(wallet_addr: str) -> Optional[datetime]:
    """Время последнего swap (любой статус)."""
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
            .order_by(desc(Transaction.created_at))
            .limit(1)
        ).scalar_one_or_none()
        return last.created_at if last else None


def _failed_streak(wallet_addr: str) -> int:
    """Сколько failed-свапов подряд (по последним N)."""
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
# STATE-ПРОВЕРКИ
# ============================================================

def _is_paused(wallet_label: str) -> bool:
    st = _get_wallet_state(wallet_label)
    paused_until = st.get("paused_until")
    if not paused_until:
        return False
    try:
        dt = datetime.fromisoformat(paused_until)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < dt:
            return True
        # пауза истекла — сброс
        _update_wallet_state(wallet_label, paused_until=None)
        return False
    except Exception:
        _update_wallet_state(wallet_label, paused_until=None)
        return False


def _check_lazy_day(wallet_label: str) -> bool:
    """Возвращает True если сегодня lazy day. Решается раз в сутки (UTC)."""
    today = datetime.utcnow().date().isoformat()
    st = _get_wallet_state(wallet_label)
    if st.get("lazy_day_date") == today:
        return bool(st.get("is_lazy_day", False))

    is_lazy = random.random() < LAZY_DAY_CHANCE
    _update_wallet_state(
        wallet_label,
        lazy_day_date=today,
        is_lazy_day=is_lazy,
    )
    if is_lazy:
        log.info(f"auto_swap: {wallet_label} — сегодня lazy day (пропуск)")
    return is_lazy


# ============================================================
# ВЫБОР ПАРЫ
# ============================================================

def _choose_pair(wallet_addr: str, balance_pol: float) -> Optional[tuple[str, str, float]]:
    """
    Выбирает случайную пару (sym_in, sym_out, amount) с учётом баланса.

    - POL-пары: нужно hi + 1.0 POL буфер на газ
    - Стейбл-пары: нужно hi стейбла на балансе

    Возвращает None если ничего не доступно.
    """
    from src.modules.executor.erc20 import get_token_balance

    try:
        balance_usdt = get_token_balance(wallet_addr, USDT_POLYGON) or 0.0
    except Exception:
        balance_usdt = 0.0
    try:
        balance_usdc = get_token_balance(wallet_addr, USDC_POLYGON) or 0.0
    except Exception:
        balance_usdc = 0.0

    balances = {
        "POL": balance_pol,
        "USDT": balance_usdt,
        "USDC": balance_usdc,
    }

    available: list[tuple[str, str, float]] = []
    for (sym_in, sym_out), (lo, hi) in AMOUNT_RANGES.items():
        # нужен запас на газ, если свапаем POL
        required = hi + 1.0 if sym_in == "POL" else hi
        if balances.get(sym_in, 0.0) >= required:
            amount = round(random.uniform(lo, hi), 3)
            # перепроверка после округления
            if amount + (1.0 if sym_in == "POL" else 0.0) > balances[sym_in]:
                continue
            available.append((sym_in, sym_out, amount))

    if not available:
        return None
    return random.choice(available)


# ============================================================
# ОСНОВНАЯ ФУНКЦИЯ
# ============================================================

def do_auto_swap(wallet_label: str = "farm-01", force: bool = False) -> Optional[str]:
    """
    Один авто-свап.

    force=True — пропустить проверки (пауза, lazy, лимиты, cooldown, кубик).
    force=False — все проверки, как в проде.
    """
    from src.core.rpc import get_balance_matic

    log.info(f"auto_swap: старт для {wallet_label} (force={force})")

    wallet = _get_wallet(wallet_label)
    if wallet is None:
        log.error(f"auto_swap: кошелёк {wallet_label} не найден в БД")
        return None

    # 1. Пауза
    if not force and _is_paused(wallet_label):
        log.info(f"auto_swap: {wallet_label} на паузе")
        return None

    # 2. Lazy day
    if not force and _check_lazy_day(wallet_label):
        return None

    # 3. Лимит свапов в день
    if not force:
        today_count = _swaps_today(wallet.address)
        if today_count >= MAX_SWAPS_PER_DAY:
            log.info(f"auto_swap: {wallet_label} уже {today_count} свапов сегодня")
            return None

    # 4. Cooldown
    if not force:
        last = _last_swap_time(wallet.address)
        if last is not None:
            elapsed = datetime.utcnow() - last
            if elapsed < timedelta(hours=COOLDOWN_HOURS):
                log.info(
                    f"auto_swap: {wallet_label} cooldown "
                    f"({elapsed.total_seconds() / 60:.0f} мин)"
                )
                return None

    # 5. Баланс POL
    try:
        balance_pol = get_balance_matic(wallet.address)
    except Exception as e:
        log.error(f"auto_swap: не смог получить баланс: {e}")
        return None

    if balance_pol < MIN_BALANCE_POL:
        msg = (
            f"⚠️ auto_swap: {wallet_label} баланс {balance_pol:.4f} POL "
            f"< {MIN_BALANCE_POL}. Стоп."
        )
        log.warning(msg)
        notify_warning(msg)
        return None

    # 6. Выбор пары
    pair = _choose_pair(wallet.address, balance_pol)
    if pair is None:
        log.warning(f"auto_swap: {wallet_label} нет доступных пар (мало токенов)")
        return None

    sym_in, sym_out, amount = pair
    token_in = TOKEN_MAP[sym_in]
    token_out = TOKEN_MAP[sym_out]

    log.success(
        f"auto_swap: {wallet_label} → {amount} {sym_in} → {sym_out}"
    )

    # 7. Свап (без notify — сами уведомим по факту)
    try:
        tx_hash = swap(
            from_label=wallet_label,
            token_in=token_in,
            token_out=token_out,
            amount=amount,
            slippage=1.0,
            wait=True,
            notify=False,
        )
    except Exception as e:
        log.exception(f"auto_swap: swap упал с исключением: {e}")
        tx_hash = None

    # 8. Обработка результата
    if tx_hash is None:
        log.error(f"auto_swap: {wallet_label} свап НЕ удался")
        streak = _failed_streak(wallet.address)
        if streak >= FAILED_STREAK_LIMIT:
            pause_until = datetime.now(timezone.utc) + timedelta(
                hours=PAUSE_AFTER_FAILED_HOURS
            )
            _update_wallet_state(
                wallet_label, paused_until=pause_until.isoformat()
            )
            notify_error(
                f"🚨 auto_swap: {wallet_label} — {streak} провалов подряд. "
                f"Пауза {PAUSE_AFTER_FAILED_HOURS}ч."
            )
        return None

    log.success(f"auto_swap: {wallet_label} OK, TX {tx_hash[:20]}...")
    return tx_hash


# ============================================================
# ДЖОБ ДЛЯ SCHEDULER
# ============================================================

def auto_swap_job() -> None:
    """
    Вызывается scheduler'ом каждый час.
    Окно UTC: 07:00–19:00 (= 10:00–22:00 МСК).
    Внутри окна — кубик 30%: делать сейчас или ждать следующий час.
    """
    now_utc = datetime.now(timezone.utc)

    if not (WINDOW_START_UTC_HOUR <= now_utc.hour < WINDOW_END_UTC_HOUR):
        log.debug(f"auto_swap_job: вне окна (UTC {now_utc.hour}ч), пропуск")
        return

    if random.random() >= DICE_CHANCE:
        log.debug("auto_swap_job: кубик не прошёл (70%), пропуск")
        return

    log.info("auto_swap_job: кубик прошёл, запускаю")
    do_auto_swap("farm-01", force=False)


__all__ = [
    "do_auto_swap",
    "auto_swap_job",
]
