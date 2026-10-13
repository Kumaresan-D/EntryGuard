"""Streamlit frontend: upload turnstile CCTV footage, submit it to the FastAPI backend, show results.

This process runs no detection itself - it's a client of the backend
(POST /jobs, GET /jobs/{id}, GET /jobs/{id}/violations/{index}/screenshot),
the same one usable directly via curl/Swagger.
"""

import tempfile
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
import requests
import streamlit as st
from streamlit_image_coordinates import streamlit_image_coordinates

from config import API_BASE_URL, DEFAULT_CONFIDENCE_THRESHOLD, DEFAULT_EVENT_GAP_SECONDS, ZONE_POINT_COUNT

TEMP_DIR = Path(tempfile.gettempdir())
PREVIEW_MAX_WIDTH = 800
ZONE_PREVIEW_COLOR = (0, 165, 255)
POLL_INTERVAL_SECONDS = 1
UPLOAD_TIMEOUT_SECONDS = 600  # generous enough for uploads up to the 2 GB cap

if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex


def read_first_frame(video_path):
    cap = cv2.VideoCapture(str(video_path))
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None


def run_job(uploaded_file, confidence_threshold, zone, event_gap_seconds):
    """Uploads to the backend, polls until done, and returns the final job dict."""
    params = {
        "confidence_threshold": confidence_threshold,
        "event_gap_seconds": event_gap_seconds,
        "zone": ",".join(f"{coord}" for point in zone for coord in point),
    }

    with st.spinner("Uploading to detection API..."):
        response = requests.post(
            f"{API_BASE_URL}/jobs",
            params=params,
            files={"file": (uploaded_file.name, uploaded_file.getvalue(), "application/octet-stream")},
            timeout=UPLOAD_TIMEOUT_SECONDS,
        )
    response.raise_for_status()
    job_id = response.json()["job_id"]

    progress_bar = st.progress(0.0)
    with st.spinner("Processing..."):
        while True:
            status_response = requests.get(f"{API_BASE_URL}/jobs/{job_id}", timeout=10)
            status_response.raise_for_status()
            job = status_response.json()

            if job["status"] == "PROCESSING" and job.get("progress") is not None:
                progress_bar.progress(job["progress"])
            elif job["status"] in ("SUCCESS", "FAILURE"):
                break

            time.sleep(POLL_INTERVAL_SECONDS)

    progress_bar.progress(1.0)
    return job


st.set_page_config(page_title="Turnstile Tailgate Detection POC", layout="centered")
st.title("Turnstile Tailgate Detection POC")
st.caption(
    "Upload CCTV footage of the turnstile. Mark the passage zone to detect when more than one "
    "person passes through in a single turnstile activation (CCTV-only for now, no eSSL access-log correlation yet)."
)

confidence_threshold = st.slider("Confidence threshold", 0.1, 0.9, DEFAULT_CONFIDENCE_THRESHOLD, 0.05)
uploaded_file = st.file_uploader("Upload video", type=["mp4", "avi", "mov", "mkv"])

if uploaded_file is not None:
    suffix = Path(uploaded_file.name).suffix or ".mp4"
    preview_input_path = TEMP_DIR / f"preview_{st.session_state.session_id}{suffix}"
    preview_input_path.write_bytes(uploaded_file.getbuffer())

    st.subheader("Original video")
    st.video(uploaded_file.getvalue())

    st.subheader("Turnstile passage zone")
    st.caption(f"Click {ZONE_POINT_COUNT} points on the frame to place the corners of the turnstile passage zone, in any order/orientation.")

    frame = read_first_frame(preview_input_path)
    zone_points = st.session_state.get("zone_points", [])
    if frame is None:
        st.warning("Could not read a preview frame from this video.")
    else:
        frame_h, frame_w = frame.shape[:2]
        scale = min(1.0, PREVIEW_MAX_WIDTH / frame_w)
        preview = cv2.resize(frame, (int(frame_w * scale), int(frame_h * scale))) if scale < 1.0 else frame.copy()

        scaled_points = [(int(x * scale), int(y * scale)) for x, y in zone_points]
        for point in scaled_points:
            cv2.circle(preview, point, 5, ZONE_PREVIEW_COLOR, -1)
        if len(scaled_points) >= 2:
            polygon = np.array(scaled_points, dtype=np.int32)
            cv2.polylines(preview, [polygon], isClosed=len(scaled_points) == ZONE_POINT_COUNT, color=ZONE_PREVIEW_COLOR, thickness=2)

        preview_rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
        coords = streamlit_image_coordinates(preview_rgb, key="zone_picker")

        if coords is not None and coords != st.session_state.get("_last_zone_click") and len(zone_points) < ZONE_POINT_COUNT:
            st.session_state._last_zone_click = coords
            zone_points = zone_points + [(coords["x"] / scale, coords["y"] / scale)]
            st.session_state.zone_points = zone_points
            st.rerun()

        if zone_points:
            st.caption("Zone points: " + ", ".join(f"({x:.0f}, {y:.0f})" for x, y in zone_points))
            if st.button("Clear zone"):
                st.session_state.zone_points = []
                st.session_state.pop("_last_zone_click", None)
                st.rerun()

    zone = tuple(zone_points) if len(zone_points) == ZONE_POINT_COUNT else None

    if zone is None:
        st.info(f"Place all {ZONE_POINT_COUNT} zone points above to enable detection.")
    else:
        event_gap_seconds = st.slider(
            "Passage event window (seconds)",
            0.5,
            8.0,
            DEFAULT_EVENT_GAP_SECONDS,
            0.5,
            help="People entering the zone within this many seconds of each other count as the same turnstile cycle.",
        )

        if st.button("Run detection"):
            try:
                job = run_job(uploaded_file, confidence_threshold, zone, event_gap_seconds)
            except requests.exceptions.ConnectionError:
                st.error(f"Could not reach the detection API at {API_BASE_URL} - is it running?")
                st.stop()
            except requests.exceptions.RequestException as exc:
                st.error(f"Detection API request failed: {exc}")
                st.stop()

            if job["status"] == "FAILURE":
                st.error(f"Detection failed: {job.get('error')}")
                st.stop()

            st.success("Done.")

            count_col1, count_col2 = st.columns(2)
            count_col1.metric("Passages", job["passage_count"])
            count_col2.metric("Tailgating violations", job["violation_count"])

            if job["violations"]:
                st.warning("Possible tailgating detected:")
                for index, violation in enumerate(job["violations"]):
                    minutes, seconds = divmod(violation["start_time"], 60)
                    st.write(
                        f"- Potential multiple-person entry detected at {int(minutes):02d}:{seconds:05.2f} "
                        f"({violation['person_count']} people in one passage)"
                    )
                    screenshot_response = requests.get(
                        f"{API_BASE_URL}/jobs/{job['job_id']}/violations/{index}/screenshot", timeout=10
                    )
                    if screenshot_response.ok:
                        st.image(screenshot_response.content)
