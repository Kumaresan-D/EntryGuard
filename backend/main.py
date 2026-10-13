"""FastAPI entry point: mounts routers, ensures storage dirs exist.

Run via: venv\\Scripts\\python -m uvicorn backend.main:app --reload
"""

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from backend.routes.jobs import router as jobs_router
from backend.routes.nvr import router as nvr_router
from backend.storage import ensure_storage_dirs

app = FastAPI(title="EntryGuard Person Detection API")

ensure_storage_dirs()
app.include_router(jobs_router)
app.include_router(nvr_router)


@app.get("/", include_in_schema=False)
def root():
    """Swagger is the front door: run.bat's ngrok tunnel publishes this API
    (port 8000, not the Streamlit UI on 8501), so opening the tunnel's bare
    URL should land on the interactive docs rather than a bare 404."""
    return RedirectResponse("/docs")
