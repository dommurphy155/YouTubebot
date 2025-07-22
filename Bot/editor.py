import asyncio
import logging
import os

logger = logging.getLogger("TelegramVideoBot")

OUTPUT_DIR = "/home/ubuntu/YouTubebot/processed"
os.makedirs(OUTPUT_DIR, exist_ok=True)

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

    # We'll remove the invalid 'trim=start=if(gt(scene,0.05),0,0)' expression.
    # Instead, we keep fixed max duration 45s via '-t 45' and remove silence using silenceremove filter.
    # Volume normalization will be applied with loudnorm filter instead of volume=normalize (more compatible).
    # Sharpening with unsharp filter is kept.
    # Contrast and brightness enhanced with eq filter.

    filter_complex = (
        "[0:v]scale=1080:-1,"
        "crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2,"
        "eq=contrast=1.1:brightness=0.05,"
        "unsharp=luma_msize_x=5:luma_msize_y=5:luma_amount=1.0,"
        "setpts=PTS-STARTPTS[v];"
        "[0:a]silenceremove=start_periods=1:start_silence=0.5:start_threshold=-30dB:"
        "detection=peak,"
        "loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
    )

    ffmpeg_cmd = [
        "ffmpeg",
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[aout]",
        "-t", "45",
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
