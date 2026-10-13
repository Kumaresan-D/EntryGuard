"""Filesystem paths for uploaded videos and violation screenshots."""

from pathlib import Path

from backend.config import UPLOAD_DIR, VIOLATIONS_DIR


def ensure_storage_dirs() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    VIOLATIONS_DIR.mkdir(parents=True, exist_ok=True)


def input_path_for(job_id: str, filename: str) -> Path:
    suffix = Path(filename).suffix or ".mp4"
    return UPLOAD_DIR / f"{job_id}{suffix}"


def violation_screenshot_path_for(job_id: str, index: int) -> Path:
    return VIOLATIONS_DIR / f"{job_id}_{index}.jpg"


def find_violation_screenshots(job_id: str) -> list[Path]:
    """Returns every saved violation screenshot for a job, sorted by index."""
    return sorted(VIOLATIONS_DIR.glob(f"{job_id}_*.jpg"), key=lambda p: int(p.stem.rsplit("_", 1)[-1]))
