r"""Mirrors violation screenshots already on disk into MinIO.

The worker only uploads screenshots it writes from now on (worker/tasks.py),
so everything detected before MinIO was configured exists only in
VIOLATIONS_DIR. Run this once after pointing .env at a MinIO server to get
those older jobs served as presigned URLs by GET /nvr/images/{date} too.

Run from the repo root:  venv\Scripts\python -m scripts.backfill_minio
"""

from backend.config import MINIO_BUCKET, MINIO_ENABLED, MINIO_ENDPOINT, VIOLATIONS_DIR
from backend.services.minio_service import upload_violation_screenshot


def main() -> None:
    if not MINIO_ENABLED:
        raise SystemExit("MinIO is not configured - set MINIO_ENDPOINT/MINIO_ACCESS_KEY/MINIO_SECRET_KEY in .env first.")

    screenshots = sorted(VIOLATIONS_DIR.glob("*_*.jpg"))
    print(f"Uploading {len(screenshots)} screenshot(s) to {MINIO_ENDPOINT}/{MINIO_BUCKET} ...")

    uploaded = 0
    for path in screenshots:
        job_id, _, index = path.stem.rpartition("_")
        if not job_id or not index.isdigit():
            print(f"  skipped (unexpected name): {path.name}")
            continue
        if upload_violation_screenshot(job_id, int(index), path):
            uploaded += 1

    print(f"Done: {uploaded}/{len(screenshots)} uploaded.")


if __name__ == "__main__":
    main()
