"""Central configuration for the detection POC."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # loads .env if present - see .env.example; never hardcode secrets here

_REPO_ROOT = Path(__file__).resolve().parent.parent

BASE_MODEL_PATH = "yolov8s.pt"
_OPENVINO_MODEL_DIR = _REPO_ROOT / f"{Path(BASE_MODEL_PATH).stem}_openvino_model"

# OpenVINO (Intel's inference runtime) runs YOLO ~3x faster than plain
# PyTorch on CPU-only machines like this one - run scripts/export_model.py
# once to generate it. Falls back to the plain .pt model if that hasn't
# been done.
MODEL_PATH = str(_OPENVINO_MODEL_DIR) if _OPENVINO_MODEL_DIR.is_dir() else BASE_MODEL_PATH

# Streamlit talks to the FastAPI service over HTTP as a plain client -
# override for a backend running elsewhere.
API_BASE_URL = os.environ.get("ENTRYGUARD_API_URL", "http://127.0.0.1:8000")
NGROK_DOMAIN = os.environ.get("NGROK_DOMAIN","https://premonarchal-marya-synostotically.ngrok-free.dev")

# COCO class id for "person"
PERSON_CLASS_ID = 0

DEFAULT_CONFIDENCE_THRESHOLD = 0.4

# Distinct people entering the turnstile zone within this many seconds of
# each other are treated as the same passage event. Tune to roughly how
# long one turnstile activation/rotation takes.
DEFAULT_EVENT_GAP_SECONDS = 3.0

# Number of points the zone picker (frontend/app.py) and NVR_ZONE (below) use
# to mark the turnstile passage - an arbitrary polygon of this many vertices,
# in any order/orientation. TailgateDetector._is_inside does a real
# point-in-polygon test, so any count >= 3 works without other code changes.
ZONE_POINT_COUNT = 4

BOX_COLOR = (0, 200, 0)
TEXT_COLOR = (255, 255, 255)

# Run YOLO detection/tracking on only 1 out of every FRAME_SKIP frames; the
# skipped frames' overlay reuses the last detected/tracked boxes so it
# doesn't flicker. Cuts inference cost roughly proportionally, at the cost
# of coarser per-frame timing precision (still fine for turnstile-speed
# passages relative to DEFAULT_EVENT_GAP_SECONDS).
FRAME_SKIP = 2

# Size of each chunk read/written while saving an upload, so
# services/job_service.py never holds a whole (possibly multi-GB) upload in
# memory at once.
UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024

STORAGE_DIR = _REPO_ROOT / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
VIOLATIONS_DIR = STORAGE_DIR / "violations"

# Celery runs on the local filesystem for this POC: no broker/result-store
# service to install or keep running. Swap these for a real broker
# (e.g. redis://...) later without touching routes/services/worker.
CELERY_BROKER_DIR = STORAGE_DIR / "broker"
CELERY_RESULTS_DIR = STORAGE_DIR / "results"

CELERY_BROKER_URL = "filesystem://"
CELERY_RESULT_BACKEND = f"file:///{CELERY_RESULTS_DIR.resolve().as_posix()}"

# --- NVR download automation (scripts/nvr_download.py / scripts/upload_downloaded_videos.py) ---
# Credentials and the NVR's address come from environment variables / .env
# (see .env.example) - never hardcode them here or anywhere committed.
NVR_URL = os.environ.get("NVR_URL")
NVR_USERNAME = os.environ.get("NVR_USERNAME")
NVR_PASSWORD = os.environ.get("NVR_PASSWORD")
NVR_CHANNEL_LABEL = os.environ.get("NVR_CHANNEL_LABEL", "North West")
NVR_ROWS_TO_DOWNLOAD = int(os.environ.get("NVR_ROWS_TO_DOWNLOAD", "3"))

# Headless by default (needed for an unattended Task Scheduler run - see
# scripts/setup_scheduled_tasks.ps1); set NVR_HEADLESS=false in .env to watch
# the browser while debugging selectors against the real NVR page.
NVR_HEADLESS = os.environ.get("NVR_HEADLESS", "true").strip().lower() != "false"

# Optional fixed turnstile zone polygon for this camera, as
# "x1,y1,x2,y2,...,xN,yN" - pick these once via the Streamlit app's zone
# picker against a frame from this camera. If unset,
# scripts/upload_downloaded_videos.py refuses to run (a zone is required).
_NVR_ZONE_RAW = os.environ.get("NVR_ZONE")
NVR_ZONE = None
if _NVR_ZONE_RAW:
    _zone_coords = [float(v) for v in _NVR_ZONE_RAW.split(",")]
    NVR_ZONE = tuple(zip(_zone_coords[0::2], _zone_coords[1::2]))

# How long after POST /nvr/download triggers the download to wait before
# automatically collecting and uploading whatever the NVR saved locally (see
# backend/worker/nvr_tasks.py). A fixed guess, not an actual "download
# finished" check - if the NVR sometimes takes longer, raise this.
NVR_UPLOAD_DELAY_SECONDS = int(os.environ.get("NVR_UPLOAD_DELAY_SECONDS", str(2 * 60 * 60)))

# Manifest filename (filename -> job_id) written into each NVR download date
# folder (Path.home() / "<date>") by both scripts/upload_downloaded_videos.py
# and backend/worker/nvr_tasks.py's collect_and_upload_task - GET
# /nvr/images/{date} reads this to know which jobs came from which date.
NVR_UPLOAD_LOG_FILENAME = "upload_log.json"

# --- MinIO object storage for violation screenshots ---
# Screenshots are written to VIOLATIONS_DIR first (that stays the pipeline's
# own source of truth), then mirrored into MinIO so GET /nvr/images/{date}
# can hand back a directly-fetchable image URL instead of only an index.
# Every MinIO setting comes from .env - never hardcode keys here.
# Unset MINIO_ENDPOINT/keys simply disables the whole integration and the
# API falls back to serving screenshots off local disk, so the POC still
# runs with no object store at all.
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "").strip()  # "host:port", no scheme
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "").strip()
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "").strip()
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "entryguard-violations").strip()

# true when MinIO is behind HTTPS; a plain local `minio server` is http.
MINIO_SECURE = os.environ.get("MINIO_SECURE", "false").strip().lower() == "true"

# How long a presigned screenshot URL stays valid. AWS SigV4 (which MinIO
# implements) caps this at 7 days, so anything larger is clamped below.
MINIO_URL_EXPIRY_SECONDS = min(int(os.environ.get("MINIO_URL_EXPIRY_SECONDS", str(24 * 60 * 60))), 7 * 24 * 60 * 60)

MINIO_ENABLED = bool(MINIO_ENDPOINT and MINIO_ACCESS_KEY and MINIO_SECRET_KEY)

# Optional: what the outside world should call MinIO, when that differs from
# MINIO_ENDPOINT (e.g. the API reaches it at 127.0.0.1:9000, but a caller
# coming in over ngrok cannot). Presigned URLs are generated against
# MINIO_ENDPOINT and then have their scheme+host swapped for this, which is
# signature-safe: SigV4 signs the path and query, not the host.
MINIO_PUBLIC_URL_BASE = os.environ.get("MINIO_PUBLIC_URL_BASE", "").strip().rstrip("/")

# Per-request connect/read timeout for MinIO calls. The SDK's stock client
# retries a dead endpoint with backoff, which turns "MinIO is down" into a
# multi-minute hang on GET /nvr/images/{date} instead of a quick fall back to
# local disk - so the client is built with this timeout and a single retry.
MINIO_TIMEOUT_SECONDS = float(os.environ.get("MINIO_TIMEOUT_SECONDS", "3"))

# After a failed reachability check, skip MinIO entirely for this long rather
# than paying the timeout again on every job in the same request.
MINIO_UNREACHABLE_COOLDOWN_SECONDS = float(os.environ.get("MINIO_UNREACHABLE_COOLDOWN_SECONDS", "60"))
