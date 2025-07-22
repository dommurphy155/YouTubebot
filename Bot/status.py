# status.py
import os
import time
import psutil
import platform
from datetime import datetime
from pathlib import Path

BOOT_TIME = time.time()
VERSION_PATH = Path(__file__).parent / "VERSION"
DOWNLOAD_DIR = Path(__file__).parent / "downloads"
EDITING_DIR = Path(__file__).parent / "editing"
READY_DIR = Path(__file__).parent / "ready"

def get_uptime():
    seconds = time.time() - BOOT_TIME
    hours, remainder = divmod(int(seconds), 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours}h {minutes}m"

def get_cpu_usage():
    return f"{psutil.cpu_percent()}%"

def get_ram_usage():
    mem = psutil.virtual_memory()
    return f"{mem.percent}%"

def get_disk_usage():
    disk = psutil.disk_usage('/')
    return f"{disk.percent}%"

def get_system_load():
    load1, load5, load15 = os.getloadavg()
    return f"{load1:.2f}, {load5:.2f}, {load15:.2f}"

def get_bot_version():
    return VERSION_PATH.read_text().strip() if VERSION_PATH.exists() else "v0.0.1"

def count_videos():
    downloaded = len(list(DOWNLOAD_DIR.glob("*.mp4")))
    editing = len(list(EDITING_DIR.glob("*.mp4")))
    ready = len(list(READY_DIR.glob("*.mp4")))
    return downloaded, editing, ready

def get_edit_progress():
    progress_file = Path("edit_progress.txt")
    if progress_file.exists():
        return progress_file.read_text().strip()
    return "N/A"

def get_next_schedule():
    schedule_file = Path("next_send.txt")
    if schedule_file.exists():
        try:
            ts = float(schedule_file.read_text().strip())
            dt = datetime.fromtimestamp(ts).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            return dt
        except:
            return "Invalid timestamp"
    return "Not scheduled"
