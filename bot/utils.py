import logging
import os
import shutil
from bot.config import LOG_FILE

# Setup logger
logger = logging.getLogger("video_bot")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

file_handler = logging.FileHandler(LOG_FILE)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


def cleanup_files(*file_paths):
    for file_path in file_paths:
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
                logger.info(f"Deleted file: {file_path}")
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
                logger.info(f"Deleted directory: {file_path}")
        except Exception as e:
            logger.error(f"Failed to delete {file_path}: {e}")
