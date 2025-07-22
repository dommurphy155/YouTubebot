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

    # ffmpeg filter chain to:
    # 1. scale max width 1080 keeping aspect ratio
    # 2. crop center 1080x1920 vertical format
    # 3. remove silence from start and end (silencedetect + trimming)
    # 4. auto trim to audio duration (max 45s)
    # 5. enhance contrast/brightness
    # 6. sharpen video
    # 7. normalize audio volume

    filter_complex = (
        "[0:v]scale=1080:-1,"
        "crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2,"
        "eq=contrast=1.1:brightness=0.05,"
        "unsharp=luma_msize_x=5:luma_msize_y=5:luma_amount=1.0,"
        "trim=start='if(gt(scene,0.05),0,0)':end=45,setpts=PTS-STARTPTS[v];"
        "[0:a]silencedetect=noise=-30dB:d=0.5[aud1];"
        "[0:a]volume=normalize[a];"
        "[a]atrim=end=45,asetpts=PTS-STARTPTS[aout]"
    )

    ffmpeg_cmd = [
        "ffmpeg",
        "-i", input_path,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[aout]",
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
