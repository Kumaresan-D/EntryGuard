"""Business logic for finding what got processed for a given NVR download date.

Reads the upload_log.json manifest (filename -> job_id) that both
scripts/upload_downloaded_videos.py and worker/nvr_tasks.py's
collect_and_upload_task write into each date's download folder, then looks
up each job's saved violation screenshots directly on disk - this works even
after a job's Celery result has expired, since it doesn't depend on Celery
at all, only on files already written to VIOLATIONS_DIR.
"""

import json
from pathlib import Path

from backend.config import NVR_UPLOAD_LOG_FILENAME
from backend.services.minio_service import list_violation_indexes
from backend.storage import find_violation_screenshots
from backend.config import NGROK_DOMAIN


class DateNotFoundError(ValueError):
    """Raised when there's no upload_log.json for the requested date - the route layer maps this to a 404."""


def get_violation_images_for_date(date_str: str) -> list[dict]:
    """Returns one entry per violation screenshot from jobs created for
    date_str's download folder: {image, url, source_video, job_id, index}.

    url/index are what GET /jobs/{job_id}/violations/{index}/screenshot
    expects - that endpoint serves the actual JPEG bytes, this one is the
    index of what exists. source_video is the NVR video the screenshot was
    captured from, kept so a violation can be traced back to its footage.
    """
    manifest_path = Path.home() / date_str / NVR_UPLOAD_LOG_FILENAME
    if not manifest_path.is_file():
        raise DateNotFoundError(f"No upload log found for {date_str} at {manifest_path}")

    job_ids_by_filename = json.loads(manifest_path.read_text())

    images = []
    for filename, job_id in job_ids_by_filename.items():
        
        minio_indexes = set(list_violation_indexes(job_id))
        for index in _violation_indexes(job_id, minio_indexes):
           
            local_image_url = f"/jobs/{job_id}/violations/{index}/screenshot"

            if NGROK_DOMAIN:
                local_image_url = f"{NGROK_DOMAIN}{local_image_url}"

            url = local_image_url
            images.append(
                {
                    "image": f"{job_id}_{index}.jpg",
                    "url": url,
                    "source_video": filename,
                    "job_id": job_id,
                    "index": index,
                }
            )
    return images


def _violation_indexes(job_id: str, minio_indexes: set[int]) -> list[int]:
    """Violation indexes for a job: whatever MinIO listed, so this keeps
    working once screenshots live only in the object store, falling back to
    VIOLATIONS_DIR when MinIO is disabled, unreachable, or has nothing yet."""
    if minio_indexes:
        return sorted(minio_indexes)
    return [int(path.stem.rsplit("_", 1)[-1]) for path in find_violation_screenshots(job_id)]
