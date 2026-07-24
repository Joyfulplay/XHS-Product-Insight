"""File-based persistence for backend integration results."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class PersistenceService:
    """Persist processed job results as JSON files.

    The in-memory JobStore is still used for fast polling, while this service
    keeps completed outputs available after the Python process exits.
    """

    def __init__(self, output_dir: str | Path = "data/processed/collection_results") -> None:
        self.output_dir = Path(output_dir)

    def save(self, key: str, payload: dict[str, Any]) -> str:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{self._safe_key(key)}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def load(self, key: str) -> dict[str, Any] | None:
        path = self.output_dir / f"{self._safe_key(key)}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _safe_key(self, key: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]", "_", key).strip("._") or "result"
