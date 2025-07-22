import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.utils import executor
from status import (
    get_uptime,
    get_cpu_usage,
    get_ram_usage,
    get_disk_usage,
    get_system_load,
    get_bot_version,
    count_videos,
    get_edit_progress,
    get_next_schedule,
)

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

@dp.message_handler(commands=["status"])
async def send_status(message: Message):
    if str(message.chat.id) != CHAT_ID:
        return  # 🔒 Ignore unauthorized users silently

    downloaded, editing, ready = count_videos()

    status_msg = (
        f"🛰️ *Bot Status*\n"
        f"⏱️ *Uptime:* `{get_uptime()}`\n"
        f"🧠 *CPU:* `{get_cpu_usage()}`\n"
        f"📦 *RAM:* `{get_ram_usage()}`\n"
        f"💽 *Disk:* `{get_disk_usage()}`\n"
        f"📊 *System Load:* `{get_system_load()}`\n"
        f"🎬 *Videos:* `Downloaded: {downloaded}` | `Editing: {editing}` | `Ready: {ready}`\n"
        f"⚙️ *Edit Progress:* `{get_edit_progress()}%`\n"
        f"🕒 *Next Video:* `{get_next_schedule()}` (UK time)\n"
        f"📌 *Version:* `{get_bot_version()}`"
    )

    await message.answer(status_msg, parse_mode="Markdown")

def start_polling():
    executor.start_polling(dp, skip_updates=True)
