import json
import logging
import os
from html import escape
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
CACHE_FILE = BASE_DIR / "apk_file_ids.json"
MAX_APK_SIZE_MB = 50  # Telegram bot upload limit


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


BOT_TOKEN = require_env("BOT_TOKEN")
ALLOWED_CHAT_ID = int(require_env("CHAT_ID"))

# Optional: Railway -> Variables -> APK_PATHS
# Comma-separated paths ya folder, e.g.:
# APK_PATHS=/app/apk/myapp.apk,/app/apk2
ENV_APK_PATHS = [p.strip() for p in os.getenv("APK_PATHS", "").split(",") if p.strip()]


# ---------------- APK helpers ----------------

def collect_apk_files() -> list[Path]:
    """Env paths pehle, phir repo ke andar auto-search."""
    found: list[Path] = []
    seen = set()

    def _add(path: Path) -> None:
        try:
            resolved = path.resolve()
        except OSError:
            return
        if resolved.is_file() and path.suffix.lower() == ".apk" and resolved not in seen:
            seen.add(resolved)
            found.append(path)

    for raw in ENV_APK_PATHS:
        p = Path(raw)
        if p.is_dir():
            for apk in sorted(p.rglob("*.apk")):
                _add(apk)
        else:
            _add(p)

    if not found:
        # Repo me kahin bhi .apk dhoondo
        for apk in sorted(BASE_DIR.rglob("*.apk")):
            _add(apk)
    return found


def load_file_id_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_file_id_cache(cache: dict) -> None:
    try:
        CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"Cache save nahi hua: {e}")


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📦 Share APK", callback_data="share_apk")],
            [InlineKeyboardButton("📋 Commands", callback_data="menu_help")],
        ]
    )


# ---------------- Commands ----------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id != ALLOWED_CHAT_ID:
        return
    await update.message.reply_text(
        "✅ <b>Bot connected successfully!</b>\n\nNeeche button dabao ya /share use karo:",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    await update.message.reply_text(f"Your chat id: {update.effective_chat.id}")


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id != ALLOWED_CHAT_ID:
        return
    await update.message.reply_text("OK")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id != ALLOWED_CHAT_ID:
        return
    await update.message.reply_text(
        "Available commands:\n"
        "• /start - Menu + Share APK button\n"
        "• /id - Get chat ID\n"
        "• /health - Check health\n"
        "• /share - Share APK files",
        reply_markup=main_menu_keyboard(),
    )


# ---------------- Share logic ----------------

async def perform_share(update_or_query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Common share logic (command + button dono ke liye)."""
    chat_id = update_or_query.effective_chat.id if update_or_query.effective_chat else None

    if chat_id != ALLOWED_CHAT_ID:
        if update_or_query.message:
            await update_or_query.message.reply_text("❌ Unauthorized access denied.")
        return

    reply_target = update_or_query.message
    if reply_target is None:
        return

    status_msg = await reply_target.reply_text("📦 Processing files...")

    try:
        apk_files = collect_apk_files()
        if not apk_files:
            await status_msg.edit_text(
                "❌ Koi APK nahi mili.\n\n"
                "APK ko repo me <code>apk/</code> folder me daalo, "
                "ya Railway Variables me <code>APK_PATHS</code> set karo.",
                parse_mode="HTML",
            )
            return

        cache = load_file_id_cache()
        files_sent = 0
        files_failed = 0

        for file_path in apk_files:
            try:
                size_mb = file_path.stat().st_size / (1024 * 1024)

                if size_mb > MAX_APK_SIZE_MB:
                    logger.warning(f"APK too large ({size_mb:.2f}MB): {file_path}")
                    files_failed += 1
                    continue

                cache_key = f"{file_path.name}:{file_path.stat().st_size}"
                caption = f"📱 {file_path.name}\nSize: {size_mb:.2f}MB"

                cached_id = cache.get(cache_key)
                if cached_id:
                    try:
                        await context.bot.send_document(
                            chat_id=ALLOWED_CHAT_ID,
                            document=cached_id,
                            caption=caption,
                            parse_mode="HTML",
                        )
                        files_sent += 1
                        logger.info(f"Sent from cache: {file_path.name}")
                        continue
                    except Exception as e:
                        logger.warning(f"Cached file_id failed, re-uploading: {e}")

                with open(file_path, "rb") as apk_file:
                    sent = await context.bot.send_document(
                        chat_id=ALLOWED_CHAT_ID,
                        document=apk_file,
                        caption=caption,
                        parse_mode="HTML",
                    )

                new_file_id = None
                try:
                    new_file_id = sent.document.file_id
                except Exception:
                    pass

                if new_file_id:
                    cache[cache_key] = new_file_id
                    save_file_id_cache(cache)

                files_sent += 1
                logger.info(f"Uploaded: {file_path.name} ({size_mb:.2f}MB)")

            except Exception as e:
                logger.error(f"Error sending {file_path}: {e}")
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
                f"❌ No files could be sent. Failed: {files_failed}"
            )

    except Exception as e:
        logger.error(f"Error in share: {e}")
        await status_msg.edit_text(f"❌ Error occurred: {str(e)}")


async def share_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await perform_share(update, context)


# ---------------- Button handler ----------------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return

    chat_id = update.effective_chat.id if update.effective_chat else None

    if query.data == "menu_help":
        await query.answer()
        if chat_id == ALLOWED_CHAT_ID:
            await query.message.reply_text(
                "Available commands:\n"
                "• /start - Menu + Share APK button\n"
                "• /id - Get chat ID\n"
                "• /health - Check health\n"
                "• /share - Share APK files",
                reply_markup=main_menu_keyboard(),
            )
        return

    if query.data == "share_apk":
        await query.answer("📦 Sending APK...")
        # callback_query ko message jaisa use kar sakte hain
        await perform_share(update, context)
        return


async def on_startup(app: Application) -> None:
    apk_count = len(collect_apk_files())
    text = (
        "<b>🤖 Railway bot is live</b>\n"
        f"<code>Allowed chat ID: {escape(str(ALLOWED_CHAT_ID))}</code>\n"
        f"📦 APK files found: {apk_count}\n\n"
        "/start pe jao — <b>Share APK</b> button milega 🚀"
    )
    await app.bot.send_message(chat_id=ALLOWED_CHAT_ID, text=text, parse_mode="HTML")


def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("share", share_command))
    app.add_handler(CallbackQueryHandler(button_handler))
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
