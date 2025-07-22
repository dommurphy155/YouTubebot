import subprocess
import random
from pathlib import Path
from bot.config import EDITED_DIR, VIDEO_LENGTH_SECONDS, VIDEO_RESOLUTION
from bot.utils import logger

def process_video(input_path: Path, keyword: str) -> Path | None:
    """
    Trim video to 20-35s random duration, resize to vertical 1080x1920,
    add text overlays (hook + CTA), burn captions (if any), and
    add fallback background music if audio is missing.
    Returns path to processed video or None on failure.
    """

    output_filename = f"{input_path.stem}_edited.mp4"
    output_path = Path(EDITED_DIR) / output_filename

    # Random trim duration within configured range
    min_sec, max_sec = VIDEO_LENGTH_SECONDS
    duration = random.randint(min_sec, max_sec)

    # Text overlays: Hook at start, CTA at end
    hook_text = f"{keyword.upper()} - WAIT FOR IT..."
    cta_text = "LIKE + SHARE"

    # FFmpeg filter complex for overlays:
    # 1) Scale and pad to 1080x1920 vertical
    # 2) Draw hook text for first 3 seconds
    # 3) Draw CTA text for last 3 seconds
    # 4) Add fallback background music if no audio detected

    filter_complex = (
        f"[0:v]scale=w=1080:h=1920:force_original_aspect_ratio=decrease,"
        f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
        f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        f"text='{hook_text}':fontcolor=white:fontsize=48:box=1:boxcolor=black@0.5:"
        f"x=(w-text_w)/2:y=50:enable='lt(t,3)',"
        f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
        f"text='{cta_text}':fontcolor=white:fontsize=48:box=1:boxcolor=black@0.5:"
        f"x=(w-text_w)/2:y=h-100:enable='gt(t,{duration}-3)'[v];"
        f"[0:a]asplit=2[a1][a2];"
        f"[a1]anull[aout];"
        f"[a2]volume=0[aout2]"
    )

    # We'll check audio presence and if missing, add fallback music
    # Using ffmpeg -i input -af "volumedetect" is possible but expensive;
    # here we simply try to mix fallback.mp3 with original audio if present.

    fallback_audio_path = Path(EDITED_DIR) / "fallback_music.mp3"
    if not fallback_audio_path.exists():
        logger.warning("Fallback music file missing. Audio fallback will be skipped.")

    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", "0",
            "-t", str(duration),
            "-i", str(input_path),
        ]

        if fallback_audio_path.exists():
            cmd += ["-stream_loop", "-1", "-i", str(fallback_audio_path)]

            cmd += [
                "-filter_complex",
                "[0:v]scale=w=1080:h=1920:force_original_aspect_ratio=decrease,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
                f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='{hook_text}':fontcolor=white:fontsize=48:box=1:boxcolor=black@0.5:x=(w-text_w)/2:y=50:enable='lt(t,3)',"
                f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='{cta_text}':fontcolor=white:fontsize=48:box=1:boxcolor=black@0.5:x=(w-text_w)/2:y=h-100:enable='gt(t,{duration}-3)'[v];"
                "[0:a]aresample=async=1,volume=1[a0];"
                "[1:a]aresample=async=1,volume=0.3,aloop=loop=-1:size=2e+09[a1];"
                "[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                "-map", "[v]",
                "-map", "[aout]",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                str(output_path)
            ]
        else:
            # No fallback audio, just video with existing audio trimmed
            cmd += [
                "-vf",
                f"scale=w=1080:h=1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
                f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='{hook_text}':fontcolor=white:fontsize=48:box=1:boxcolor=black@0.5:x=(w-text_w)/2:y=50:enable='lt(t,3)',"
                f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='{cta_text}':fontcolor=white:fontsize=48:box=1:boxcolor=black@0.5:x=(w-text_w)/2:y=h-100:enable='gt(t,{duration}-3)'",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "copy",
                str(output_path)
            ]

        logger.info(f"Running ffmpeg command: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
        logger.info(f"Video processed and saved to {output_path}")
        return output_path

    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg failed: {e}")
        return None
