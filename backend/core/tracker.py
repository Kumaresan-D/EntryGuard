"""Adds multi-frame identity tracking on top of a PersonDetector's YOLO model.

Uses Ultralytics' bundled ByteTrack so the same person keeps the same ID
across frames, which line-crossing counting depends on.
"""

from backend.config import PERSON_CLASS_ID


class PersonTracker:
    """Wraps a PersonDetector's model with tracking, scoped to a single video.

    Create a fresh instance per video: the first call to track() starts new
    ByteTrack state (persist=False), and every call after that continues it
    (persist=True), so IDs don't leak in from a previous video processed by
    the same underlying model.
    """

    def __init__(self, detector):
        self.detector = detector
        self._started = False

    def track(self, frame):
        """Returns a list of (x1, y1, x2, y2, confidence, track_id) for tracked people."""
        results = self.detector.model.track(
            frame,
            classes=[PERSON_CLASS_ID],
            conf=self.detector.confidence_threshold,
            persist=self._started,
            tracker="bytetrack.yaml",
            verbose=False,
        )[0]
        self._started = True

        boxes = results.boxes
        if boxes.id is None:
            return []

        tracked = []
        for box, track_id in zip(boxes, boxes.id):
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            confidence = float(box.conf[0])
            tracked.append((int(x1), int(y1), int(x2), int(y2), confidence, int(track_id)))
        return tracked
