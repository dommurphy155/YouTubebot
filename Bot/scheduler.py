import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot import scraper, editor, uploader

logger = logging.getLogger("TelegramVideoBot")
scheduler = AsyncIOScheduler()

async def scheduled_job():
    try:
        video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # Replace with rotating URL source
        video_path = await scraper.scrape_video(video_url)
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
  
