"""Phase 2 of the NVR video pipeline: uploads whatever recording files the
NVR's own "Download to PC" mechanism has already saved locally (triggered by
scripts/nvr_download.py) to the EntryGuard API as jobs.

Run only after the NVR has actually finished saving files for that date
(scripts/nvr_download.py prints an estimate, typically several hours):

    venv\\Scripts\\python -m scripts.upload_downloaded_videos [--date YYYY-MM-DD]

This only enqueues jobs and exits - it does not wait for them to finish
processing (each can take a long time, and the Celery worker's --pool=solo
setup processes one at a time regardless of how many are queued here). Check
progress via the Streamlit app or GET /jobs/{id}; job ids are also logged to
upload_log.json in the same folder the videos were read from.

Requires NVR_ZONE to be set (see .env.example) - the API requires a zone on
every job, so there's nothing useful to upload without one configured for
this camera.
"""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import requests

from backend.config import (
    API_BASE_URL,
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_EVENT_GAP_SECONDS,
    NVR_UPLOAD_LOG_FILENAME,
    NVR_ZONE,
)

UPLOAD_TIMEOUT_SECONDS = 600

# .dav/.264 are common proprietary NVR export containers; core/video_processor.py's
# cv2.VideoCapture generally cannot open them directly - if a job fails
# immediately with "Could not open video", that file likely needs
# re-exporting/converting to .mp4 first.
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".dav", ".264"}


def find_video_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXTENSIONS)


def upload_video(path: Path) -> str:
    params = {
        "confidence_threshold": DEFAULT_CONFIDENCE_THRESHOLD,
        "event_gap_seconds": DEFAULT_EVENT_GAP_SECONDS,
        "zone": ",".join(f"{coord}" for point in NVR_ZONE for coord in point),
    }

    with path.open("rb") as video_file:
        response = requests.post(
            f"{API_BASE_URL}/jobs",
            params=params,
            files={"file": (path.name, video_file, "application/octet-stream")},
            timeout=UPLOAD_TIMEOUT_SECONDS,
        )
    response.raise_for_status()
    return response.json()["job_id"]


def main() -> None:
    if not NVR_ZONE:
        raise SystemExit("Set NVR_ZONE (see .env.example) before running this - the API requires a zone on every job.")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        default=(date.today() - timedelta(days=1)).strftime("%Y-%m-%d"),
        help="Date folder to upload from under your user profile (default: yesterday)",
    )
    args = parser.parse_args()

    folder = Path.home() / args.date
    if not folder.is_dir():
        raise SystemExit(f"No download folder found at {folder}")

    videos = find_video_files(folder)
    if not videos:
        raise SystemExit(f"No video files found in {folder}")

    log = {}
    for video_path in videos:
        print(f"Uploading {video_path.name} ...")
        job_id = upload_video(video_path)
        log[video_path.name] = job_id
        print(f"  -> job_id {job_id}")

    log_path = folder / NVR_UPLOAD_LOG_FILENAME
    log_path.write_text(json.dumps(log, indent=2))
    print(f"Logged {len(log)} job id(s) to {log_path}")


if __name__ == "__main__":
    main()
