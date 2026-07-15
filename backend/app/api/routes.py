from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/health")
def health_check() -> dict:
    return {"status": "ok"}
