"""
src/core/telegram_wallet_cmds.py
Команды Telegram-бота для управления кошельками.

Использование (в telegram_bot.py):
    from src.core.telegram_wallet_cmds import register_wallet_handlers
    register_wallet_handlers(app)

Команды:
    /create_wallet <label>          — создать новый farming-кошелёк
    /balance <address|label>        — показать баланс одного кошелька
    /rename_wallet <address> <label> — переименовать кошелёк
"""

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from src.core.config import settings
from src.core.logger import get_logger
from src.core.notifier import notify_success

log = get_logger(__name__)


def _is_owner(update: Update) -> bool:
    """Проверяет, что команда от владельца бота."""
    if not update.effective_chat:
        return False
    return str(update.effective_chat.id) == str(settings.TELEGRAM_CHAT_ID)


async def _reject(update: Update) -> None:
    """Отклоняет команду не от владельца."""
    if update.message:
        await update.message.reply_text("⛔ Бот приватный.")


# --- /create_wallet ---

async def cmd_create_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Создаёт новый farming-кошелёк.
    Использование: /create_wallet <метка>
    Пример: /create_wallet farm-02
    """
    if not _is_owner(update):
        await _reject(update)
        return

    if not context.args:
        await update.message.reply_text(
            "Использование: <code>/create_wallet &lt;метка&gt;</code>\n"
            "Пример: <code>/create_wallet farm-02</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    label = " ".join(context.args).strip()[:32]

    def _create() -> dict:
        from src.modules.wallets.manager import (
            generate_wallet,
            save_wallet,
        )

        wallet_data = generate_wallet(label=label, wallet_type="farming")
        saved = save_wallet(
            address=wallet_data["address"],
            private_key=wallet_data["private_key"],
            label=wallet_data["label"],
            wallet_type=wallet_data["wallet_type"],
        )
        return {
            "address": wallet_data["address"],
            "label": label,
            "saved": saved is not None,
        }

    try:
        result = await asyncio.to_thread(_create)
    except Exception as e:
        log.exception("Ошибка создания кошелька")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        return

    if not result["saved"]:
        await update.message.reply_text("❌ Не удалось сохранить в БД")
        return

    # Уведомление в Telegram (дублируем через notifier)
    notify_success(f"👛 Новый кошелёк: {result['label']} | {result['address'][:10]}...")

    await update.message.reply_text(
        f"✅ <b>Кошелёк создан</b>\n\n"
        f"Метка: <code>{result['label']}</code>\n"
        f"Адрес: <code>{result['address']}</code>\n\n"
        f"<i>Приватный ключ зашифрован и сохранён в БД.</i>",
        parse_mode=ParseMode.HTML,
    )


# --- /balance ---

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Показывает баланс одного кошелька.
    Использование: /balance <address|label>
    """
    if not _is_owner(update):
        await _reject(update)
        return

    if not context.args:
        await update.message.reply_text(
            "Использование: <code>/balance &lt;адрес или метка&gt;</code>\n"
            "Пример: <code>/balance farm-01</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    query = " ".join(context.args).strip()

    def _check() -> dict:
        from src.core.rpc import get_balance_matic
        from src.modules.wallets.manager import get_all_wallets

        wallets = get_all_wallets()

        # Ищем: сначала по адресу, потом по метке
        target = None
        for w in wallets:
            if w.address.lower() == query.lower():
                target = w
                break
        if target is None:
            for w in wallets:
                if w.label.lower() == query.lower():
                    target = w
                    break

        if target is None:
            return {"found": False}

        try:
            bal = get_balance_matic(target.address)
        except Exception as e:
            return {"found": True, "error": str(e)[:200]}

        return {
            "found": True,
            "address": target.address,
            "label": target.label,
            "balance": bal,
        }

    try:
        result = await asyncio.to_thread(_check)
    except Exception as e:
        log.exception("Ошибка /balance")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        return

    if not result["found"]:
        await update.message.reply_text(f"🤷 Кошелёк <code>{query}</code> не найден.", parse_mode=ParseMode.HTML)
        return

    if "error" in result:
        await update.message.reply_text(f"❌ Ошибка RPC: <code>{result['error']}</code>", parse_mode=ParseMode.HTML)
        return

    await update.message.reply_text(
        f"💰 <b>Баланс</b>\n\n"
        f"Метка: <code>{result['label']}</code>\n"
        f"Адрес: <code>{result['address'][:10]}...{result['address'][-6:]}</code>\n"
        f"Баланс: <b>{result['balance']:.6f} MATIC</b>",
        parse_mode=ParseMode.HTML,
    )


# --- /rename_wallet ---

async def cmd_rename_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Переименовывает кошелёк.
    Использование: /rename_wallet <адрес> <новая_метка>
    """
    if not _is_owner(update):
        await _reject(update)
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Использование: <code>/rename_wallet &lt;адрес&gt; &lt;новая_метка&gt;</code>\n"
            "Пример: <code>/rename_wallet 0xAd7d... farm-01</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    address = context.args[0].strip()
    new_label = " ".join(context.args[1:]).strip()[:32]

    def _rename() -> dict:
        from sqlalchemy import select
        from src.core.database import get_session, Wallet

        with get_session() as session:
            wallet = session.execute(
                select(Wallet).where(Wallet.address == address)
            ).scalar_one_or_none()

            if wallet is None:
                return {"found": False}

            old_label = wallet.label
            wallet.label = new_label
            session.commit()

            return {"found": True, "old": old_label, "new": new_label}

    try:
        result = await asyncio.to_thread(_rename)
    except Exception as e:
        log.exception("Ошибка /rename_wallet")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        return

    if not result["found"]:
        await update.message.reply_text("🤷 Кошелёк не найден.")
        return

    await update.message.reply_text(
        f"✅ Переименован:\n"
        f"<code>{result['old']}</code> → <code>{result['new']}</code>",
        parse_mode=ParseMode.HTML,
    )


def register_wallet_handlers(app: Application) -> None:
    """Регистрирует команды управления кошельками в приложении."""
    app.add_handler(CommandHandler("create_wallet", cmd_create_wallet))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("rename_wallet", cmd_rename_wallet))


__all__ = [
    "register_wallet_handlers",
    "cmd_create_wallet",
    "cmd_balance",
    "cmd_rename_wallet",
]
