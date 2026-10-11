"""
src/core/swap_cmds.py
/quote и /swap команды для Telegram. Мультичейн.

Использование:
    /quote FROM TO AMOUNT [CHAIN]
    /swap FROM TO AMOUNT [CHAIN]

Примеры:
    /quote POL USDT 1.0              — Polygon (дефолт)
    /quote USDC USDT 10              — Polygon
    /swap POL USDC 0.5 base          — Base
    /swap USDC ETH 5 linea           — Linea

Поддерживаемые сети: polygon | base | linea
"""

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from src.core.config import settings
from src.core.logger import get_logger
from src.core.rpc import CHAINS, DEFAULT_CHAIN
from src.modules.executor.erc20 import TOKENS

log = get_logger(__name__)


# ============================================================
# Хелперы
# ============================================================

def _is_owner(update: Update) -> bool:
    if not update.effective_chat:
        return False
    return str(update.effective_chat.id) == str(settings.TELEGRAM_CHAT_ID)


async def _reject(update: Update) -> None:
    if update.message:
        await update.message.reply_text("Приватный бот")


def _resolve_chain(s: str) -> str:
    """Валидация имени сети."""
    chain = s.lower().strip()
    if chain not in CHAINS:
        raise ValueError(
            f"Неизвестная сеть: {s}. "
            f"Доступные: {', '.join(CHAINS.keys())}"
        )
    return chain


def _resolve_token(sym: str, chain: str = DEFAULT_CHAIN) -> str:
    """
    Символ → адрес контракта в указанной сети.
    Native (POL/MATIC/ETH) → 'native' (специальная метка для dex.py).
    """
    s = sym.upper().strip()

    # Native токены для разных сетей
    native_aliases = {
        "polygon": ("MATIC", "POL", "NATIVE", "WMATIC"),
        "base": ("ETH", "NATIVE", "WETH"),
        "linea": ("ETH", "NATIVE", "WETH"),
    }
    if s in native_aliases.get(chain, ()):
        return "native"

    # Известные токены сети
    chain_tokens = TOKENS.get(chain, {})
    if s in chain_tokens:
        return chain_tokens[s]

    # Прямой адрес
    if s.startswith("0X") and len(s) == 42:
        return sym  # вернём исходный с 0x, не upper
    if s.startswith("0x") and len(s) == 42:
        return sym

    raise ValueError(
        f"Неизвестный токен '{sym}' в сети {chain}. "
        f"Доступные: {', '.join(chain_tokens.keys())} или адрес 0x..."
    )


# ============================================================
# /quote
# ============================================================

async def cmd_quote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        await _reject(update)
        return

    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text(
            "Использование: <code>/quote FROM TO AMOUNT [CHAIN]</code>\n\n"
            "Примеры:\n"
            "<code>/quote POL USDT 1.0</code>\n"
            "<code>/quote USDC USDT 10 base</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    t_in_sym, t_out_sym, amt_s = args[0], args[1], args[2]
    chain_arg = args[3] if len(args) > 3 else DEFAULT_CHAIN

    try:
        chain = _resolve_chain(chain_arg)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    try:
        amt = float(amt_s)
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом")
        return

    await update.message.reply_text(f"Запрашиваю курс [{chain}]...")

    try:
        t_in = _resolve_token(t_in_sym, chain=chain)
        t_out = _resolve_token(t_out_sym, chain=chain)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    def _run():
        from src.services.dex import get_quote
        from src.modules.wallets.manager import get_all_wallets

        wallets = get_all_wallets()
        if not wallets:
            return None
        # Берём первый farming-кошелёк
        w = wallets[0]
        return get_quote(t_in, t_out, amt, chain=chain, from_address=w.address)

    try:
        q = await asyncio.to_thread(_run)
    except Exception as e:
        log.exception("quote err")
        await update.message.reply_text(f"Ошибка: {str(e)[:150]}")
        return

    if not q:
        await update.message.reply_text(f"Курс [{chain}] не получен")
        return

    txt = (
        f"💱 <b>Quote [{chain}]</b>\n\n"
        f"{q['from_amount']} {q['from_symbol']} → "
        f"{q['to_amount']:.6f} {q['to_symbol']}"
    )
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML)


# ============================================================
# /swap
# ============================================================

async def cmd_swap(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        await _reject(update)
        return

    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text(
            "Использование: <code>/swap FROM TO AMOUNT [CHAIN]</code>\n\n"
            "Примеры:\n"
            "<code>/swap POL USDC 0.5</code>\n"
            "<code>/swap USDC ETH 5 base</code>\n"
            "<code>/swap USDC POL 3 linea</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    t_in_sym, t_out_sym, amt_s = args[0], args[1], args[2]
    chain_arg = args[3] if len(args) > 3 else DEFAULT_CHAIN

    try:
        chain = _resolve_chain(chain_arg)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    try:
        amt = float(amt_s)
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом")
        return

    await update.message.reply_text(
        f"🔄 Запускаю свап [{chain}]: {amt} {t_in_sym} → {t_out_sym}..."
    )

    try:
        t_in = _resolve_token(t_in_sym, chain=chain)
        t_out = _resolve_token(t_out_sym, chain=chain)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    def _run():
        from src.services.dex import swap
        from src.modules.wallets.manager import get_all_wallets

        wallets = get_all_wallets()
        if not wallets:
            return None
        w = wallets[0]
        return swap(
            from_label=w.label,
            token_in=t_in,
            token_out=t_out,
            amount=amt,
            chain=chain,
            slippage=5.0,
            wait=True,
            notify=True,
        )

    try:
        tx = await asyncio.to_thread(_run)
    except Exception as e:
        log.exception("swap err")
        await update.message.reply_text(f"Ошибка: {str(e)[:150]}")
        return

    if tx:
        await update.message.reply_text(f"Tx: {tx[:20]}...")
    else:
        await update.message.reply_text(f"Свап [{chain}] не выполнен")


# ============================================================
# Регистрация
# ============================================================

def register_swap_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("quote", cmd_quote))
    app.add_handler(CommandHandler("swap", cmd_swap))
    log.info("swap_cmds: зарегистрированы /quote, /swap")


__all__ = ["register_swap_handlers"]
