"""
src/core/swap_cmds.py
/quote и /swap команды для Telegram. Мультичейн.

Routing:
    - Base + ETH<->токен  → Aerodrome (главный DEX Base)
    - Всё остальное       → KyberSwap (агрегатор)

Дополнительная команда:
    /aero FROM TO AMOUNT  — принудительно через Aerodrome (Base)

Использование:
    /quote FROM TO AMOUNT [CHAIN]
    /swap FROM TO AMOUNT [CHAIN]
    /aero FROM TO AMOUNT

Примеры:
    /quote POL USDT 1.0
    /quote USDC ETH 1 base
    /swap ETH USDC 0.0002 base     ← пойдёт через Aerodrome
    /swap USDC ETH 0.5 base         ← пойдёт через Aerodrome
    /swap USDT POL 0.5 linea        ← пойдёт через Kyber
    /aero ETH USDC 0.0002           ← принудительно Aerodrome
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
    chain = s.lower().strip()
    if chain not in CHAINS:
        raise ValueError(
            f"Неизвестная сеть: {s}. Доступные: {', '.join(CHAINS.keys())}"
        )
    return chain


def _resolve_token(sym: str, chain: str = DEFAULT_CHAIN) -> str:
    """
    Символ → адрес контракта или 'native' (спец-метка).
    """
    s = sym.upper().strip()

    native_aliases = {
        "polygon": ("MATIC", "POL", "NATIVE", "WMATIC"),
        "base": ("ETH", "NATIVE", "WETH"),
        "linea": ("ETH", "NATIVE", "WETH"),
    }
    if s in native_aliases.get(chain, ()):
        return "native"

    chain_tokens = TOKENS.get(chain, {})
    if s in chain_tokens:
        return chain_tokens[s]

    if s.startswith("0X") and len(s) == 42:
        return sym
    if s.startswith("0x") and len(s) == 42:
        return sym

    raise ValueError(
        f"Неизвестный токен '{sym}' в сети {chain}. "
        f"Доступные: {', '.join(chain_tokens.keys())} или адрес 0x..."
    )


def _is_native_sym(sym: str, chain: str) -> bool:
    """Проверяет является ли символ native для этой сети."""
    s = sym.upper().strip()
    native = {"polygon": ("MATIC", "POL", "NATIVE"), "base": ("ETH", "NATIVE", "WETH"), "linea": ("ETH", "NATIVE", "WETH")}
    return s in native.get(chain, ())


def _use_aerodrome(chain: str, t_in_sym: str, t_out_sym: str) -> bool:
    """
    Использовать ли Aerodrome для этого свапа.
    Да — только если chain=base И (один из токенов native, другой стейбл).
    """
    if chain != "base":
        return False
    in_native = _is_native_sym(t_in_sym, chain)
    out_native = _is_native_sym(t_out_sym, chain)
    # Aerodrome MVP поддерживает только native <-> токен
    return in_native != out_native


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
            "<code>/quote ETH USDC 0.0002 base</code>",
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

    use_aero = _use_aerodrome(chain, t_in_sym, t_out_sym)
    source = "Aerodrome" if use_aero else "KyberSwap"
    await update.message.reply_text(f"Запрашиваю курс [{chain}] через {source}...")

    try:
        t_in = _resolve_token(t_in_sym, chain=chain)
        t_out = _resolve_token(t_out_sym, chain=chain)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    def _run():
        from src.modules.wallets.manager import get_all_wallets

        wallets = get_all_wallets()
        if not wallets:
            return None
        w = wallets[0]

        if use_aero:
            from src.services.aerodrome import get_quote_aerodrome
            return get_quote_aerodrome(t_in_sym, t_out_sym, amt)

        from src.services.dex import get_quote
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
        f"💱 <b>Quote [{chain}] через {source}</b>\n\n"
        f"{q['from_amount']} {q['from_symbol']} → "
        f"{q['to_amount']:.6f} {q['to_symbol']}"
    )
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML)


# ============================================================
# /swap (авто-роутинг)
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
            "<code>/swap ETH USDC 0.0002 base</code> ← Aerodrome\n"
            "<code>/swap USDC ETH 0.5 base</code>      ← Aerodrome",
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

    use_aero = _use_aerodrome(chain, t_in_sym, t_out_sym)
    source = "Aerodrome" if use_aero else "KyberSwap"

    await update.message.reply_text(
        f"🔄 Запускаю свап [{chain}] через {source}: "
        f"{amt} {t_in_sym} → {t_out_sym}..."
    )

    try:
        t_in = _resolve_token(t_in_sym, chain=chain)
        t_out = _resolve_token(t_out_sym, chain=chain)
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    def _run():
        from src.modules.wallets.manager import get_all_wallets

        wallets = get_all_wallets()
        if not wallets:
            return None
        w = wallets[0]

        if use_aero:
            from src.services.aerodrome import swap_aerodrome
            return swap_aerodrome(
                from_label=w.label,
                token_in=t_in_sym,
                token_out=t_out_sym,
                amount=amt,
                slippage=5.0,
                wait=True,
                notify=True,
            )

        from src.services.dex import swap
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
        await updateod.message.reply_text(f"Ошибка: {strrome(e)[:150]}")
       (chain return

    if tx:
        await update.message.reply_text(f"Tx: {tx[:20]}...")
    else:
        await update.message.reply_text(f"Свап [{chain}] не выполнен")


# ============================================================
# /aero (принудительно Aerodrome)
# ============================================================

async def cmd_aero(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Принудительный свап через Aerodrome (Base)."""
    if not _is_owner(update):
        await _reject(update)
        return

    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text(
            "Использование: <code>/aero FROM TO AMOUNT</code>\n\n"
            "Всегда chain=base (Aerodrome только там).\n"
            "Пример: <code>/aero ETH USDC 0.0002</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    t_in_sym, t_out_sym, amt_s = args[0], args[1], args[2]

    try:
        amt = float(amt_s)
    except ValueError:
        await update.message.reply_text("Сумма должна быть числом")
        return

    if not (_is_native_sym(t_in_sym, "base") ^ _is_native_sym(t_out_sym, "base")):
        await update.message.reply_text(
            "Aerodrome MVP поддерживает только ETH↔токен (не токен↔токен)"
        )
        return

    await update.message.reply_text(
        f"🔄 Aerodrome [base]: {amt} {t_in_sym} → {t_out_sym}..."
    )

    def _run():
        from src.services.aerodrome import swap_aerodrome
        from src.modules.wallets.manager import get_all_wallets

        wallets = get_all_wallets()
        if not wallets:
            return None
        w = wallets[0]
        return swap_aerodrome(
            from_label=w.label,
            token_in=t_in_sym,
            token_out=t_out_sym,
            amount=amt,
            slippage=5.0,
            wait=True,
            notify=True,
        )

    try:
        tx = await asyncio.to_thread(_run)
    except Exception as e:
        log.exception("aero err")
        await update.message.reply_text(f"Ошибка: {str(e)[:150]}")
        return

    if tx:
        await update.message.reply_text(f"Tx: {tx[:20]}...")
    else:
        await update.message.reply_text("Aerodrome свап не выполнен")


# ============================================================
# Регистрация
# ============================================================

def register_swap_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("quote", cmd_quote))
    app.add_handler(CommandHandler("swap", cmd_swap))
    app.add_handler(CommandHandler("aero", cmd_aero))
    log.info("swap_cmds: зарегистрированы /quote, /swap, /aero")


__all__ = ["register_swap_handlers"]
