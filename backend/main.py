import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def load_local_env(path: Path) -> None:
    """Load ``KEY=VALUE`` entries from *path* without overriding shell variables."""
    if not path.is_file():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        if entry.startswith("export "):
            entry = entry[7:].lstrip()
        if "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


load_local_env(Path(__file__).resolve().parents[1] / ".env")

from app.api.xhs_connector import router as xhs_connector_router

app = FastAPI(title="XHS Product Insight API")

# The connector does not use browser credentials, so extension origins can
# access its local task API without exposing a credentialed cross-origin flow.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(xhs_connector_router)


@app.get("/")
def read_root() -> dict:
    return {
        "project": "XHS-Product-Insight",
        "status": "initialized",
        "message": "Backend API entry point is ready.",
    }


if __name__ == "__main__":
    import uvicorn

    # The reload subprocess imports ``main:app``.  Anchor its import path to
    # this file so `python backend/main.py` also works from the project root.
    os.chdir(Path(__file__).resolve().parent)
    uvicorn.run(
        "main:app",
        host=os.getenv("UVICORN_HOST", "127.0.0.1"),
        port=int(os.getenv("UVICORN_PORT", "8000")),
        # Keep direct `python backend/main.py` starts consistent with the
        # development launcher: source changes restart the local API.
        reload=True,
        reload_dirs=[str(Path(__file__).resolve().parent)],
    )
