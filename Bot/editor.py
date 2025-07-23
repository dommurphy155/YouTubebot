import asyncio
import logging
import os
import subprocess
import json
from typing import List

import cv2
import numpy as np

logger = logging.getLogger("TelegramVideoBot")

OUTPUT_DIR = "/home/ubuntu/YouTubebot/processed"
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

def detect_best_segment(video_path: str, min_duration=20, max_duration=60) -> float:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError("Failed to open video file for analysis")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    scene_scores = []
    prev_frame = None
    changes = []

    for i in range(total_frames):
        ret, frame = cap.read()
        if not ret:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if prev_frame is not None:
            diff = cv2.absdiff(gray, prev_frame)
            changes.append(np.sum(diff))
        prev_frame = gray

    cap.release()

    if len(changes) < fps * min_duration:
        return 0

    scores = np.convolve(changes, np.ones(int(fps * min_duration)), mode='valid')
    best_start_frame = int(np.argmax(scores))
    best_start_time = best_start_frame / fps

    if best_start_time + max_duration > duration:
        return max(0, duration - max_duration)
    return best_start_time

async def edit_video(input_path: str) -> str:
    output_path = os.path.join(OUTPUT_DIR, os.path.basename(input_path))
    logger.info(f"Editing video: {input_path}")

    # Smart trim logic
    start_time = detect_best_segment(input_path, min_duration=20, max_duration=60)
    logger.info(f"Selected best segment start time: {start_time:.2f}s")

    filter_complex = (
        "[0:v]scale=1080:-1,"
        "crop=1080:1920:(in_w-1080)/2:(in_h-1920)/2,"
        "eq=contrast=1.1:brightness=0.05,"
        "unsharp=luma_msize_x=5:luma_msize_y=5:luma_amount=1.0,"
        "fade=t=in:st=0:d=1,fade=t=out:st=44:d=1,"
        "minterpolate='fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1',"
        "setpts=PTS-STARTPTS[v];"
        "[0:a]silenceremove=start_periods=1:start_silence=0.5:start_threshold=-30dB:"
        "stop_periods=1:stop_silence=0.5:stop_threshold=-30dB:detection=peak,"
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

    await run_ffmpeg_async(ffmpeg_cmd)
    logger.info(f"Edited video saved to: {output_path}")
    return output_path

def is_video_suitable(path: str) -> bool:
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration",
            "-of", "json",
            path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)
        stream = info["streams"][0]
        duration = float(stream.get("duration", 0))
        width = int(stream.get("width", 0))
        height = int(stream.get("height", 0))

        return (
            15 <= duration <= 90 and
            width >= 640 and
            height >= 360
        )
    except Exception as e:
        logger.warning(f"Video suitability check failed: {e}")
        return False
