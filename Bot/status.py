import os
from fastapi import FastAPI
from threading import Thread
import psutil
import uvicorn
import logging

def start_status_listener(token, chat_id):
    app = FastAPI()

    @app.get("/status")
    def status():
        proc = psutil.Process(os.getpid())
        return {
            "uptime": proc.create_time(),
            "cpu_percent": psutil.cpu_percent(),
            "memory": proc.memory_info().rss,
            "videos_in_tmp": len(psutil.os.listdir(psutil.os.tempdir)),
        }

    def run():
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")

    Thread(target=run, daemon=True).start()
    logging.info("Status endpoint active on port 8000")
