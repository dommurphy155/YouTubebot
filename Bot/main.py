import asyncio
import logging

logger = logging.getLogger("TelegramVideoBot")
logging.basicConfig(level=logging.INFO)

async def main():
    logger.info("Starting Telegram Video Bot")
    while True:
        logger.info("Bot is running...")
        await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by keyboard interrupt")
    except Exception as e:
        logger.exception(f"Bot crashed with exception: {e}")
