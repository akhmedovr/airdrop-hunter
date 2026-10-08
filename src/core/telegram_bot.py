"""
src/core/telegram_bot.py
Telegram-бот для управления Airdrop Hunter.

Режим: long polling. Принимает команды только от владельца
(chat_id из .env), всё остальное игнорирует.

Команды:
    /start    — приветствие
    /help     — список команд
    /ping     — проверить, что бот жив
    /status   — статус системы (RPC, кошельки, окружение)
    /wallets  — список кошельков с балансами
    /scan     — запустить сканер DeFiLlama вручную
    /quests   — активные квесты Galxe

Запуск:
    python -m src.core.telegram_bot
"""

import asyncio
from datetime import datetime, timezone

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from src.core.config import settings
from src.core.logger import get_logger

log = get_logger(__name__)

# Время старта процесса — для /status
_START_TIME = datetime.now(timezone.utc)


def _is_owner(update: Update) -> bool:
    """Проверяет, что команда пришла от владельца бота."""
    if not update.effective_chat:
        return False
    return str(update.effective_chat.id) == str(settings.TELEGRAM_CHAT_ID)


async def _reject(update: Update) -> None:
    """Вежливо отказывает не-владельцу и логирует попытку."""
    chat_id = update.effective_chat.id if update.effective_chat else "unknown"
    user = update.effective_user.username if update.effective_user else "unknown"
    log.warning(f"Отклонена команда от чужого chat_id={chat_id} (@{user})")
    if update.message:
        await update.message.reply_text("⛔ Бот приватный.")


