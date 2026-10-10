"""
src/analytics/pnl.py
Аналитика газа и PnL по транзакциям.

Сейчас считается только расход (газ). Доход от аирдропов — позже,
когда появится учёт claim'ов.

Особенности:
    - Курс MATIC/USD через CoinGecko, кэш 5 минут
    - Если API недоступен — показываем только MATIC, без USD
    - gas_usd в БД фактически содержит MATIC (историческое имя поля)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy import select

from src.core.database import SessionLocal, Transaction, Wallet
from src.core.logger import get_logger

log = get_logger(__name__)


# ============================================================
# КУРС MATIC/USD
# ============================================================

_RATE_CACHE: dict = {"rate": None, "fetched_at": None}
_RATE_TTL_SECONDS = 300  # 5 минут


def get_matic_usd_rate() -> Optional[float]:
    """
    Курс MATIC (POL) → USD через CoinGecko.
    Кэш 5 минут. При ошибке возвращает None (не падаем).
    """
    now = datetime.utcnow()
    cached = _RATE_CACHE

    if cached["rate"] is not None and cached["fetched_at"] is not None:
        age = (now - cached["fetched_at"]).total_seconds()
        if age < _RATE_TTL_SECONDS:
            return cached["rate"]

    try:
        r = httpx.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "matic-network", "vs_currencies": "usd"},
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()
        rate = float(data["matic-network"]["usd"])
        _RATE_CACHE["rate"] = rate
        _RATE_CACHE["fetched_at"] = now
        log.debug(f"pnl: MATIC/USD = {rate}")
        return rate
    except Exception as e:
        log.warning(f"pnl: не смог получить курс MATIC/USD: {e}")
        return cached["rate"]  # вернём старый кэш если есть


# ============================================================
# РАСЧЁТ
# ============================================================

def _aggregate(txs: list[Transaction]) -> dict:
    """
    Внутренняя агрегация списка транзакций.
    Возвращает dict со счётчиками, газом, разбивкой.
    """
    total = len(txs)
    success = sum(1 for t in txs if t.status == "success")
    failed = sum(1 for t in txs if t.status == "failed")
    pending = sum(1 for t in txs if t.status == "pending")

    gas_matic = sum(float(t.gas_usd or 0.0) for t in txs)

    by_type: dict[str, int] = {}
    for t in txs:
        by_type[t.tx_type] = by_type.get(t.tx_type, 0) + 1

    # Активные дни (уникальные даты)
    active_days = len({t.created_at.date() for t in txs if t.created_at})

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "pending": pending,
        "gas_matic": gas_matic,
        "by_type": by_type,
        "active_days": active_days,
    }


def get_profit_summary(days: int = 7) -> dict:
    """
    Статистика за последние `days` дней + общая по всем транзакциям.

    Возвращает dict:
        {
            "days": 7,
            "period": {...агрегация за период...},
            "all_time": {...агрегация всего...},
            "by_wallet": [{"label", "total", "gas_matic"}, ...],
            "matic_usd": float | None,
        }
    """
    since = datetime.utcnow() - timedelta(days=days)

    with SessionLocal() as s:
        all_txs = list(s.execute(select(Transaction)).scalars().all())
        period_txs = [t for t in all_txs if t.created_at and t.created_at >= since]
        wallets = list(s.execute(select(Wallet)).scalars().all())
        wallet_by_id = {w.id: w for w in wallets}

    period = _aggregate(period_txs)
    all_time = _aggregate(all_txs)

    # Разбивка по кошелькам (за всё время)
    by_wallet_map: dict[int, dict] = {}
    for t in all_txs:
        wid = t.wallet_id
        if wid not in by_wallet_map:
            w = wallet_by_id.get(wid)
            by_wallet_map[wid] = {
                "label": w.label if w else f"id={wid}",
                "total": 0,
                "gas_matic": 0.0,
            }
        by_wallet_map[wid]["total"] += 1
        by_wallet_map[wid]["gas_matic"] += float(t.gas_usd or 0.0)

    by_wallet = sorted(
        by_wallet_map.values(),
        key=lambda x: x["gas_matic"],
        reverse=True,
    )

    return {
        "days": days,
        "period": period,
        "all_time": all_time,
        "by_wallet": by_wallet,
        "matic_usd": get_matic_usd_rate(),
    }


# ============================================================
# ФОРМАТИРОВАНИЕ ДЛЯ TELEGRAM
# ============================================================

def _fmt_gas(matic: float, rate: Optional[float]) -> str:
    """Формат газа: 'X.XXXX MATIC (~$Y.YYYY)' или без USD."""
    if rate is None:
        return f"{matic:.4f} MATIC"
    usd = matic * rate
    return f"{matic:.4f} MATIC (~${usd:.4f})"


def format_profit(stats: dict) -> str:
    """HTML-сообщение для Telegram."""
    if not stats or stats.get("all_time", {}).get("total", 0) == 0:
        return (
            "💰 <b>Profit Report</b>\n\n"
            "Транзакций пока нет. Запусти <code>/swap</code> чтобы начать, "
            "или дождись авто-свапа от scheduler."
        )

    days = stats["days"]
    period = stats["period"]
    all_time = stats["all_time"]
    rate = stats["matic_usd"]

    lines = [
        "💰 <b>Profit Report</b>",
        "",
        f"<b>📊 Всего:</b>",
        f"  Транзакций: {all_time['total']} "
        f"(✅ {all_time['success']}  ❌ {all_time['failed']}",
    ]
    if all_time["pending"]:
        lines[-1] += f"  ⏳ {all_time['pending']}"
    lines[-1] += ")"
    lines.append(f"  Активных дней: {all_time['active_days']}")
    lines.append(f"  Газ: {_fmt_gas(all_time['gas_matic'], rate)}")

    lines.append("")
    lines.append(f"<b>📅 За {days} дн.:</b>")
    if period["total"] == 0:
        lines.append("  Транзакций нет")
    else:
        lines.append(
            f"  Транзакций: {period['total']} "
            f"(✅ {period['success']}  ❌ {period['failed']})"
        )
        lines.append(f"  Газ: {_fmt_gas(period['gas_matic'], rate)}")

    if stats.get("by_wallet"):
        lines.append("")
        lines.append("<b>👛 По кошелькам:</b>")
        for w in stats["by_wallet"]:
            gas_str = _fmt_gas(w["gas_matic"], rate)
            lines.append(f"  • {w['label']}: {w['total']} tx | {gas_str}")

    if all_time["by_type"]:
        lines.append("")
        lines.append("<b>🔀 По типам:</b>")
        for ttype, cnt in sorted(
            all_time["by_type"].items(), key=lambda x: -x[1]
        ):
            lines.append(f"  • {ttype}: {cnt}")

    if rate is None:
        lines.append("")
        lines.append("<i>⚠️ Курс MATIC/USD недоступен, только MATIC</i>")

    return "\n".join(lines)


__all__ = [
    "get_matic_usd_rate",
    "get_profit_summary",
    "format_profit",
]
