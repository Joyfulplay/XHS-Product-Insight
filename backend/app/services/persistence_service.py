class PersistenceService:
    """Sample service for storing processed results permanently."""

    def save(self, key: str, payload: dict) -> str:
        return f"saved::{key}::{payload.get('summary', '')}"
