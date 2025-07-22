import asyncio
import shlex
import subprocess
from pathlib import Path
from bot.config import DOWNLOAD_DIR, YTDLP_RETRIES, YTDLP_FRAGMENT_RETRIES, YTDLP_MAX_DURATION
from bot.utils import logger

async def download_video(keyword: str) -> Path | None:
    """
    Downloads a public YouTube video matching the keyword,
    returning path to downloaded file or None on failure.
    """
    # yt-dlp command to search and download one video matching the keyword
    # --max-duration to avoid long videos, --format best mp4 compatible
    cmd = (
        f"yt-dlp 'ytsearch1:{keyword}' "
        f"--max-downloads 1 "
        f"--max-duration {YTDLP_MAX_DURATION} "
        f"--format bestvideo[ext=mp4]+bestaudio[ext=m4a]/best "
        f"--merge-output-format mp4 "
        f"--retries {YTDLP_RETRIES} "
        f"--fragment-retries {YTDLP_FRAGMENT_RETRIES} "
        f"--no-warnings "
        f"--no-cache-dir "
        f"--output '{DOWNLOAD_DIR}/%(title)s.%(ext)s'"
    )
    logger.info(f"Starting download for keyword: {keyword}")
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        logger.error(f"yt-dlp failed for keyword '{keyword}': {stderr.decode().strip()}")
        return None

    # Locate downloaded file (most recent file in DOWNLOAD_DIR)
    files = sorted(Path(DOWNLOAD_DIR).glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        logger.error(f"No video file found after download for keyword '{keyword}'")
        return None

    downloaded_file = files[0]
    logger.info(f"Downloaded file: {downloaded_file}")
    return downloaded_file
