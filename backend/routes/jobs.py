"""HTTP routes for video-processing jobs.

Kept thin: parse the request, delegate to services/job_service.py for all
actual logic, and shape the HTTP response/errors.
"""

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from backend.config import DEFAULT_CONFIDENCE_THRESHOLD, DEFAULT_EVENT_GAP_SECONDS
from backend.services.job_service import InvalidZoneError, create_job, get_job_status, get_violation_screenshot_path
from backend.services.minio_service import presigned_url

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("")
async def post_job(
    file: UploadFile = File(...),
    zone: str = Query(..., description='Turnstile passage polygon vertices as "x1,y1,x2,y2,...,xN,yN"'),
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    event_gap_seconds: float = DEFAULT_EVENT_GAP_SECONDS,
):
    """zone marks the turnstile passage polygon's vertices (any order/orientation,
    any vertex count >= 3) as "x1,y1,x2,y2,...,xN,yN"; required on every job."""
    try:
        job_id = await create_job(file, zone, confidence_threshold, event_gap_seconds)
    except InvalidZoneError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"job_id": job_id, "status": "queued"}


@router.get("/{job_id}")
def get_job(job_id: str):
    return get_job_status(job_id)


@router.get("/{job_id}/violations/{index}/screenshot")
def get_violation_screenshot(job_id: str, index: int):
    screenshot_path = get_violation_screenshot_path(job_id, index)
    if screenshot_path.exists():
        # No filename= here on purpose: FileResponse turns that into
        # "Content-Disposition: attachment", which makes a browser download
        # the JPEG instead of displaying it. inline renders it in the tab.
        return FileResponse(
            screenshot_path,
            media_type="image/jpeg",
            headers={"Content-Disposition": f'inline; filename="{screenshot_path.name}"'},
        )

    # Local file gone (cleaned up, or this API instance never had it) but the
    # MinIO mirror may still: hand the caller a presigned link to it rather
    # than a 404.
    url = presigned_url(job_id, index)
    if url:
        return RedirectResponse(url)

    raise HTTPException(status_code=404, detail="Violation screenshot not found")
