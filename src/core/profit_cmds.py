"""
src/core/profit_cmds.py
Telegram-команда /profit — отчёт о газе и активности.

Использование:
    /profit        — за 7 дней
    /profit 30     — за 30 дней
    /profit 1      — за сутки

Регистрируется из telegram_bot.py через register_handlers(app).
"""

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, ContextTypes

from src.analytics.pnl import format_profit, get_profit_summary
from src.core.logger import get_logger

log = get_logger(__name__)


async def cmd_profit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/profit [days] — отчёт о газе."""
    days = 7
    args = context.args or []
    if args:
        try:
            days = int(args[0])
            if days < 1 or days > 365:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "Использование: <code>/profit [дней]</code>\n"
                "Например: <code>/profit 30</code>",
                parse_mode=ParseMode.HTML,
            )
            return

    try:
        stats = await asyncio.to_thread(get_profit_summary, days)
    except Exception as e:
        log.exception("cmd_profit: ошибка расчёта")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        return

    text = format_profit(stats)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


def register_handlers(app) -> None:
    """Регистрирует /profit в PTB Application."""
    app.add_handler(CommandHandler("profit", cmd_profit))
    log.info("profit_cmds: зарегистрирован /profit")


__all__ = ["register_handlers"]
