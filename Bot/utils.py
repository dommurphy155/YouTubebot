import asyncio
import logging

logger = logging.getLogger("TelegramVideoBot.utils")

async def has_audio_stream(filepath: str) -> bool:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        filepath
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    has_audio = bool(stdout.strip())
    if not has_audio:
        logger.warning(f"No audio stream found in {filepath}")
    return has_audio

async def get_video_duration(filepath: str) -> float | None:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        filepath
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        duration = float(stdout.strip())
        return duration
    except (ValueError, TypeError):
        logger.warning(f"Failed to get duration for {filepath}")
        return None
