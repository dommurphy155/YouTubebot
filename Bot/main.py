import asyncio
import logging

logger = logging.getLogger()
logging.basicConfig(level=logging.INFO)

async def main():
    logger.info("Starting Telegram Video Bot")
    while True:
        logger.info("Bot running...")
        await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot interrupted and stopped")
