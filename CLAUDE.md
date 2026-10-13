# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

EntryGuard is a proof-of-concept for detecting turnstile tailgating from CCTV footage alone: an eSSL access-control device authorizes one person per turnstile activation, but the physical gate doesn't stop a second person following through in the same cycle. This POC infers "passage events" purely from person-tracking timing (no eSSL access-log/API correlation yet — see the module docstring in `backend/core/tailgate_detector.py` for the exact reasoning and what changes once that integration exists).

The only output artifacts are the JSON result (passage/violation counts) and one JPEG screenshot per violation — there is no processed output video; the pipeline reads and analyzes the video but never re-encodes/writes one.

## Running it

Three processes, all from the venv (`venv\`, not `.venv\`), run from the repo root — or just double-click `run.bat`, which starts all three at once, each in its own window, plus an ngrok tunnel publishing the API publicly (see below):

```
venv\Scripts\python -m uvicorn backend.main:app --reload                     # FastAPI backend (port 8000)
venv\Scripts\celery -A backend.celery_app worker --loglevel=info --pool=solo  # Celery worker (--pool=solo needed on Windows)
venv\Scripts\streamlit run frontend/app.py                                    # Streamlit frontend
```

One-time setup after cloning, to get faster CPU inference via OpenVINO:

```
venv\Scripts\python -m scripts.export_model
```

`run.bat` also starts `ngrok http 8000` in a fourth window so the API is reachable from outside the LAN. Set `NGROK_DOMAIN` in `.env` to a reserved ngrok domain (full URL, e.g. `https://entryguard.ngrok-free.app`) to keep that public URL constant across restarts; with it unset ngrok still starts but on a random URL, and if ngrok isn't on `PATH` the script prints setup instructions and leaves the other three processes running. The tunnel only fronts the backend (port 8000), never the Streamlit UI on 8501 — `backend/main.py` redirects `/` to `/docs`, so the tunnel's bare URL lands on Swagger. The Streamlit frontend keeps talking to `http://127.0.0.1:8000` unless you override `ENTRYGUARD_API_URL`.

`backend/config.py` automatically prefers the exported `<model>_openvino_model/` directory once it exists, falling back to the plain `.pt` weights (`config.BASE_MODEL_PATH`) otherwise.

Uploads are capped at 2 GB (`.streamlit/config.toml`'s `server.maxUploadSize`); `backend/services/job_service.py` streams the upload to disk in `config.UPLOAD_CHUNK_SIZE_BYTES` chunks rather than buffering it whole, but Streamlit itself (`streamlit.runtime.memory_uploaded_file_manager.MemoryUploadedFileManager`) holds the entire upload in memory regardless of size, so expect RAM usage on the order of the file size in the Streamlit process for large uploads.

There is no lint config and no automated test suite in this repo. `test1.py` at the root is an unrelated scratch script (a keystroke auto-typer) — not part of the detection pipeline and not a test suite, despite the "test" name.

## Layout

```
frontend/
  app.py        # Streamlit UI - a pure HTTP client of the backend, no detection logic
  config.py     # frontend-only constants, deliberately independent of backend/config.py

backend/
  main.py       # FastAPI app: mounts routers, ensures storage dirs exist
  config.py     # single source of truth for tunable constants - check here first when changing a default
  storage.py    # filesystem paths for uploads/violation screenshots, keyed by job_id
  celery_app.py # Celery app instance (filesystem broker/backend)
  routes/       # HTTP layer - thin, parses requests and shapes responses
    jobs.py
  services/     # business logic layer - validation, job dispatch, status formatting
    job_service.py
  worker/       # async execution layer - the Celery task itself
    tasks.py
  core/         # domain/pipeline layer - detection, tracking, tailgate logic, drawing
    detector.py, tracker.py, tailgate_detector.py, video_processor.py, drawing.py

scripts/        # standalone operational tooling, each run as `python -m scripts.<name>`
  export_model.py, nvr_download.py, upload_downloaded_videos.py, test_process_video.py, setup_scheduled_tasks.ps1

storage/        # runtime data: uploads, violations, Celery broker/results - not source code
```

**Why two separate `config.py` files:** `frontend/` and `backend/` are meant to be independently runnable — the frontend is just an HTTP client and has no business importing backend internals (model paths, Celery broker dirs, NVR credentials). `frontend/config.py` duplicates the handful of constants the UI actually needs (`API_BASE_URL`, the confidence/event-gap defaults, `ZONE_POINT_COUNT`); everything else lives only in `backend/config.py`. `scripts/` sits outside both — it's operator tooling that prepares data *for* the backend, so it imports `backend.config` directly rather than duplicating those settings too.

**Import/invocation rules that make this actually work:**
- Everything under `backend/` and `frontend/` uses **absolute** imports rooted at the package name (`from backend.config import ...`, `from backend.core.detector import ...`), never relative imports — stay consistent with this if you add files.
- All three long-running processes and every `scripts/*.py` invocation must run **from the repo root** — that's what puts the root on `sys.path` so `backend.*`/`frontend.*` packages resolve. Concretely: `uvicorn`/Celery both take a dotted module path (`backend.main:app`, `-A backend.celery_app`) and are launched via `-m`/their own CWD-aware bootstrap; Streamlit is pointed at `frontend/app.py`, and its own script-directory-relative import handling is what lets `frontend/app.py` find its sibling `frontend/config.py` via a plain `from config import ...`; `scripts/*.py` must be run as `python -m scripts.<name>` (not `python scripts/<name>.py`), since only `-m` invocation puts the repo root — not `scripts/` itself — on `sys.path`.
- `backend/config.py` computes `STORAGE_DIR`/`_OPENVINO_MODEL_DIR` as `Path(__file__).resolve().parent.parent / ...` (two levels up from `backend/config.py` to the repo root) specifically so the physical `storage/` and `<model>_openvino_model/` directories stay where they've always been on disk, independent of how deep `config.py` itself lives in the package tree. If you ever nest `backend/` deeper, update that path math.

## Architecture

Three processes talk over HTTP and a Celery queue — nothing shares in-process state:

- **`frontend/app.py`** — Streamlit frontend. Uploads video, lets the user click `config.ZONE_POINT_COUNT` points on the first frame to place a zone polygon (any order/orientation) — detection won't run until all points are placed, a zone is required on every job. Polls job status, shows passage/violation counts and each violation's screenshot.
- **`backend/routes/jobs.py`** — FastAPI routes, mounted by `backend/main.py`. `POST /jobs` saves the upload and enqueues a Celery task (`zone` is a required query param: `"x1,y1,x2,y2,...,xN,yN"`, at least 3 points); `GET /jobs/{id}` reads status/progress/result; `GET /jobs/{id}/violations/{index}/screenshot` serves the frame captured at the moment that violation was detected. Routes stay thin — all the actual logic (zone validation, saving the upload, dispatching the task, formatting the Celery result) lives in `backend/services/job_service.py`.
- **`backend/celery_app.py`** / **`backend/worker/tasks.py`** — the worker side. `worker.tasks.process_video_task` is the single entry point invoked async from `job_service.create_job`. Celery is configured with the **filesystem** broker/backend (`config.CELERY_BROKER_DIR`/`CELERY_RESULTS_DIR`), not Redis/RabbitMQ — there's no external broker service to run for this POC. Swap the broker URL in `config.py` for a real one later without touching the routes/services/worker layers.
- **`backend/routes/nvr.py`** / **`backend/worker/nvr_tasks.py`** — `POST /nvr/download` triggers the NVR download-then-upload pipeline; `GET /nvr/images/{date}` looks up every violation screenshot produced from that date's videos. See "Optional: NVR download pipeline" below.

Job identity is the Celery `task_id`, set equal to a generated `job_id`; `backend/storage.py` derives upload/violation-screenshot paths from that same id, so job state, Celery result, and files on disk are all keyed by one uuid.

The pipeline (`backend/core/video_processor.py`'s `process_video_with_tailgate_detection`): per-frame `PersonTracker.track()` (YOLO + ByteTrack, `core/tracker.py`, gives stable IDs across frames) feeds `TailgateDetector.update()` (`core/tailgate_detector.py`), which groups zone entries into passage events by time gap and flags any event with >1 distinct person as a violation. The zone itself is an arbitrary polygon (any vertex count ≥ 3, not an axis-aligned box) — `TailgateDetector._is_inside` does a real point-in-polygon test (`_point_in_polygon`, ray casting), so the zone can be freely shaped/oriented rather than always axis-aligned. Detection/tracking only runs every `config.FRAME_SKIP`-th frame to cut inference cost.

There is no video writer anywhere in this loop — frames are read and analyzed, never re-encoded. The only drawing that happens (`core/drawing.py`'s `draw_tracked_detections`/`draw_turnstile_zone`) is on the single frame captured the moment a passage event first becomes a violation (its 2nd distinct person entering the zone); `worker/tasks.py`'s `on_violation` callback saves that one frame via `storage.violation_screenshot_path_for(job_id, index)`, where `index` is that event's position within `tailgate_detector.violations` — stable because events close and append in chronological order and a violation event can only stay one.

A `PersonTracker` and `TailgateDetector` are scoped to exactly one video — a fresh instance is constructed per task (see `worker/tasks.py`); reusing one across videos would leak track IDs/state (`PersonTracker.track()` first call resets ByteTrack state via `persist=False`, every call after uses `persist=True`). `PersonDetector` instances (the underlying YOLO model), by contrast, are cached per confidence-threshold in `worker.tasks._detector_cache` and reused across jobs.

## Optional: NVR download pipeline

`scripts/nvr_download.py` (Playwright) logs into an NVR's web UI and triggers its own "Download to PC" for the previous day's footage on one channel; the NVR then saves files locally in the background (hours, independent of this script). Something later needs to scan that dated folder and upload whatever's there to the API as jobs — this requires `NVR_ZONE` to be set in `.env`, since the API now requires a zone on every job. Both scripts read config from `.env` (see `.env.example`) — the login form and date-picker selectors in `nvr_download.py` are best-effort and may need adjusting against the real NVR page (see that file's docstring).

`nvr_download.py` runs headless by default (`config.NVR_HEADLESS`); set `NVR_HEADLESS=false` in `.env` to watch it while fixing selectors.

Two independent ways to run the download-then-upload pipeline, pick one (or use both — they don't interfere with each other):

- **On demand, via API** — `POST /nvr/download` (`backend/routes/nvr.py`) enqueues `backend/worker/nvr_tasks.py`'s `run_nvr_download_task`, which computes "yesterday" once, runs the Playwright automation, then schedules `collect_and_upload_task(target_date)` via Celery's `apply_async(countdown=...)` to fire `config.NVR_UPLOAD_DELAY_SECONDS` later (default 2 hours) — no OS-level scheduler involved, and the multi-hour wait doesn't tie up a worker slot since it's just a delayed broker message. The date is computed once and threaded through explicitly rather than each task recomputing "yesterday" at its own execution time — otherwise a download triggered late at night could have its collection step run past midnight and land on the wrong day's folder. `collect_and_upload_task` calls `process_video_task.apply_async` directly per video file found in that date's folder, using each file's existing on-disk path (no need to copy it into `UPLOAD_DIR` first), and writes `config.NVR_UPLOAD_LOG_FILENAME` (`upload_log.json`, filename -> job_id) into that same folder. If the NVR sometimes takes longer than the configured delay to finish saving files, `collect_and_upload_task` will find an empty/partial folder — there's no real "is the download actually done" check, same caveat as the scheduled-task approach below.
- **Always-on daily schedule** — `scripts/upload_downloaded_videos.py` (a standalone script, not the Celery task above) scans the folder and uploads via a real HTTP `POST /jobs` call per file, writing the same `upload_log.json` manifest. `scripts/setup_scheduled_tasks.ps1` registers two daily Windows Scheduled Tasks (download, then upload a fixed `-DelayHours` later) so this runs unattended without anyone calling the API.

## Optional: MinIO object storage

Violation screenshots are always written to `VIOLATIONS_DIR` first — local disk stays the pipeline's source of truth — and are then mirrored into MinIO on a best-effort basis by `worker/tasks.py`'s `on_violation` callback. The point of the mirror is the response shape of `GET /nvr/images/{date}`: with MinIO configured, each violation's `url` is a **presigned MinIO link** the caller can fetch the JPEG from directly, rather than a path back into this API.

Everything lives in `backend/services/minio_service.py` and degrades to a no-op when `config.MINIO_ENABLED` is false (i.e. `MINIO_ENDPOINT`/keys unset in `.env`) or MinIO is unreachable: uploads return False instead of raising, so **a storage outage can never fail a detection job**; `presigned_url`/`list_violation_indexes` return `None`/`[]`, so `nvr_service` falls back to globbing `VIOLATIONS_DIR` and emitting the local `/jobs/.../screenshot` URL, exactly as it behaved before MinIO existed. The `minio` package is imported lazily inside `_client()` so the API and worker still start without it installed.

Objects are keyed `violations/<job_id>/<index>.jpg` — one prefix per job, so `list_violation_indexes` is a single prefix listing. `GET /jobs/{job_id}/violations/{index}/screenshot` serves the local file when it's there and otherwise redirects to the presigned URL, so screenshots keep resolving after local cleanup.

`MINIO_PUBLIC_URL_BASE` covers the case where callers can't reach `MINIO_ENDPOINT` themselves (API exposed via ngrok, MinIO on `127.0.0.1`): the presigned URL's scheme+host is swapped after signing, which is safe because SigV4 signs the path and query, not the host.

MinIO calls use an explicit 3s-timeout, single-retry HTTP client (`MINIO_TIMEOUT_SECONDS`) plus a process-level "unreachable" cooldown (`MINIO_UNREACHABLE_COOLDOWN_SECONDS`, 60s). Without those, a store that's down turns `GET /nvr/images/{date}` into a multi-minute hang instead of a fallback, because the SDK's default client retries a dead connection with backoff once per job. Presigning is pure local signing with no round-trip, so it "succeeds" against a dead store — which is why `nvr_service` only presigns indexes that MinIO's *listing* returned, using that listing as the reachability probe.

**Local testing:** MinIO's open-source server is archived — `dl.min.io` returns 410 and the GitHub releases carry no binaries — so there's no official server to install locally any more. `moto` (`venv\Scripts\python -m pip install "moto[s3,server]"`, a dev-only dependency deliberately kept out of `requirements.txt`) serves the same S3 API and is what this integration was verified against:

```
venv\Scripts\python -m moto.server -H 127.0.0.1 -p 9000   # S3-compatible test store
venv\Scripts\python -m scripts.backfill_minio             # re-seed it (moto is in-memory: restarting loses everything)
```

The client code is plain S3, so it works unchanged against a real MinIO deployment, AWS S3, or any other S3-compatible store — only the four `MINIO_*` values in `.env` change.

The worker only uploads screenshots written *after* MinIO was configured — run `venv\Scripts\python -m scripts.backfill_minio` once to mirror pre-existing ones from `VIOLATIONS_DIR`.

Either way you run it, `GET /nvr/images/{date}` (`backend/services/nvr_service.py`) reads that same `upload_log.json` manifest and, for each job_id in it, globs `VIOLATIONS_DIR` for that job's saved screenshots (`backend/storage.py`'s `find_violation_screenshots`) — this works even after a job's Celery result has expired, since it only depends on files already written to disk, not on Celery at all. Returns `{image, url, source_video, job_id, index}` per violation — `image` is the screenshot's filename on disk, `source_video` the NVR video it came from; the JPEG bytes themselves come from `url` (`GET /jobs/{job_id}/violations/{index}/screenshot`), this endpoint is only the index of what exists.
