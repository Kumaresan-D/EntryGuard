"""Frame-by-frame video processing: read -> track -> detect tailgating -> screenshot on violation.

No output video is produced - the only visual artifact is the frame captured
by on_violation at the moment a passage event becomes a violation.
"""

import cv2

from backend.config import FRAME_SKIP
from backend.core.drawing import draw_tracked_detections, draw_turnstile_zone


def process_video_with_tailgate_detection(input_path, tracker, tailgate_detector, progress_callback=None, on_violation=None):
    """Tracks people through input_path and detects tailgating at the turnstile zone.

    tracker should be a fresh PersonTracker for this video. tailgate_detector
    is updated (and finalized) in place; read its .events/.violations after
    this returns.

    on_violation, if given, is called as on_violation(frame, index) the moment
    a passage event first becomes a violation (a 2nd distinct person entering
    the zone within the same event) - frame has the tracked boxes and zone
    overlay drawn on it (drawing only happens for this one frame per
    violation, not every frame, since there's no video to render), and index
    is that event's stable position within tailgate_detector.violations once
    it's eventually closed and appended there.

    Tracking/tailgate updates only run every FRAME_SKIP-th frame (config.py).

    progress_callback, if given, is called with a float in [0, 1] after each frame.
    """
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise IOError(f"Could not open video: {input_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    was_violation = False
    last_tracked = []
    frame_index = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            if frame_index % FRAME_SKIP == 0:
                last_tracked = tracker.track(frame)
                tailgate_detector.update(last_tracked, frame_index / fps)

            is_violation = tailgate_detector.current_event_is_violation
            if on_violation and is_violation and not was_violation:
                draw_tracked_detections(frame, last_tracked)
                draw_turnstile_zone(
                    frame,
                    tailgate_detector.zone,
                    tailgate_detector.live_passage_count,
                    tailgate_detector.live_violation_count,
                    is_violation,
                )
                on_violation(frame.copy(), len(tailgate_detector.violations))
            was_violation = is_violation

            frame_index += 1
            if progress_callback and total_frames:
                progress_callback(min(frame_index / total_frames, 1.0))
    finally:
        cap.release()

    tailgate_detector.finalize()
