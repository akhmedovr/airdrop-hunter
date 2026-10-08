"""
src/core/swap_cmds.py
/quote и /swap команды для Telegram.
"""
import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from src.core.config import settings
from src.core.logger import get_logger

log = get_logger(__name__)


def _is_owner(update: Update) -> bool:
    if not update.effective_chat:
        return False
    return str(update.effective_chat.id) == str(settings.TELEGRAM_CHAT_ID)


async def _reject(update: Update) -> None:
    if update.message:
        await update.message.reply_text("Приватный бот")


async def cmd_quote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        await _reject(update)
        return
    if len(context.args) < 3:
        await update.message.reply_text("Использование: /quote FROM TO AMOUNT")
        return
    t_in, t_out, amt_s = context.args[0], context.args[1], context.args[2]
    try:
        amt = float(amt_s)
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом")
        return
    await update.message.reply_text("Запрашиваю курс...")
    def _run():
        from src.services.dex import get_quote
        from src.modules.wallets.manager import get_all_wallets
        wallets = get_all_wallets()
        if not wallets:
            return None
        return get_quote(t_in, t_out, amt, wallets[0].address)
    try:
        q = await asyncio.to_thread(_run)
    except Exception as e:
        log.exception("quote err")
        await update.message.reply_text(f"Ошибка: {str(e)[:150]}")
        return
    if not q:
        await update.message.reply_text("Курс не получен")
        return
    txt = f"Курс: {q['from_amount']} {q['from_symbol']} -> {q['to_amount']:.6f} {q['to_symbol']}"
    await update.message.reply_text(txt)


async def cmd_swap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        await _reject(update)
        return
    if len(context.args) < 3:
        await update.message.reply_text("Использование: /swap FROM TO AMOUNT")
        return
    t_in, t_out, amt_s = context.args[0], context.args[1], context.args[2]
    try:
        amt = float(amt_s)
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом")
        return
    await update.message.reply_text(f"Запускаю свап {amt} {t_in} -> {t_out}...")
    def _run():
        from src.services.dex import swap
        from src.modules.wallets.manager import get_all_wallets
        wallets = get_all_wallets()
        if not wallets:
            return None
        w = wallets[0]
        return swap(from_label=w.label, token_in=t_in, token_out=t_out, amount=amt, slippage=1.0, wait=True, notify=True)
    try:
        tx = await asyncio.to_thread(_run)
    except Exception as e:
        log.exception("swap err")
        await update.message.reply_text(f"Ошибка: {str(e)[:150]}")
        return
    if tx:
        await update.message.reply_text(f"Tx: {tx[:20]}...")
    else:
        await update.message.reply_text("Свап не выполнен")


def register_swap_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("quote", cmd_quote))
    app.add_handler(CommandHandler("swap", cmd_swap))
