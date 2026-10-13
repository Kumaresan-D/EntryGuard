"""Celery task: run turnstile tailgate detection over an uploaded video."""

import cv2

from backend.celery_app import celery_app
from backend.config import DEFAULT_CONFIDENCE_THRESHOLD, DEFAULT_EVENT_GAP_SECONDS
from backend.core.detector import PersonDetector
from backend.core.tailgate_detector import TailgateDetector
from backend.core.tracker import PersonTracker
from backend.core.video_processor import process_video_with_tailgate_detection
from backend.services.minio_service import upload_violation_screenshot
from backend.storage import violation_screenshot_path_for

_detector_cache = {}


def _get_detector(confidence_threshold: float) -> PersonDetector:
    if confidence_threshold not in _detector_cache:
        _detector_cache[confidence_threshold] = PersonDetector(confidence_threshold=confidence_threshold)
    return _detector_cache[confidence_threshold]


@celery_app.task(name="process_video_task", bind=True)
def process_video_task(
    self,
    input_path: str,
    zone: tuple,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    event_gap_seconds: float = DEFAULT_EVENT_GAP_SECONDS,
):
    """zone is (v1, v2, ..., vN): the vertices of the turnstile passage polygon."""
    detector = _get_detector(confidence_threshold)
    tracker = PersonTracker(detector)
    tailgate_detector = TailgateDetector(zone, event_gap_seconds=event_gap_seconds)

    # Throttled to a report roughly once per percentage point rather than
    # every frame: the filesystem result backend (config.py) overwrites one
    # plain file per update with no atomicity, so writing on every single
    # frame made it easy for a concurrent GET /jobs/{id} read to land
    # mid-write and see a corrupt half-old/half-new file (surfaces as a
    # kombu "Extra data" JSONDecodeError in services/job_service.py).
    _last_reported = -1.0

    def report_progress(fraction: float) -> None:
        nonlocal _last_reported
        if fraction - _last_reported >= 0.01 or fraction >= 1.0:
            _last_reported = fraction
            self.update_state(state="PROCESSING", meta={"progress": fraction})

    def save_violation_screenshot(frame, index):
        # Local disk stays the source of truth; the MinIO copy is a
        # best-effort mirror (no-op when MinIO isn't configured) so
        # GET /nvr/images/{date} can hand out direct image URLs.
        screenshot_path = violation_screenshot_path_for(self.request.id, index)
        cv2.imwrite(str(screenshot_path), frame)
        upload_violation_screenshot(self.request.id, index, screenshot_path)

    process_video_with_tailgate_detection(
        input_path,
        tracker,
        tailgate_detector,
        progress_callback=report_progress,
        on_violation=save_violation_screenshot,
    )
    return {
        "passage_count": len(tailgate_detector.events),
        "violation_count": len(tailgate_detector.violations),
        "violations": [
            {
                "start_time": event.start_time,
                "end_time": event.end_time,
                "person_count": event.person_count,
            }
            for event in tailgate_detector.violations
        ],
    }
