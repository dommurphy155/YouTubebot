import asyncio
import logging
import os
import tempfile
import ffmpeg

logger = logging.getLogger("TelegramVideoBot")

OUTPUT_DIR = "/home/ubuntu/YouTubebot/processed"
os.makedirs(OUTPUT_DIR, exist_ok=True)

async def edit_video(input_path: str) -> str:
    output_path = os.path.join(OUTPUT_DIR, os.path.basename(input_path))

    try:
        logger.info(f"Editing video: {input_path}")

        # Resize, crop center square, convert to vertical for iPhone (9:16), compress
        (
            ffmpeg
            .input(input_path)
            .filter("scale", 1080, -1)
            .filter("crop", 1080, 1920)
            .output(output_path, vcodec='libx264', crf=23, preset='medium', acodec='aac', movflags='faststart')
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )

        logger.info(f"Edited video saved to: {output_path}")
        return output_path

    except ffmpeg.Error as e:
        logger.error(f"FFmpeg failed: {e.stderr.decode() if e.stderr else e}")
        raise
