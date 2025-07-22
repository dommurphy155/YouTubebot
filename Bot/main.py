import asyncio
import logging

logger = logging.getLogger()
logging.basicConfig(level=logging.INFO)

async def main():
    logger.info("Starting Telegram Video Bot")
    try:
        while True:
            logger.info("Bot running...")
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        logger.info("Bot stopped")

if __name__ == "__main__":
    asyncio.run(main())
