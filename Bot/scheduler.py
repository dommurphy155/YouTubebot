import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot import scraper, editor, uploader
import os

logger = logging.getLogger("TelegramVideoBot")
scheduler = AsyncIOScheduler()

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
if not PEXELS_API_KEY:
    logger.error("PEXELS_API_KEY environment variable not set")
    raise RuntimeError("PEXELS_API_KEY environment variable not set")

async def scheduled_job():
    try:
        # Pass the API key to scraper.scrape_video if scraper supports it
        video_path = await scraper.scrape_video(api_key=PEXELS_API_KEY)
        if not video_path:
            return

        edited_path = await editor.edit_video(video_path)
        await uploader.upload_video(edited_path)
        uploader.cleanup_files([video_path, edited_path])
    except Exception as e:
        logger.error(f"Scheduled job failed: {e}")

def start_scheduler():
    scheduler.add_job(scheduled_job, "interval", minutes=30)
    scheduler.start()
    logger.info("Scheduler started")
