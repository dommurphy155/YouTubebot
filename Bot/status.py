import os
import logging
import psutil
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
import subprocess

logger = logging.getLogger("TelegramVideoBot")
app = FastAPI()

BOOT_TIME = datetime.fromtimestamp(psutil.boot_time())

@app.get("/status")
def get_status():
    try:
        uptime = str(datetime.now() - BOOT_TIME).split('.')[0]
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        load = os.getloadavg()

        logs = subprocess.check_output(["tail", "-n", "20", "/var/log/syslog"]).decode("utf-8", errors="ignore")

        return JSONResponse({
            "uptime": uptime,
            "cpu_percent": cpu,
            "memory_used_percent": mem.percent,
            "disk_used_percent": disk.percent,
            "load_avg": load,
            "logs": logs
        })

    except Exception as e:
        logger.error(f"Status endpoint failed: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
