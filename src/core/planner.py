"""
src/core/planner.py
Мозг бота: планирование задач, трекинг прогресса.

Идея: бот — голова, пользователь — руки.
Бот знает какие кампании фармим, генерирует задачи, отслеживает прогресс.

Модели БД:
    Airdrop — кампания (name, status)
    Task    — задача (description, task_type, status)

Команды в Telegram:
    /today    — показать pending задачи
    /done <id> — отметить задачу выполненной
    /progress — общий прогресс по кампаниям
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select

from src.core.database import Airdrop, Task, get_session
from src.core.logger import get_logger

log = get_logger(__name__)


# ============================================================
# SEED — что засеем при первом запуске
# ============================================================
# Позже вынесем в YAML. Сейчас — хардкод, чтобы стартовать быстро.

SEED_CAMPAIGNS: list[dict] = [
    {
        "name": "Polygon Warmup",
        "status": "active",
        "tasks": [
            ("Swap 0.3 POL → USDT через Kyber [farm-01]", "swap"),
            ("Follow @KyberNetwork в X", "social"),
            ("Approve USDC на Kyber router [farm-01]", "swap"),
            ("Swap 0.3 USDT → POL обратно [farm-01]", "swap"),
            ("Retweet анонс KyberSwap", "social"),
        ],
    },
    {
        "name": "Galxe Social Starter",
        "status": "active",
        "tasks": [
            ("Зайти на Galxe через email", "social"),
            ("Пройти 1 квест с наградой Points", "social"),
            ("Пройти квест с наградой Galxe Gold", "social"),
            ("Собрать 50+ Points на Galxe", "social"),
            ("Собрать 30+ GG на Galxe", "social"),
        ],
    },
]


# ============================================================
# SEED
# ============================================================

def seed_campaigns() -> int:
    """
    Заполняет БД кампаниями, если она пуста.
    Возвращает количество созданных кампаний.
    Безопасно вызывать многократно (idempotent).
    """
    created = 0
    try:
        with get_session() as session:
            existing = session.execute(select(Airdrop)).scalars().all()
            if existing:
                log.info(f"planner: БД уже содержит {len(existing)} кампаний, seed не нужен")
                return 0

            for camp in SEED_CAMPAIGNS:
                airdrop = Airdrop(
                    name=camp["name"],
                    status=camp["status"],
                )
                session.add(airdrop)
                session.flush()  # получаем airdrop.id

                for desc, ttype in camp["tasks"]:
                    session.add(Task(
                        airdrop_id=airdrop.id,
                        description=desc,
                        task_type=ttype,
                        status="pending",
                    ))
                created += 1

            session.commit()
            log.success(f"planner: засеяно {created} кампаний, "
                        f"{sum(len(c['tasks']) for c in SEED_CAMPAIGNS)} задач")
            return created
    except Exception as e:
        log.error(f"planner: ошибка seed: {e}")
        return 0


# ============================================================
# ЧТЕНИЕ
# ============================================================

def get_today_tasks(limit: int = 5) -> list[Task]:
    """
    Возвращает pending задачи (макс limit).
    Порядок: сначала swap (on-chain), потом social — чтобы быстрое вперёд.
    """
    try:
        with get_session() as session:
            stmt = (
                select(Task)
                .where(Task.status == "pending")
                .order_by(Task.id)
                .limit(limit)
            )
            return list(session.execute(stmt).scalars().all())
    except Exception as e:
        log.error(f"planner: get_today_tasks ошибка: {e}")
        return []


def get_task_by_id(task_id: int) -> Optional[Task]:
    """Возвращает задачу по id."""
    try:
        with get_session() as session:
            return session.execute(
                select(Task).where(Task.id == task_id)
            ).scalar_one_or_none()
    except Exception as e:
        log.error(f"planner: get_task_by_id ошибка: {e}")
        return None


def get_progress() -> dict:
    """
    Сводка по всем кампаниям и задачам.
    """
    try:
        with get_session() as session:
            campaigns = session.execute(select(Airdrop)).scalars().all()
            tasks = session.execute(select(Task)).scalars().all()

            by_status = {"pending": 0, "completed": 0, "failed": 0}
            for t in tasks:
                by_status[t.status] = by_status.get(t.status, 0) + 1

            by_type: dict[str, int] = {}
            for t in tasks:
                by_type[t.task_type] = by_type.get(t.task_type, 0) + 1

            campaign_stats = []
            for c in campaigns:
                c_tasks = [t for t in tasks if t.airdrop_id == c.id]
                c_done = sum(1 for t in c_tasks if t.status == "completed")
                campaign_stats.append({
                    "name": c.name,
                    "status": c.status,
                    "total": len(c_tasks),
                    "done": c_done,
                })

            return {
                "total_campaigns": len(campaigns),
                "total_tasks": len(tasks),
                "by_status": by_status,
                "by_type": by_type,
                "campaigns": campaign_stats,
            }
    except Exception as e:
        log.error(f"planner: get_progress ошибка: {e}")
        return {}


# ============================================================
# ЗАПИСЬ
# ============================================================

def mark_task_done(task_id: int) -> bool:
    """Помечает задачу completed. True при успехе."""
    try:
        with get_session() as session:
            task = session.execute(
                select(Task).where(Task.id == task_id)
            ).scalar_one_or_none()
            if task is None:
                log.warning(f"planner: задача #{task_id} не найдена")
                return False
            if task.status == "completed":
                log.info(f"planner: задача #{task_id} уже была completed")
                return True

            task.status = "completed"
            task.completed_at = datetime.utcnow()
            session.commit()
            log.success(f"planner: задача #{task_id} → completed")
            return True
    except Exception as e:
        log.error(f"planner: mark_task_done ошибка: {e}")
        return False


def mark_task_failed(task_id: int, error: str = "") -> bool:
    """Помечает задачу failed с сообщением об ошибке."""
    try:
        with get_session() as session:
            task = session.execute(
                select(Task).where(Task.id == task_id)
            ).scalar_one_or_none()
            if task is None:
                return False

            task.status = "failed"
            task.error_message = error[:500] if error else None
            session.commit()
            log.warning(f"planner: задача #{task_id} → failed: {error[:80]}")
            return True
    except Exception as e:
        log.error(f"planner: mark_task_failed ошибка: {e}")
        return False


# ============================================================
# ФОРМАТИРОВАНИЕ ДЛЯ TELEGRAM
# ============================================================

def format_today(tasks: list[Task]) -> str:
    """Форматирует список задач на сегодня (HTML)."""
    if not tasks:
        return (
            "📭 <b>Все задачи выполнены!</b>\n\n"
            "Новых пока нет. Отличная работа.\n"
            "Бот пришлёт следующую партию, когда добавим кампании."
        )

    icons = {
        "swap": "🔄",
        "bridge": "🌉",
        "social": "🐦",
        "other": "📌",
    }
    lines = [f"☀️ <b>План на сегодня ({len(tasks)})</b>", ""]
    for t in tasks:
        icon = icons.get(t.task_type, "📌")
        lines.append(f"{icon} <b>#{t.id}</b> — {t.description}")
        lines.append(f"    <i>тип: {t.task_type}</i>")
        lines.append("")
    lines.append("Когда выполнишь — жми: <code>/done &lt;id&gt;</code>")
    return "\n".join(lines)


def format_progress(stats: dict) -> str:
    """Форматирует отчёт о прогрессе (HTML)."""
    if not stats or stats.get("total_tasks", 0) == 0:
        return (
            "📊 <b>Прогресс</b>\n\n"
            "Пока пусто. Запусти <code>/today</code> чтобы получить задачи."
        )

    bs = stats.get("by_status", {})
    done = bs.get("completed", 0)
    pending = bs.get("pending", 0)
    failed = bs.get("failed", 0)
    total = stats["total_tasks"]

    pct = int(100 * done / total) if total else 0
    bar_len = 12
    filled = int(bar_len * pct / 100)
    bar = "█" * filled + "░" * (bar_len - filled)

    lines = [
        "📊 <b>Прогресс</b>",
        "",
        f"<code>{bar}</code>  {pct}%",
        f"✅ Выполнено: {done}/{total}",
        f"⏳ Осталось: {pending}",
    ]
    if failed:
        lines.append(f"❌ Провалено: {failed}")

    lines.append("")
    lines.append("<b>По кампаниям:</b>")
    for c in stats.get("campaigns", []):
        c_pct = int(100 * c["done"] / c["total"]) if c["total"] else 0
        lines.append(f"• {c['name']}: {c['done']}/{c['total']} ({c_pct}%)")

    return "\n".join(lines)


__all__ = [
    "seed_campaigns",
    "get_today_tasks",
    "get_task_by_id",
    "get_progress",
    "mark_task_done",
    "mark_task_failed",
    "format_today",
    "format_progress",
]
