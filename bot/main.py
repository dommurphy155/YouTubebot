import asyncio
from bot.config import KEYWORDS, DOWNLOAD_DIR, EDITED_DIR
from bot.downloader import download_video
from bot.editor import process_video
from bot.telegram_sender import send_video
from bot.rotation import RotationManager
from bot.utils import logger, cleanup_files
from pathlib import Path
import os

ROTATION_STATE_FILE = os.path.join(DOWNLOAD_DIR, "rotation_state.json")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID"))  # Replace with your chat ID or export it

async def main_loop():
    rotation = RotationManager(KEYWORDS, ROTATION_STATE_FILE)

    while True:
        keyword = rotation.next_keyword()
        logger.info(f"Starting processing cycle for keyword: {keyword}")

        video_path = await download_video(keyword)
        if not video_path:
            logger.error(f"Download failed for keyword {keyword}. Skipping to next.")
            await asyncio.sleep(60)  # Wait 1 minute before next attempt
            continue

        edited_path = process_video(video_path, keyword)
        if not edited_path:
            logger.error(f"Editing failed for video {video_path}. Cleaning up and skipping.")
            cleanup_files(video_path)
            await asyncio.sleep(60)
            continue

        caption = f"#Shorts #YouTubeShorts #Viral #Trending #{keyword.replace(' ', '')}"
        sent = await send_video(TELEGRAM_CHAT_ID, edited_path, caption)
        if sent:
            cleanup_files(video_path, edited_path)
        else:
            logger.error("Failed to send video, keeping files for manual retry.")

        # Wait before next cycle to avoid hitting rate limits (e.g., 5 minutes)
        await asyncio.sleep(300)

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
