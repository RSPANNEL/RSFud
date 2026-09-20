import logging
import os
from html import escape
from pathlib import Path

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
ALLOWED_CHAT_ID = int(require_env("CHAT_ID"))

# APK file paths - UPDATE THESE FOR YOUR ENVIRONMENT
APK_PATHS = [
    "/home/appuser/app/Droper/app/build/outputs/apk/debug/app-debug.apk",
    "/home/appuser/app/PyBuilder/dist/Final Output Apk/dropper-debug-20251210-200400-signed.apk",
]


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


async def share_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send APK files to the allowed chat"""
    chat_id = update.effective_chat.id if update.effective_chat else None
    
    if chat_id != ALLOWED_CHAT_ID:
        if update.message:
            await update.message.reply_text("❌ Unauthorized access denied.")
        return
    
    if not update.message:
        return
    
    status_msg = await update.message.reply_text("📦 Processing files...")
    
    try:
        files_sent = 0
        files_failed = 0
        
        for apk_path in APK_PATHS:
            try:
                file_path = Path(apk_path)
                
                if not file_path.exists():
                    logger.warning(f"APK file not found: {apk_path}")
                    files_failed += 1
                    continue
                
                file_size_mb = file_path.stat().st_size / (1024 * 1024)
                
                if file_size_mb > 100:
                    logger.warning(f"APK file too large ({file_size_mb:.2f}MB): {apk_path}")
                    files_failed += 1
                    continue
                
                logger.info(f"Sending APK: {file_path.name} ({file_size_mb:.2f}MB)")
                
                with open(file_path, 'rb') as apk_file:
                    await context.bot.send_document(
                        chat_id=ALLOWED_CHAT_ID,
                        document=apk_file,
                        caption=f"📱 {file_path.name}\nSize: {file_size_mb:.2f}MB",
                        parse_mode="HTML"
                    )
                
                files_sent += 1
                logger.info(f"Successfully sent: {file_path.name}")
                
            except Exception as e:
                logger.error(f"Error sending APK {apk_path}: {e}")
                files_failed += 1
                continue
        
        if files_sent > 0:
            await status_msg.edit_text(
                f"✅ Share complete!\n"
                f"📤 Files sent: {files_sent}\n"
                f"❌ Files failed: {files_failed}"
            )
        else:
            await status_msg.edit_text(
                f"❌ No files could be sent.\n"
                f"Failed: {files_failed}\n\n"
                f"Make sure APK files exist at configured paths."
            )
    
    except Exception as e:
        logger.error(f"Error in share command: {e}")
        await status_msg.edit_text(f"❌ Error occurred: {str(e)}")


async def on_startup(app: Application) -> None:
    text = (
        "<b>🤖 Railway bot is live</b>\n"
        f"<code>Allowed chat ID: {escape(str(ALLOWED_CHAT_ID))}</code>\n\n"
        "Available commands:\n"
        "• /start - Test connection\n"
        "• /id - Get chat ID\n"
        "• /health - Check health\n"
        "• /share - Share APK files"
    )
    await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=text, parse_mode="HTML")


def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(CommandHandler("share", share_command))
    app.post_init = on_startup
    return app


def main() -> None:
    app = build_app()
    logger.info("Starting bot polling...")
    app.run_polling(allowed_updates=None)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.exception("Bot failed to start: %s", exc)
        raise
