"""Quick manual test: upload one specific video file to the EntryGuard API,
wait for it to finish processing, and print the result.

    venv\\Scripts\\python -m scripts.test_process_video "C:\\path\\to\\video.mp4"

Requires NVR_ZONE to be set (see .env.example) - the API requires a zone on
every job.
"""

import argparse
import time
from pathlib import Path

import requests

from backend.config import API_BASE_URL, DEFAULT_CONFIDENCE_THRESHOLD, DEFAULT_EVENT_GAP_SECONDS, NVR_ZONE

UPLOAD_TIMEOUT_SECONDS = 600
POLL_INTERVAL_SECONDS = 2


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


def wait_for_job(job_id: str) -> dict:
    while True:
        response = requests.get(f"{API_BASE_URL}/jobs/{job_id}", timeout=10)
        response.raise_for_status()
        job = response.json()

        if job["status"] == "PROCESSING" and job.get("progress") is not None:
            print(f"  processing... {job['progress'] * 100:.0f}%")
        elif job["status"] in ("SUCCESS", "FAILURE"):
            return job

        time.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    if not NVR_ZONE:
        raise SystemExit("Set NVR_ZONE (see .env.example) before running this - the API requires a zone on every job.")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_path", help="Path to the video file to process")
    args = parser.parse_args()

    path = Path(args.video_path)
    if not path.is_file():
        raise SystemExit(f"No such file: {path}")

    print(f"Uploading {path.name} ...")
    job_id = upload_video(path)
    print(f"job_id: {job_id}")

    job = wait_for_job(job_id)

    if job["status"] == "FAILURE":
        print(f"Failed: {job.get('error')}")
        return

    print("Done.")
    print(f"Passages: {job['passage_count']}  Violations: {job['violation_count']}")
    for index, violation in enumerate(job["violations"]):
        minutes, seconds = divmod(violation["start_time"], 60)
        print(
            f"  - {int(minutes):02d}:{seconds:05.2f} - {violation['person_count']} people "
            f"(screenshot: {API_BASE_URL}/jobs/{job_id}/violations/{index}/screenshot)"
        )


if __name__ == "__main__":
    main()
