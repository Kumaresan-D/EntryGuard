"""Celery tasks backing POST /nvr/download: trigger the NVR download, then
automatically collect and process whatever it saved locally after a delay.

Split into two tasks so the multi-hour wait for the NVR to finish saving
files doesn't tie up a worker slot - collect_and_upload_task is scheduled
with a countdown (Celery just delays when it becomes available on the
broker) rather than the trigger task sleeping.
"""

import json
from datetime import date, timedelta
from pathlib import Path

from backend.celery_app import celery_app
from backend.config import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_EVENT_GAP_SECONDS,
    NVR_UPLOAD_DELAY_SECONDS,
    NVR_UPLOAD_LOG_FILENAME,
    NVR_ZONE,
)
from backend.worker.tasks import process_video_task

# .dav/.264 are common proprietary NVR export containers; core/video_processor.py's
# cv2.VideoCapture generally cannot open them directly - a resulting job
# failing immediately with "Could not open video" likely needs that file
# re-exported/converted to .mp4 first.
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".dav", ".264"}


def _yesterday() -> str:
    return (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")


@celery_app.task(name="run_nvr_download_task", bind=True)
def run_nvr_download_task(self):
    """Runs scripts/nvr_download.py's browser automation, then schedules
    collect_and_upload_task to run NVR_UPLOAD_DELAY_SECONDS later.

    Computes the target date once, here, and passes it through explicitly to
    collect_and_upload_task rather than having that task recompute "yesterday"
    at its own (much later) execution time - otherwise a download triggered
    late at night could have its collection step run past midnight and land
    on the wrong day's folder.
    """
    from scripts.nvr_download import main as download_main

    target_date = _yesterday()

    try:
        download_main()
    except SystemExit as exc:
        # nvr_download.py raises SystemExit for CLI-style "missing config"
        # errors; re-raise as a normal exception so Celery's task-failure
        # handling (not the interpreter's exit machinery) takes over.
        raise RuntimeError(str(exc)) from exc

    collect_and_upload_task.apply_async(args=[target_date], countdown=NVR_UPLOAD_DELAY_SECONDS)


@celery_app.task(name="collect_and_upload_task", bind=True)
def collect_and_upload_task(self, target_date: str | None = None):
    """Scans target_date's download folder (default: yesterday) and enqueues
    a process_video_task per video file found - reuses each file's existing
    path on disk directly, no need to copy it into UPLOAD_DIR first since
    it's already local.

    Also writes NVR_UPLOAD_LOG_FILENAME into that same folder (filename ->
    job_id) - the same manifest format scripts/upload_downloaded_videos.py
    already writes - so GET /nvr/images/{date} can later look up which jobs
    (and therefore which violation screenshots) came from that date.
    """
    if not NVR_ZONE:
        raise RuntimeError("NVR_ZONE must be set (see .env.example) before videos can be processed.")

    target_date = target_date or _yesterday()
    folder = Path.home() / target_date
    if not folder.is_dir():
        return {"folder": str(folder), "job_ids": [], "error": "folder not found"}

    videos = sorted(p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXTENSIONS)
    log = {
        video_path.name: process_video_task.apply_async(
            args=[str(video_path), NVR_ZONE, DEFAULT_CONFIDENCE_THRESHOLD, DEFAULT_EVENT_GAP_SECONDS]
        ).id
        for video_path in videos
    }
    (folder / NVR_UPLOAD_LOG_FILENAME).write_text(json.dumps(log, indent=2))

    return {"folder": str(folder), "job_ids": list(log.values())}
