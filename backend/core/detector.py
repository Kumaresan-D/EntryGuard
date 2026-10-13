"""Person detection wrapper around an Ultralytics YOLO model."""

from ultralytics import YOLO

from backend.config import DEFAULT_CONFIDENCE_THRESHOLD, MODEL_PATH, PERSON_CLASS_ID


class PersonDetector:
    """Runs YOLO inference on a single frame and returns person detections."""

    def __init__(self, model_path: str = MODEL_PATH, confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD):
        self.model = YOLO(model_path)
        self.confidence_threshold = confidence_threshold

    def detect(self, frame):
        """Returns a list of (x1, y1, x2, y2, confidence) for detected people."""
        results = self.model(
            frame,
            classes=[PERSON_CLASS_ID],
            conf=self.confidence_threshold,
            verbose=False,
        )[0]

        detections = []
        for box in results.boxes:
            x1, y1, x2, y2 = box.xyxy[0].tolist()
            confidence = float(box.conf[0])
            detections.append((int(x1), int(y1), int(x2), int(y2), confidence))
        return detections
