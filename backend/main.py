from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
