import asyncio
import logging
import signal
import sys

from bot import scraper, editor, uploader

logger = logging.getLogger("TelegramVideoBot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

running = True

def handle_shutdown(signum, frame):
    global running
    running = False
    logger.info("Shutdown signal received.")

async def main_loop():
    while running:
        try:
            video_path = await scraper.scrape_video()
            if not video_path:
                await asyncio.sleep(60)
                continue

            edited_path = await editor.edit_video(video_path)
            await uploader.upload_video(edited_path)
            scraper.cleanup_files([video_path, edited_path])
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
        await asyncio.sleep(10)

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    try:
        asyncio.run(main_loop())
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        sys.exit(1)
