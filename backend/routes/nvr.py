"""HTTP routes for the NVR download-then-upload pipeline."""

from fastapi import APIRouter, HTTPException

from backend.services.nvr_service import DateNotFoundError, get_violation_images_for_date
from backend.worker.nvr_tasks import run_nvr_download_task

router = APIRouter(prefix="/nvr", tags=["nvr"])


@router.post("/download")
def trigger_nvr_download():
    """Triggers scripts/nvr_download.py's browser automation asynchronously,
    then automatically collects and processes whatever the NVR saved locally
    config.NVR_UPLOAD_DELAY_SECONDS later (default 2 hours)."""
    result = run_nvr_download_task.apply_async()
    return {"task_id": result.id, "status": "triggered"}


@router.get("/images/{target_date}")
def get_violation_images(target_date: str):
    """Returns every violation screenshot produced from videos downloaded on
    target_date (YYYY-MM-DD, matching the NVR's own download folder naming).

    Each entry's job_id/index can be fetched as an actual image via the
    existing GET /jobs/{job_id}/violations/{index}/screenshot endpoint.
    """
    try:
        images = get_violation_images_for_date(target_date)
    except DateNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"date": target_date, "count": len(images), "images": images}
