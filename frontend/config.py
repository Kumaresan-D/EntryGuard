"""Frontend-only configuration - deliberately independent of backend/config.py
so the Streamlit app stays a pure HTTP client with no import-level coupling
to backend internals (model paths, Celery, NVR credentials, etc.).
"""

import os

# The FastAPI backend's base URL - override if it's running elsewhere.
API_BASE_URL = os.environ.get("ENTRYGUARD_API_URL", "http://127.0.0.1:8000")

DEFAULT_CONFIDENCE_THRESHOLD = 0.4
DEFAULT_EVENT_GAP_SECONDS = 3.0

# Must match backend.config.ZONE_POINT_COUNT - the number of points the zone
# picker below collects before a job can be submitted.
ZONE_POINT_COUNT = 4
