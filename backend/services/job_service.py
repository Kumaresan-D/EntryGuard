"""Business logic for video-processing jobs: zone validation, job dispatch, and status formatting.

Kept separate from routes/jobs.py so the HTTP layer stays thin (parse the
request, call a service function, shape the response) and this layer has no
FastAPI-response-shaping concerns of its own.
"""

import time
import uuid
from pathlib import Path

from fastapi import UploadFile
from kombu.exceptions import DecodeError

from backend.celery_app import celery_app
from backend.config import UPLOAD_CHUNK_SIZE_BYTES
from backend.storage import input_path_for, violation_screenshot_path_for
from backend.worker.tasks import process_video_task


class InvalidZoneError(ValueError):
    """Raised when a zone string fails validation - the route layer maps this to a 400."""


def parse_zone(zone: str) -> tuple:
    try:
        coords = [float(v) for v in zone.split(",")]
    except ValueError:
        raise InvalidZoneError("zone must be a comma-separated list of numbers")
    if len(coords) < 6 or len(coords) % 2 != 0:
        raise InvalidZoneError("zone must have an even count of at least 6 numbers (>= 3 points)")
    return tuple(zip(coords[0::2], coords[1::2]))


async def create_job(file: UploadFile, zone: str, confidence_threshold: float, event_gap_seconds: float) -> str:
    """Validates the zone, saves the upload, and dispatches the Celery task. Returns the new job_id."""
    parsed_zone = parse_zone(zone)

    job_id = uuid.uuid4().hex
    input_path = input_path_for(job_id, file.filename)

    with input_path.open("wb") as out_file:
        while chunk := await file.read(UPLOAD_CHUNK_SIZE_BYTES):
            out_file.write(chunk)

    process_video_task.apply_async(
        args=[str(input_path), parsed_zone, confidence_threshold, event_gap_seconds],
        task_id=job_id,
    )
    return job_id


def _read_result_meta(result, attempts=3, retry_delay_seconds=0.05):
    """Reads (status, info) off a Celery AsyncResult, retrying on DecodeError.

    The filesystem result backend (config.py) overwrites one plain file per
    state update with no atomicity, so a read landing mid-write can briefly
    see a corrupt half-old/half-new file. That's transient - the next write
    completes it - so a short retry clears it up instead of surfacing a 500.
    """
    for attempt in range(attempts):
        try:
            return result.status, result.info
        except DecodeError:
            if attempt == attempts - 1:
                raise
            time.sleep(retry_delay_seconds)


def get_job_status(job_id: str) -> dict:
    result = celery_app.AsyncResult(job_id)
    # Read status/info together: Celery doesn't cache non-final states (so
    # polling sees live updates), meaning two separate reads can observe two
    # different snapshots if the task advances in between.
    status, info = _read_result_meta(result)

    response = {"job_id": job_id, "status": status}
    if status == "PROCESSING" and isinstance(info, dict):
        response["progress"] = info.get("progress")
    elif status == "SUCCESS" and isinstance(info, dict) and "passage_count" in info:
        response["passage_count"] = info["passage_count"]
        response["violation_count"] = info["violation_count"]
        response["violations"] = info["violations"]
    elif status == "FAILURE":
        response["error"] = str(info)

    return response


def get_violation_screenshot_path(job_id: str, index: int) -> Path:
    return violation_screenshot_path_for(job_id, index)
