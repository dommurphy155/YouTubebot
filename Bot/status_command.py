import os
from telegram import Update
from telegram.ext import ContextTypes
from status import (
    get_uptime,
    get_cpu_usage,
    get_ram_usage,
    get_disk_usage,
    get_system_load,
    get_bot_version,
    count_videos,
    get_edit_progress,
    get_next_schedule
)

async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != os.environ.get("TELEGRAM_CHAT_ID"):
        return  # Ignore non-owner calls

    downloaded, editing, ready = count_videos()

    status_msg = (
        "<b>📊 Bot Status</b>\n\n"
        f"🕒 <b>Uptime:</b> {get_uptime()}\n"
        f"💻 <b>CPU:</b> {get_cpu_usage()}\n"
        f"🧠 <b>RAM:</b> {get_ram_usage()}\n"
        f"💾 <b>Disk:</b> {get_disk_usage()}\n"
        f"📉 <b>Load:</b> {get_system_load()}\n"
        f"📦 <b>Version:</b> {get_bot_version()}\n\n"
        f"🎥 <b>Downloaded:</b> {downloaded}\n"
        f"🎬 <b>Editing:</b> {editing}\n"
        f"✅ <b>Ready:</b> {ready}\n"
        f"📈 <b>Progress:</b> {get_edit_progress()}\n"
        f"⏰ <b>Next Send:</b> {get_next_schedule()}\n"
    )

    await update.message.reply_text(
        status_msg,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
