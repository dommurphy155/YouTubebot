import os
import json
import subprocess
import asyncio
import logging
from typing import List

logger = logging.getLogger("TelegramVideoBot")

OUTPUT_DIR = os.path.join(os.getcwd(), "processed")
os.makedirs(OUTPUT_DIR, exist_ok=True)

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
            raise RuntimeError(f"ffmpeg failed with code {proc.returncode}: {err_msg}")

def detect_best_segment(video_path: str, max_duration: int = 45) -> float:
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        total_duration = float(result.stdout.strip())
        if total_duration <= max_duration:
            return 0.0
        return round((total_duration - max_duration) / 2, 2)
    except Exception as e:
        logger.warning(f"Segment detection failed: {e}")
        return 0.0

def has_audio_stream(video_path: str) -> bool:
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=index",
            "-of", "json",
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)
        return bool(info.get("streams"))
    except Exception:
        return False

async def edit_video(input_path: str) -> str:
    output_path = os.path.join(OUTPUT_DIR, os.path.basename(input_path))
    logger.info(f"Editing video: {input_path}")

    start_time = detect_best_segment(input_path)
    logger.info(f"Using start time: {start_time:.2f}s")

    if has_audio_stream(input_path):
        filter_complex = (
            "[0:v]scale=1080:-1,"
            "crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2,"
            "eq=contrast=1.1:brightness=0.05,"
            "unsharp=5:5:1.0,"
            "fade=t=in:st=0:d=1,fade=t=out:st=44:d=1,"
            "minterpolate='fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1',"
            "setpts=PTS-STARTPTS[v];"
            "[0:a]silenceremove=start_periods=1:start_silence=0.5:start_threshold=-30dB:"
            "stop_periods=1:stop_silence=0.5:stop_threshold=-30dB,"
            "afade=t=in:ss=0:d=1,afade=t=out:st=44:d=1,"
            "loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
        )
        ffmpeg_cmd = [
            "ffmpeg",
            "-ss", str(start_time),
            "-i", input_path,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "[aout]",
            "-t", "45",
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
    else:
        # No audio present, drop audio filters & maps
        filter_complex = (
            "[0:v]scale=1080:-1,"
            "crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2,"
            "eq=contrast=1.1:brightness=0.05,"
            "unsharp=5:5:1.0,"
            "fade=t=in:st=0:d=1,fade=t=out:st=44:d=1,"
            "minterpolate='fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1',"
            "setpts=PTS-STARTPTS[v]"
        )
        ffmpeg_cmd = [
            "ffmpeg",
            "-ss", str(start_time),
            "-i", input_path,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-t", "45",
            "-vcodec", "libx264",
            "-preset", "fast",
            "-crf", "25",
            "-pix_fmt", "yuv420p",
            "-movflags", "faststart",
            "-threads", "2",
            "-y",
            output_path
        ]

    await run_ffmpeg_async(ffmpeg_cmd)
    logger.info(f"Edited video saved to: {output_path}")
    return output_path

def is_video_suitable(path: str) -> bool:
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration",
            "-of", "json",
            path
        ], capture_output=True, text=True, check=True)
        stream = json.loads(result.stdout)["streams"][0]
        duration = float(stream.get("duration", 0))
        width = int(stream.get("width", 0))
        height = int(stream.get("height", 0))
        return 15 <= duration <= 90 and width >= 640 and height >= 360
    except Exception as e:
        logger.warning(f"Suitability check failed: {e}")
        return False
