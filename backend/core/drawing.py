"""Drawing helpers for rendering tracked detections and the turnstile zone onto frames."""

import cv2
import numpy as np

from backend.config import BOX_COLOR, TEXT_COLOR

ZONE_COLOR = (0, 165, 255)
ZONE_VIOLATION_COLOR = (0, 0, 255)
COUNTS_TEXT_COLOR = (255, 255, 255)
COUNTS_BG_COLOR = (0, 0, 0)


def _draw_box_with_label(frame, x1, y1, x2, y2, label):
    cv2.rectangle(frame, (x1, y1), (x2, y2), BOX_COLOR, 2)

    (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    label_top = max(y1 - text_h - 6, 0)
    cv2.rectangle(frame, (x1, label_top), (x1 + text_w + 4, label_top + text_h + 6), BOX_COLOR, -1)
    cv2.putText(frame, label, (x1 + 2, label_top + text_h + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.5, TEXT_COLOR, 1)


def draw_tracked_detections(frame, tracked_detections):
    """Draws bounding boxes labeled with track ID and confidence in place."""
    for x1, y1, x2, y2, confidence, track_id in tracked_detections:
        _draw_box_with_label(frame, x1, y1, x2, y2, f"#{track_id} {confidence:.2f}")

    return frame


def draw_turnstile_zone(frame, zone, passage_count, violation_count, current_event_is_violation):
    """Draws the turnstile passage zone (a polygon over its vertices) and a
    running passages/violations overlay in place.

    current_event_is_violation highlights the zone in red while more than
    one person is already registered in the still-open passage event.
    """
    color = ZONE_VIOLATION_COLOR if current_event_is_violation else ZONE_COLOR
    polygon = np.array([(int(x), int(y)) for x, y in zone], dtype=np.int32)
    cv2.polylines(frame, [polygon], isClosed=True, color=color, thickness=2)

    label = f"Passages: {passage_count}  Violations: {violation_count}"
    (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
    cv2.rectangle(frame, (10, 10), (10 + text_w + 12, 10 + text_h + 16), COUNTS_BG_COLOR, -1)
    cv2.putText(frame, label, (16, 10 + text_h + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.7, COUNTS_TEXT_COLOR, 2)

    return frame
