"""
src/core/auto_swap.py
Авто-свапы по расписанию. Мультичейн.

Routing:
    - Base + ETH<->токен -> Aerodrome
    - Остальное         -> KyberSwap
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
from src.core.rpc import (
    DEFAULT_CHAIN,
    get_balance_native,
    get_native_symbol,
)
from src.modules.executor.erc20 import TOKENS
from src.services.dex import NATIVE_TOKEN, swap


log = get_logger(__name__)


STATE_FILE = Path("data/auto_swap_state.json")

MAX_SWAPS_PER_DAY = 2
COOLDOWN_HOURS = 4
FAILED_STREAK_LIMIT = 3
PAUSE_AFTER_FAILED_HOURS = 24

LAZY_DAY_CHANCE = 0.15
DICE_CHANCE = 0.30

WINDOW_START_UTC_HOUR = 7
WINDOW_END_UTC_HOUR = 19

MIN_BALANCE_NATIVE = {
    "polygon": 5.0,
    "base": 0.0005,
    "linea": 0.0005,
}

AMOUNT_RANGES = {
    "polygon": {
        ("POL", "USDT"): (1.0, 3.0),
        ("POL", "USDC"): (1.0, 3.0),
        ("USDT", "POL"): (0.3, 1.0),
        ("USDC", "POL"): (0.3, 1.0),
        ("USDT", "USDC"): (0.3, 1.0),
        ("USDC", "USDT"): (0.3, 1.0),
    },
    "base": {
        ("ETH", "USDC"): (0.0001, 0.0005),
        ("USDC", "ETH"): (0.3, 1.0),
        ("USDC", "USDT"): (0.3, 1.0),
        ("USDT", "USDC"): (0.3, 1.0),
    },
    "linea": {
        ("ETH", "USDC"): (0.0001, 0.0005),
        ("USDC", "ETH"): (0.3, 1.0),
        ("USDC", "USDT"): (0.3, 1.0),
        ("USDT", "USDC"): (0.3, 1.0),
    },
}

NATIVE_GAS_BUFFER = {
    "polygon": 1.0,
    "base": 0.00005,
    "linea": 0.00005,
}


def _native_sym(chain: str) -> str:
    s = get_native_symbol(chain)
    return "POL" if chain == "polygon" else s


def _token_map(chain: str) -> dict:
    native_sym = _native_sym(chain)
    result = {native_sym: NATIVE_TOKEN}
    for sym, addr in TOKENS.get(chain, {}).items():
        result[sym] = addr
    return result


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        with STATE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"auto_swap: state read err: {e}")
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with STATE_FILE.open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error(f"auto_swap: state write err: {e}")


def _state_key(wallet_label: str, chain: str) -> str:
    return f"{wallet_label}::{chain}"


def _get_wallet_state(wallet_label: str, chain: str) -> dict:
    state = _load_state()
    key = _state_key(wallet_label, chain)
    default = {
        "lazy_day_date": None,
        "is_lazy_day": False,
        "paused_until": None,
    }
    return state.get(key, default)


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


def _get_wallet(wallet_label: str) -> Optional[Wallet]:
    with SessionLocal() as s:
        return s.execute(
            select(Wallet).where(Wallet.label == wallet_label)
        ).scalar_one_or_none()


def _swaps_today(wallet_addr: str, chain: str) -> int:
    today_start = datetime.utcnow().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    with SessionLocal() as s:
        w = s.execute(
            select(Wallet).where(Wallet.address == wallet_addr)
        ).scalar_one_or_none()
        if not w:
            return 0
        count = s.execute(
            select(func.count(Transaction.id))
            .where(Transaction.wallet_id == w.id)
            .where(Transaction.tx_type == "swap")
            .where(Transaction.chain == chain)
            .where(Transaction.created_at >= today_start)
        ).scalar_one()
        return int(count or 0)


def _last_swap_time(wallet_addr: str, chain: str) -> Optional[datetime]:
    with SessionLocal() as s:
        w = s.execute(
            select(Wallet).where(Wallet.address == wallet_addr)
        ).scalar_one_or_none()
        if not w:
            return None
        last = s.execute(
            select(Transaction)
            .where(Transaction.wallet_id == w.id)
            .where(Transaction.tx_type == "swap")
            .where(Transaction.chain == chain)
            .order_by(desc(Transaction.created_at))
            .limit(1)
        ).scalar_one_or_none()
        return last.created_at if last else None


def _failed_streak(wallet_addr: str, chain: str) -> int:
    with SessionLocal() as s:
        w = s.execute(
            select(Wallet).where(Wallet.address == wallet_addr)
        ).scalar_one_or_none()
        if not w:
            return 0
        recent = s.execute(
            select(Transaction)
            .where(Transaction.wallet_id == w.id)
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


def _is_paused(wallet_label: str, chain: str) -> bool:
    st = _get_wallet_state(wallet_label, chain)
    paused = st.get("paused_until")
    if not paused:
        return False
    try:
        dt = datetime.fromisoformat(paused)
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
        log.info(f"auto_swap: {wallet_label} [{chain}] lazy day")
    return is_lazy


def _choose_pair(wallet_addr: str, chain: str, balance_native: float):
    """
    Выбирает (sym_in, sym_out, amount).

    Проверяем баланс >= lo (минимум диапазона), а не hi.
    Иначе обратные пары не срабатывают, если стейбла меньше максимума.
    """
    from src.modules.executor.erc20 import get_token_balance

    native_sym = _native_sym(chain)
    gas_buffer = NATIVE_GAS_BUFFER.get(chain, 0.001)

    balances = {native_sym: balance_native}
    for sym in ("USDT", "USDC"):
        addr = TOKENS.get(chain, {}).get(sym)
        if not addr:
            continue
        try:
            balances[sym] = get_token_balance(
                wallet_addr, addr, chain=chain
            ) or 0.0
        except Exception:
            balances[sym] = 0.0

    log.debug(f"auto_swap: balances [{chain}]: {balances}")

    ranges = AMOUNT_RANGES.get(chain, {})
    available = []

    for (sym_in, sym_out), (lo, hi) in ranges.items():
        balance_avail = balances.get(sym_in, 0.0)
        gas_needed = gas_buffer if sym_in == native_sym else 0.0
        usable = balance_avail - gas_needed
        if usable < lo:
            continue
        effective_hi = min(hi, usable)
        if effective_hi < lo:
            continue
        amount = round(random.uniform(lo, effective_hi), 6)
        available.append((sym_in, sym_out, amount))

    if not available:
        return None

    native_to_stable = [p for p in available if p[0] == native_sym]
    stable_to_native = [p for p in available if p[1] == native_sym]
    others = [p for p in available
              if p[0] != native_sym and p[1] != native_sym]

    pool = []
    weights = []
    if native_to_stable:
        pool.append(native_to_stable)
        weights.append(0.6)
    if stable_to_native:
        pool.append(stable_to_native)
        weights.append(0.4)
    if others:
        pool.append(others)
        weights.append(0.2)

    if not pool:
        return None

    chosen_pool = random.choices(pool, weights=weights, k=1)[0]
    return random.choice(chosen_pool)


def _do_swap(
    chain: str,
    wallet_label: str,
    sym_in: str,
    sym_out: str,
    token_in: str,
    token_out: str,
    amount: float,
) -> Optional[str]:
    if chain == "base":
        native_sym = _native_sym(chain)
        in_native = (sym_in == native_sym)
        out_native = (sym_out == native_sym)
        if in_native != out_native:
            from src.services.aerodrome import swap_aerodrome
            log.info(f"auto_swap: routing Aerodrome [{chain}]")
            return swap_aerodrome(
                from_label=wallet_label,
                token_in=sym_in,
                token_out=sym_out,
                amount=amount,
                slippage=5.0,
                wait=True,
                notify=False,
            )

    log.info(f"auto_swap: routing KyberSwap [{chain}]")
    return swap(
        from_label=wallet_label,
        token_in=token_in,
        token_out=token_out,
        amount=amount,
        chain=chain,
        slippage=5.0,
        wait=True,
        notify=False,
    )


def do_auto_swap(
    wallet_label: str = "farm-01",
    chain: str = DEFAULT_CHAIN,
    force: bool = False,
) -> Optional[str]:
    native_sym = _native_sym(chain)
    log.info(f"auto_swap: старт {wallet_label} [{chain}] force={force}")

    wallet = _get_wallet(wallet_label)
    if wallet is None:
        log.error(f"auto_swap: кошелёк {wallet_label} не найден")
        return None

    if not force and _is_paused(wallet_label, chain):
        log.info(f"auto_swap: {wallet_label} [{chain}] на паузе")
        return None

    if not force and _check_lazy_day(wallet_label, chain):
        return None

    if not force:
        today_count = _swaps_today(wallet.address, chain)
        if today_count >= MAX_SWAPS_PER_DAY:
            log.info(
                f"auto_swap: {wallet_label} [{chain}] уже "
                f"{today_count} свапов сегодня"
            )
            return None

    if not force:
        last = _last_swap_time(wallet.address, chain)
        if last is not None:
            elapsed = datetime.utcnow() - last
            if elapsed < timedelta(hours=COOLDOWN_HOURS):
                log.info(
                    f"auto_swap: {wallet_label} [{chain}] cooldown "
                    f"{elapsed.total_seconds() / 60:.0f} мин"
                )
                return None

    try:
        balance_native = get_balance_native(wallet.address, chain=chain)
    except Exception as e:
        log.error(f"auto_swap: баланс [{chain}] err: {e}")
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

    pair = _choose_pair(wallet.address, chain, balance_native)
    if pair is None:
        log.warning(
            f"auto_swap: {wallet_label} [{chain}] нет пар "
            f"(мало токенов)"
        )
        return None

    sym_in, sym_out, amount = pair
    tmap = _token_map(chain)
    token_in = tmap[sym_in]
    token_out = tmap[sym_out]

    log.success(
        f"auto_swap: {wallet_label} [{chain}] -> "
        f"{amount} {sym_in} -> {sym_out}"
    )

    try:
        tx_hash = _do_swap(
            chain, wallet_label,
            sym_in, sym_out,
            token_in, token_out,
            amount,
        )
    except Exception as e:
        log.exception(f"auto_swap: swap [{chain}] exception: {e}")
        tx_hash = None

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
                f"🚨 auto_swap: {wallet_label} [{chain}] "
                f"{streak} провалов подряд. Пауза "
                f"{PAUSE_AFTER_FAILED_HOURS}ч."
            )
        return None

    log.success(
        f"auto_swap: {wallet_label} [{chain}] OK, "
        f"TX {tx_hash[:20]}..."
    )
    return tx_hash


ACTIVE_CHAINS_FOR_AUTOSWAP = ["polygon"]
AUTOSWAP_WALLET = "farm-01"


def auto_swap_job() -> None:
    now_utc = datetime.now(timezone.utc)

    if not (WINDOW_START_UTC_HOUR <= now_utc.hour < WINDOW_END_UTC_HOUR):
        log.debug(f"auto_swap_job: вне окна UTC {now_utc.hour}ч")
        return

    if random.random() >= DICE_CHANCE:
        log.debug("auto_swap_job: кубик не прошёл")
        return

    log.info("auto_swap_job: кубик прошёл, запускаю")

    for chain in ACTIVE_CHAINS_FOR_AUTOSWAP:
        try:
            do_auto_swap(AUTOSWAP_WALLET, chain=chain, force=False)
        except Exception as e:
            log.exception(f"auto_swap_job: {chain} exception: {e}")


__all__ = [
    "do_auto_swap",
    "auto_swap_job",
    "ACTIVE_CHAINS_FOR_AUTOSWAP",
    "AUTOSWAP_WALLET",
]
