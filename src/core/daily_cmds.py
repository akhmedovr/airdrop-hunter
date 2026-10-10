"""
src/core/daily_cmds.py
Telegram-команды для работы с планом задач.

Регистрируются из telegram_bot.py через register_handlers(app).

Команды:
    /today    — показать pending задачи (макс 5)
    /done <id> — отметить задачу выполненной
    /progress — общий прогресс по кампаниям

При первом вызове register_handlers() выполняет seed_campaigns(),
чтобы в БД появились стартовые кампании.
"""

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from src.core.logger import get_logger
from src.core.planner import (
    format_progress,
    format_today,
    get_progress,
    get_task_by_id,
    get_today_tasks,
    mark_task_done,
    seed_campaigns,
)

log = get_logger(__name__)


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/today — задачи на сегодня."""
    tasks = get_today_tasks(limit=5)
    text = format_today(tasks)
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/done <id> — отметить задачу выполненной."""
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Использование: <code>/done 3</code>", parse_mode="HTML"
        )
        return

    try:
        task_id = int(args[0])
    except ValueError:
        await update.message.reply_text(
            f"❌ Неверный id: <code>{args[0]}</code>", parse_mode="HTML"
        )
        return

    task = get_task_by_id(task_id)
    if task is None:
        await update.message.reply_text(f"❌ Задача #{task_id} не найдена")
        return

    if task.status == "completed":
        await update.message.reply_text(f"ℹ️ Задача #{task_id} уже выполнена")
        return

    ok = mark_task_done(task_id)
    if ok:
        await update.message.reply_text(
            f"✅ Задача #{task_id} выполнена!\n\n"
            f"<i>{task.description}</i>",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(f"❌ Не удалось отметить #{task_id}")


async def cmd_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/progress — общий прогресс."""
    stats = get_progress()
    text = format_progress(stats)
    await update.message.reply_text(text, parse_mode="HTML")


def register_handlers(app) -> None:
    """
    Регистрирует команды в PTB Application.
    Вызывается из telegram_bot.py после создания app.
    """
    # seed выполняется один раз при старте, безопасно повторять
    try:
        seed_campaigns()
    except Exception as e:
        log.error(f"daily_cmds: seed_campaigns упал: {e}")

    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("progress", cmd_progress))
    log.info("daily_cmds: зарегистрированы /today, /done, /progress")


__all__ = ["register_handlers"]
