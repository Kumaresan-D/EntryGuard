"""Detects tailgating at a turnstile from CCTV alone (no eSSL access-log correlation yet).

The eSSL device authorizes one person per activation, but the physical gate
doesn't stop a second person from following through during that same cycle.
Without the access-log/API wired in yet, we can't check against the actual
authorized event - instead, we infer a "passage event" purely from timing:
distinct tracked people entering the turnstile zone within event_gap_seconds
of each other are assumed to be the same physical turnstile cycle. An event
with more than one distinct person is flagged as a possible tailgating
violation. Once the eSSL API is wired in, an event should instead be bounded
by the device's own authorization timestamps rather than this time-gap guess.
"""


class PassageEvent:
    def __init__(self, start_time):
        self.start_time = start_time
        self.end_time = start_time
        self.track_ids = []

    def add(self, track_id, time_seconds):
        if track_id not in self.track_ids:
            self.track_ids.append(track_id)
        self.end_time = time_seconds

    @property
    def person_count(self):
        return len(self.track_ids)

    @property
    def is_violation(self):
        return self.person_count > 1


def _point_in_polygon(point, vertices):
    """Ray-casting point-in-polygon test: works for any simple polygon (in
    any vertex order/orientation), not just a triangle."""
    x, y = point
    inside = False
    x1, y1 = vertices[-1]
    for x2, y2 in vertices:
        if (y1 > y) != (y2 > y):
            x_intersect = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_intersect:
                inside = not inside
        x1, y1 = x2, y2
    return inside


class TailgateDetector:
    def __init__(self, zone, event_gap_seconds):
        """zone is (v1, v2, ..., vN): the vertices of the turnstile passage
        polygon, in any order/orientation."""
        self.zone = zone
        self._vertices = zone
        self.event_gap_seconds = event_gap_seconds

        self.events = []
        self._current_event = None
        self._was_inside = {}
        self._registered_track_ids = set()

    def _is_inside(self, point):
        return _point_in_polygon(point, self._vertices)

    def update(self, tracked_detections, time_seconds):
        """tracked_detections: (x1, y1, x2, y2, confidence, track_id) tuples.
        time_seconds: this frame's timestamp within the video.
        """
        for x1, y1, x2, y2, _confidence, track_id in tracked_detections:
            point = ((x1 + x2) / 2, y2)  # bottom-center: approximates where the person is standing
            inside = self._is_inside(point)
            was_inside = self._was_inside.get(track_id, False)

            # Only a track's first zone entry counts as its passage moment -
            # ignores jitter if the same person flickers in/out near the edge.
            if inside and not was_inside and track_id not in self._registered_track_ids:
                self._registered_track_ids.add(track_id)
                self._register_entry(track_id, time_seconds)

            self._was_inside[track_id] = inside

    def _register_entry(self, track_id, time_seconds):
        if self._current_event is not None and time_seconds - self._current_event.end_time <= self.event_gap_seconds:
            self._current_event.add(track_id, time_seconds)
        else:
            if self._current_event is not None:
                self.events.append(self._current_event)
            self._current_event = PassageEvent(time_seconds)
            self._current_event.add(track_id, time_seconds)

    def finalize(self):
        """Call once after the whole video is processed to flush the last open event."""
        if self._current_event is not None:
            self.events.append(self._current_event)
            self._current_event = None

    @property
    def violations(self):
        return [event for event in self.events if event.is_violation]

    @property
    def live_passage_count(self):
        """Passages so far, including the still-open event (for a live overlay while processing)."""
        return len(self.events) + (1 if self._current_event is not None else 0)

    @property
    def live_violation_count(self):
        count = len(self.violations)
        if self._current_event is not None and self._current_event.is_violation:
            count += 1
        return count

    @property
    def current_event_is_violation(self):
        return self._current_event is not None and self._current_event.is_violation
