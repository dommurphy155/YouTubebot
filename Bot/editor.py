import asyncio
import logging
import os
from typing import List

logger = logging.getLogger("TelegramVideoBot")

OUTPUT_DIR = "/home/ubuntu/YouTubebot/processed"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Limit ffmpeg concurrency to 1 to avoid resource contention on VPS
_ffmpeg_semaphore = asyncio.Semaphore(1)


async def run_ffmpeg_async(cmd: List[str]) -> None:
    async with _ffmpeg_semaphore:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err_msg = stderr.decode().strip()
            logger.error(f"FFmpeg error: {err_msg}")
            raise RuntimeError(f"ffmpeg failed with code {proc.returncode}: {err_msg}")


async def edit_video(input_path: str, max_duration: int = 45) -> str:
    """
    Edit video to vertical 1080x1920 format, apply sharpening, brightness/contrast,
    fade in/out, interpolate to 30fps, normalize audio loudness.

    Args:
        input_path: Path to input video file.
        max_duration: Max length of output video in seconds.

    Returns:
        Path to processed video file.
    """

    output_path = os.path.join(OUTPUT_DIR, os.path.basename(input_path))
    logger.info(f"Editing video: {input_path}")

    # Construct filter complex string with parameterized fade out start time
    # Fade out starts max_duration-1 second for 1 second duration
    fade_out_start = max_duration - 1

    filter_complex = (
        "[0:v]scale=1080:-1,"
        "crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2,"
        "eq=contrast=1.1:brightness=0.05,"
        "unsharp=luma_msize_x=5:luma_msize_y=5:luma_amount=1.0,"
        f"fade=t=in:st=0:d=1,fade=t=out:st={fade_out_start}:d=1,"
        "minterpolate='fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1',"
        "setpts=PTS-STARTPTS[v];"
        "[0:a]"
        "silenceremove=start_periods=1:start_silence=0.5:start_threshold=-30dB:"
        "stop_periods=1:stop_silence=0.5:stop_threshold=-30dB:detection=peak,"
        "afade=t=in:ss=0:d=1,afade=t=out:st={fade_out_start}:d=1,"
        "loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
    ).format(fade_out_start=fade_out_start)

    ffmpeg_cmd = [
        "ffmpeg",
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[aout]",
        "-t", str(max_duration),
        "-vcodec", "libx264",
        "-preset", "fast",
        "-crf", "25",
        "-acodec", "aac",
        "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-movflags", "faststart",
        "-threads", "2",
        "-y",
        output_path
    ]

    await run_ffmpeg_async(ffmpeg_cmd)

    logger.info(f"Edited video saved to: {output_path}")
    return output_path
