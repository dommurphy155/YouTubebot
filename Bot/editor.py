import ffmpeg
import os
import logging
import tempfile

def edit_video(input_path):
    output = os.path.join(tempfile.gettempdir(), "short.mp4")
    try:
        (
            ffmpeg.input(input_path)
            .trim(start=0, duration=30)
            .filter("scale", 1080, -2)
            .output(output, vcodec="libx264", crf=23, preset="fast", acodec="aac", audio_bitrate="96k")
            .overwrite_output()
            .run(quiet=True)
        )
        logging.info("Edited video %s", output)
        return output
    except ffmpeg.Error as e:
        logging.error("FFmpeg error: %s", e)
        return None
