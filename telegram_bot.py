import logging
import os
from html import escape

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


BOT_TOKEN = require_env("BOT_TOKEN")
ALLOWED_CHAT_ID = int(require_env("ALLOWED_CHAT_ID"))


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id != ALLOWED_CHAT_ID:
        return
    await update.message.reply_text("Bot connected successfully.")


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    await update.message.reply_text(f"Your chat id: {update.effective_chat.id}")


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id != ALLOWED_CHAT_ID:
        return
    await update.message.reply_text("OK")


async def on_startup(app: Application) -> None:
    text = (
        "<b>Railway bot is live</b>\n"
        f"Allowed chat ID: <code>{escape(str(ALLOWED_CHAT_ID))}</code>"
    )
    await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=text, parse_mode="HTML")


def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("health", health_command))
    app.post_init = on_startup
    return app


def main() -> None:
    app = build_app()
    logger.info("Starting bot polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.exception("Bot failed to start: %s", exc)
        raise
