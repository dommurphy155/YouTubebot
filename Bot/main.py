import asyncio
import logging
import signal
import sys

logger = logging.getLogger("TelegramVideoBot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

running = True

def handle_shutdown(signum, frame):
    global running
    logger.info("Shutdown signal received.")
    running = False

async def main_loop():
    logger.info("Starting Telegram Video Bot")
    while running:
        logger.info("Bot is running...")
        await asyncio.sleep(60)
    logger.info("Exiting bot cleanly.")

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    try:
        asyncio.run(main_loop())
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        sys.exit(1)
