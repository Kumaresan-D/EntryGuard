"""One-time setup: export the YOLO model to OpenVINO format for faster CPU inference.

Run once after cloning: venv\\Scripts\\python -m scripts.export_model
config.py automatically prefers the exported model once it exists.
"""

from ultralytics import YOLO

from backend.config import BASE_MODEL_PATH

if __name__ == "__main__":
    model = YOLO(BASE_MODEL_PATH)
    model.export(format="openvino")
