import asyncio
import logging
import os
import shlex
import subprocess

logger = logging.getLogger("TelegramVideoBot")

OUTPUT_DIR = "/home/ubuntu/YouTubebot/processed"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Semaphore to limit concurrent ffmpeg jobs
_ffmpeg_semaphore = asyncio.Semaphore(1)

async def run_ffmpeg_async(cmd: list[str]) -> None:
    async with _ffmpeg_semaphore:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err_msg = stderr.decode().strip()
            raise RuntimeError(f"ffmpeg failed with code {proc.returncode}: {err_msg}")

async def edit_video(input_path: str) -> str:
    output_path = os.path.join(OUTPUT_DIR, os.path.basename(input_path))
    logger.info(f"Editing video: {input_path}")

    # Build ffmpeg command manually for async subprocess
    # Scale input to max 1080 width, keep aspect, crop center 1080x1920 vertical video
    # Use 'fast' preset + CRF 25 for lighter load with decent quality
    ffmpeg_cmd = [
        "ffmpeg",
        "-i", input_path,
        "-filter_complex",
        "[0]scale=1080:-1[s0];[s0]crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2[s1]",
        "-map", "[s1]",
        "-vcodec", "libx264",
        "-preset", "fast",
        "-crf", "25",
        "-acodec", "aac",
        "-movflags", "faststart",
        "-y",
        output_path
    ]

    try:
        await run_ffmpeg_async(ffmpeg_cmd)
        logger.info(f"Edited video saved to: {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"FFmpeg failed: {str(e)}")
        raise