# --- Хендлеры команд ---

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        await _reject(update)
        return
    text = (
        "🤖 <b>Airdrop Hunter</b>\n\n"
        "Я управляю твоим ботом-охотником за аирдропами.\n"
        "Напиши /help — покажу, что умею."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        await _reject(update)
        return
    text = (
        "<b>📋 Доступные команды:</b>\n\n"
        "<b>Система:</b>\n"
        "/ping — проверить, что бот жив\n"
        "/status — состояние системы\n"
        "/help — это сообщение\n\n"
        "<b>Кошельки:</b>\n"
        "/wallets — список всех кошельков\n"
        "/create_wallet &lt;метка&gt; — создать кошелёк\n"
        "/balance &lt;адрес|метка&gt; — баланс одного кошелька\n"
        "/rename_wallet &lt;адрес&gt; &lt;метка&gt; — переименовать\n\n"
        "<b>Аирдропы:</b>\n"
        "/scan — запустить сканер DeFiLlama\n"
        "/quests — активные квесты Galxe"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        await _reject(update)
        return
    now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    await update.message.reply_text(f"🏓 Pong! {now}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        await _reject(update)
        return

    def _collect() -> dict:
        from src.core.rpc import get_active_rpc, get_web3, get_gas_price_gwei
        from src.modules.wallets.manager import wallets_summary
        from src.core.proxy import proxy_status

        info: dict = {
            "environment": settings.ENVIRONMENT,
            "log_level": settings.LOG_LEVEL,
            "rpc_active": None,
            "block": None,
            "gas_gwei": None,
            "rpc_error": None,
            "wallets": None,
            "proxies": None,
        }
        try:
            w3 = get_web3()
            info["rpc_active"] = get_active_rpc()
            info["block"] = w3.eth.block_number
            info["gas_gwei"] = get_gas_price_gwei()
        except Exception as e:
            info["rpc_error"] = str(e)[:200]

        try:
            info["wallets"] = wallets_summary()
        except Exception as e:
            info["wallets"] = {"error": str(e)[:200]}

        try:
            info["proxies"] = proxy_status()
        except Exception as e:
            info["proxies"] = {"error": str(e)[:200]}

        return info

    info = await asyncio.to_thread(_collect)

    uptime = datetime.now(timezone.utc) - _START_TIME
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    lines = [
        "<b>📊 Статус системы</b>",
        "",
        f"Окружение: <code>{info['environment']}</code>",
        f"Лог: <code>{info['log_level']}</code>",
        f"Uptime: {hours}ч {minutes}м {seconds}с",
        "",
    ]

    if info["rpc_error"]:
        lines.append(f"❌ RPC: <code>{info['rpc_error']}</code>")
    else:
        lines.append(f"✅ RPC: <code>{info['rpc_active']}</code>")
        lines.append(f"Блок: <code>{info['block']}</code>")
        lines.append(f"Gas: <code>{info['gas_gwei']:.2f} Gwei</code>")

    lines.append("")

    wallets = info["wallets"]
    if isinstance(wallets, dict) and "total" in wallets:
        lines.append(
            f"👛 Кошельков: {wallets['total']} "
            f"(farming: {wallets.get('farming', 0)}, "
            f"cold: {wallets.get('cold', 0)})"
        )
    else:
        lines.append(f"👛 Кошельки: ошибка — {wallets}")

    proxies = info["proxies"]
    if isinstance(proxies, dict) and "total_configured" in proxies:
        labels = ", ".join(proxies.get("labels", []))
        lines.append(f"🛡 Прокси: {proxies['total_configured']} ({labels})")
    else:
        lines.append(f"🛡 Прокси: ошибка — {proxies}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        await _reject(update)
        return

    def _collect() -> list[dict]:
        from src.core.rpc import get_balance_matic
        from src.core.proxy import get_proxy_for_wallet
        from src.modules.wallets.manager import get_all_wallets

        result = []
        for w in get_all_wallets():
            try:
                proxy = get_proxy_for_wallet(w.address)
                bal = get_balance_matic(w.address, proxy=proxy)
            except Exception as e:
                log.warning(f"Не смог получить баланс {w.address[:10]}: {e}")
                bal = None
            result.append({
                "address": w.address,
                "label": w.label,
                "type": w.wallet_type,
                "balance_matic": bal,
            })
        return result

    wallets = await asyncio.to_thread(_collect)

    if not wallets:
        await update.message.reply_text("👛 Кошельков пока нет.")
        return

    lines = ["<b>👛 Кошельки:</b>", ""]
    for i, w in enumerate(wallets, 1):
        addr_short = f"{w['address'][:6]}...{w['address'][-4:]}"
        bal_str = (
            f"{w['balance_matic']:.4f} MATIC"
            if w["balance_matic"] is not None
            else "ошибка"
        )
        lines.append(
            f"{i}. <code>{addr_short}</code> "
            f"<b>{w['label']}</b> [{w['type']}]\n"
            f"    💰 {bal_str}"
        )

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        await _reject(update)
        return

    await update.message.reply_text("🔍 Запускаю сканер DeFiLlama...")

    def _run_scan() -> list[dict]:
        from src.modules.scanner.defillama import scan_polygon_candidates
        return scan_polygon_candidates(min_tvl=500_000, limit=10, notify=False)

    try:
        results = await asyncio.to_thread(_run_scan)
    except Exception as e:
        log.exception("Сканер упал")
        await update.message.reply_text(f"❌ Ошибка сканера: {str(e)[:200]}")
        return

    if not results:
        await update.message.reply_text("🤷 Кандидатов не найдено.")
        return

    lines = ["<b>🔍 Кандидаты (Polygon, без токена):</b>", ""]
    for i, c in enumerate(results[:10], 1):
        tvl_m = c["tvl_usd"] / 1_000_000
        lines.append(
            f"{i}. <b>{c['name']}</b> ({c['category']})\n"
            f"    TVL: ${tvl_m:.1f}M | {c['defillama_url']}"
        )

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_quests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает активные квесты Galxe."""
    if not _is_owner(update):
        await _reject(update)
        return

    await update.message.reply_text("🔍 Запрашиваю активные квесты Galxe...")

    def _run() -> list[dict]:
        from src.modules.scanner.galxe import fetch_active_quests
        return fetch_active_quests(limit=15, notify=False)

    try:
        quests = await asyncio.to_thread(_run)
    except Exception as e:
        log.exception("Galxe scanner упал")
        await update.message.reply_text(f"❌ Ошибка: {str(e)[:200]}")
        return

    if not quests:
        await update.message.reply_text("🤷 Активных квестов не найдено.")
        return

    lines = ["<b>🎯 Активные квесты Galxe:</b>", ""]
    for i, q in enumerate(quests[:10], 1):
        lines.append(f"{i}. <b>{q['name']}</b>")
        lines.append(f"    <a href='{q['url']}'>Открыть квест</a>")
    lines.append(f"\nВсего активных: {len(quests)}")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# --- Регистрация хендлеров ---

def _register_handlers(app: Application) -> None:
    # Основные команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("wallets", cmd_wallets))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("quests", cmd_quests))

    # Команды управления кошельками — подключаем из отдельного модуля
    from src.core.telegram_wallet_cmds import register_wallet_handlers
    register_wallet_handlers(app)


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Логирует необработанные исключения из хендлеров."""
    log.exception(f"Ошибка в обработчике: {context.error}")


def run_bot() -> None:
    """Запускает бота в режиме long polling (блокирующий вызов)."""
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")
    if not settings.TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID не задан в .env")

    log.info("Запуск Telegram-бота (long polling)...")

    app = (
        Application.builder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .build()
    )
    _register_handlers(app)
    app.add_error_handler(_on_error)

    log.success("Бот запущен. Отправь /help в Telegram.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


__all__ = ["run_bot"]


if __name__ == "__main__":
    try:
        run_bot()
    except KeyboardInterrupt:
        log.info("Бот остановлен (Ctrl+C).")
