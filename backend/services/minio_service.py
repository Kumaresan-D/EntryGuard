"""MinIO object storage for violation screenshots.

VIOLATIONS_DIR on local disk stays the pipeline's own source of truth - the
worker writes each screenshot there first (see worker/tasks.py), then mirrors
it here. What MinIO buys is a directly-fetchable image URL: GET
/nvr/images/{date} can return a presigned link per violation, so a caller
gets the actual images from that one date-parameterised request instead of
having to loop back through the API for every JPEG's bytes.

Everything here degrades to a no-op when MinIO isn't configured
(config.MINIO_ENABLED is false) or is unreachable: uploads are best-effort
and never fail a detection job, and lookups return None/[] so callers fall
back to the local-disk path. The minio package is imported lazily inside
_client() for the same reason - the API and worker still start without it.
"""

import time
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from backend.config import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENABLED,
    MINIO_ENDPOINT,
    MINIO_PUBLIC_URL_BASE,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
    MINIO_TIMEOUT_SECONDS,
    MINIO_UNREACHABLE_COOLDOWN_SECONDS,
    MINIO_URL_EXPIRY_SECONDS,
)

# Objects are laid out one "folder" per job so list_violation_indexes can
# list a single prefix: violations/<job_id>/<index>.jpg
_OBJECT_PREFIX = "violations"

# Set when MinIO looks unreachable, so the rest of a request (and the next
# minute of them) falls straight back to local disk instead of each call
# paying the connect timeout over again.
_unreachable_until = 0.0


def _mark_unreachable() -> None:
    global _unreachable_until
    _unreachable_until = time.monotonic() + MINIO_UNREACHABLE_COOLDOWN_SECONDS


def object_name_for(job_id: str, index: int) -> str:
    return f"{_OBJECT_PREFIX}/{job_id}/{index}.jpg"


@lru_cache(maxsize=1)
def _build_client():
    """Builds the shared Minio client and ensures the bucket exists - once per
    process. The explicit http_client is what keeps a dead endpoint cheap: the
    SDK's default retries a failed connection several times with backoff."""
    import urllib3
    from minio import Minio

    http_client = urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=MINIO_TIMEOUT_SECONDS, read=MINIO_TIMEOUT_SECONDS),
        retries=urllib3.Retry(total=1, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504]),
    )
    client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
        http_client=http_client,
    )
    if not client.bucket_exists(MINIO_BUCKET):
        client.make_bucket(MINIO_BUCKET)
    return client


def _client():
    """The shared client, or None when MinIO is disabled, in its unreachable
    cooldown, or failing to connect - which is what makes every function below
    degrade gracefully instead of raising into the caller."""
    if not MINIO_ENABLED or time.monotonic() < _unreachable_until:
        return None

    try:
        return _build_client()
    except Exception as exc:  # noqa: BLE001
        _mark_unreachable()
        print(f"[minio] unreachable ({exc}) - falling back to local disk for {MINIO_UNREACHABLE_COOLDOWN_SECONDS:.0f}s")
        return None


def _public(url: str) -> str:
    """Swaps a presigned URL's scheme+host for MINIO_PUBLIC_URL_BASE when set.

    Safe to do after signing: SigV4 signs the path and query string, not the
    host, so only the reachable address changes and the signature still
    verifies.
    """
    if not MINIO_PUBLIC_URL_BASE:
        return url
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    return f"{MINIO_PUBLIC_URL_BASE}{parts.path}?{parts.query}" if parts.query else f"{MINIO_PUBLIC_URL_BASE}{parts.path}"


def upload_violation_screenshot(job_id: str, index: int, local_path: Path) -> bool:
    """Mirrors one already-saved screenshot into MinIO. Best-effort: returns
    False (rather than raising) if MinIO is off or the put fails, so a storage
    hiccup can never kill an in-flight detection job."""
    client = _client()
    if client is None:
        return False

    try:
        client.fput_object(MINIO_BUCKET, object_name_for(job_id, index), str(local_path), content_type="image/jpeg")
        return True
    except Exception as exc:  # noqa: BLE001 - never propagate into the pipeline
        print(f"[minio] upload failed for {job_id}_{index}.jpg: {exc}")
        return False


def presigned_url(job_id: str, index: int) -> str | None:
    """A time-limited direct URL for one screenshot, or None if MinIO is
    off/unreachable or the object isn't there.

    Objects are stored with content_type="image/jpeg" and no
    Content-Disposition, so opening this link renders the screenshot in the
    browser rather than downloading it. Signed response-header overrides
    (response-content-disposition) would do the same explicitly, but moto -
    the S3 stand-in this was tested against - mishandles them and answers
    text/plain, so the stored content type is what we rely on.
    """
    client = _client()
    if client is None:
        return None

    try:
        url = client.presigned_get_object(
            MINIO_BUCKET,
            object_name_for(job_id, index),
            expires=timedelta(seconds=MINIO_URL_EXPIRY_SECONDS),
        )
        return _public(url)
    except Exception as exc:  # noqa: BLE001
        print(f"[minio] presign failed for {job_id}_{index}.jpg: {exc}")
        return None


def list_violation_indexes(job_id: str) -> list[int]:
    """Every violation index stored in MinIO for a job, sorted. Empty when
    MinIO is off/unreachable, which makes callers fall back to disk."""
    client = _client()
    if client is None:
        return []

    try:
        objects = client.list_objects(MINIO_BUCKET, prefix=f"{_OBJECT_PREFIX}/{job_id}/", recursive=True)
        return sorted(int(Path(obj.object_name).stem) for obj in objects)
    except Exception as exc:  # noqa: BLE001
        # Listing is the reachability probe nvr_service relies on, so a
        # failure here also opens the cooldown window.
        _mark_unreachable()
        print(f"[minio] list failed for {job_id}: {exc}")
        return []
