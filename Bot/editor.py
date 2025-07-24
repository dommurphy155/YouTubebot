import os
import logging
import ffmpeg
import random
from moviepy.editor import VideoFileClip

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] editor.py: %(message)s",
    handlers=[logging.StreamHandler()]
)

INPUT_DIR = "downloads"
OUTPUT_DIR = "ready"
WATERMARK = "branding/logo.png"  # Put watermark PNG here (transparent, ~300x100 recommended)

MIN_DURATION = 20
MAX_DURATION = 60
TARGET_RESOLUTION = (1080, 1920)  # vertical
CRF = 25

def get_best_subclip(video: VideoFileClip, min_duration: int, max_duration: int) -> tuple:
    """Select subclip biased toward middle with slight randomness."""
    duration = video.duration
    if duration <= max_duration:
        return 0, duration
    window = random.randint(min_duration, max_duration)
    mid = duration / 2
    start = max(0, mid - window / 2 + random.uniform(-3, 3))
    end = start + window
    return round(start, 2), round(min(end, duration), 2)

def apply_ffmpeg_filters(input_path, output_path, start_time, end_time):
    try:
        logging.info("Applying ffmpeg filters...")

        input_stream = ffmpeg.input(input_path, ss=start_time, to=end_time)

        # Video Filters
        video = (
            input_stream.video
            .filter('scale', TARGET_RESOLUTION[0], -1)
            .filter('crop', TARGET_RESOLUTION[0], TARGET_RESOLUTION[1])
            .filter('eq', contrast=1.1, brightness=0.05, saturation=1.25)
            .filter('unsharp', 5, 5, 1.0, 5, 5, 0.0)
            .filter('zoompan', z='min(zoom+0.0015,1.03)', d=1)  # slow zoom-in effect
        )

        # Overlay watermark
        if os.path.isfile(WATERMARK):
            watermark = ffmpeg.input(WATERMARK)
            video = ffmpeg.overlay(video, watermark, x='(main_w-overlay_w)/2', y='main_h-overlay_h-50')

        # Audio
        audio = input_stream.audio

        # Final output
        (
            ffmpeg
            .output(video, audio, output_path,
                    vcodec='libx264',
                    acodec='aac',
                    crf=CRF,
                    preset='fast',
                    movflags='+faststart')
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )

        logging.info(f"✅ Rendered successfully: {output_path}")
        return True

    except ffmpeg.Error as e:
        logging.error("❌ FFmpeg error:")
        logging.error(e.stderr.decode(errors="ignore"))
        return False

def process_video(file_path):
    try:
        filename = os.path.basename(file_path)
        name, _ = os.path.splitext(filename)
        output_path = os.path.join(OUTPUT_DIR, f"{name}_edited.mp4")

        clip = VideoFileClip(file_path)
        start, end = get_best_subclip(clip, MIN_DURATION, MAX_DURATION)
        logging.info(f"🎬 Selected subclip: {start}s → {end}s (total: {clip.duration}s)")

        success = apply_ffmpeg_filters(file_path, output_path, start, end)

        clip.close()
        if not success:
            raise RuntimeError("FFmpeg failed.")
        return output_path
    except Exception as e:
        logging.error(f"Error processing {file_path}: {str(e)}")
        return None

def main():
    logging.info("🚀 Starting editor.py...")
    for file in os.listdir(INPUT_DIR):
        if file.endswith(".mp4"):
            input_path = os.path.join(INPUT_DIR, file)
            output_path = process_video(input_path)
            if output_path:
                logging.info(f"📤 Final saved: {output_path}")
            else:
                logging.warning(f"⚠️ Failed: {file}")

if __name__ == "__main__":
    main()
