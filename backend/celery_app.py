"""Celery application shared by the FastAPI process (producer) and the worker (consumer)."""

from celery import Celery

from backend.config import CELERY_BROKER_DIR, CELERY_BROKER_URL, CELERY_RESULT_BACKEND, CELERY_RESULTS_DIR

for _dir in (CELERY_BROKER_DIR, CELERY_RESULTS_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

celery_app = Celery(
    "entryguard",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["backend.worker.tasks", "backend.worker.nvr_tasks"],
)

celery_app.conf.task_track_started = True
celery_app.conf.broker_transport_options = {
    "data_folder_in": str(CELERY_BROKER_DIR),
    "data_folder_out": str(CELERY_BROKER_DIR),
    "control_folder": str(CELERY_BROKER_DIR / "control"),
}
