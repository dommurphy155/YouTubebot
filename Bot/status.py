import os
import time
import psutil
from pathlib import Path
from datetime import datetime

ROOT_DIR = Path(__file__).parent.parent
BOOT_TIME = time.time()

VERSION_PATH = ROOT_DIR / "VERSION"
DOWNLOAD_DIR = ROOT_DIR / "downloads"
EDITING_DIR = ROOT_DIR / "processed"
READY_DIR = ROOT_DIR / "edited"
PROGRESS_FILE = ROOT_DIR / "edit_progress.txt"
SCHEDULE_FILE = ROOT_DIR / "next_send.txt"

def get_uptime():
    seconds = int(time.time() - BOOT_TIME)
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours}h {minutes}m"

def get_cpu_usage():
    return f"{psutil.cpu_percent(interval=0.5)}%"

def get_ram_usage():
    return f"{psutil.virtual_memory().percent}%"

def get_disk_usage():
    return f"{psutil.disk_usage('/').percent}%"

def get_system_load():
    try:
        load1, load5, load15 = os.getloadavg()
        return f"{load1:.2f}, {load5:.2f}, {load15:.2f}"
    except:
        return "Unavailable"

def get_bot_version():
    try:
        return VERSION_PATH.read_text().strip()
    except:
        return "v0.0.1"

def count_videos():
    try:
        downloaded = len(list(DOWNLOAD_DIR.glob("*.mp4")))
        editing = len(list(EDITING_DIR.glob("*.mp4")))
        ready = len(list(READY_DIR.glob("*.mp4")))
        return downloaded, editing, ready
    except:
        return 0, 0, 0

def get_edit_progress():
    try:
        return PROGRESS_FILE.read_text().strip()
    except:
        return "N/A"

def get_next_schedule():
    try:
        ts = float(SCHEDULE_FILE.read_text().strip())
        dt = datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        return dt
    except:
        return "Not scheduled"
