from __future__ import annotations
import json
from pathlib import Path


class StateStore:
    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._data: dict[str, str] = {}
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.replace(self._path)  # atomic on POSIX

    def set(self, key: str, state: str) -> None:
        self._data[key] = state
        self._save()

    def should_notify(self, key: str, state: str) -> bool:
        changed = self._data.get(key) != state
        self._data[key] = state
        self._save()
        return changed
