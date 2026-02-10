"""Persistent store for jobs triggered through this MCP server.

Records are stored in a JSON file so they survive across server restarts.
The default location is ``~/.jenkins_mcp/triggered_jobs.json`` and can be
overridden with the ``JENKINS_MCP_STORE_PATH`` environment variable.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _default_store_path() -> Path:
    """Return the default path for the trigger store file."""
    custom = os.environ.get("JENKINS_MCP_STORE_PATH")
    if custom:
        return Path(custom)
    return Path.home() / ".jenkins_mcp" / "triggered_jobs.json"


class TriggerStore:
    """Thread-safe, file-backed store for triggered job records."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _default_store_path()
        self._lock = threading.Lock()
        self._ensure_dir()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_dir(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
            return []
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, records: list[dict[str, Any]]) -> None:
        self._path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def add(
        self,
        *,
        job_name: str,
        parameters: dict[str, Any] | None,
        queue_id: int,
        build_number: int | None,
    ) -> dict[str, Any]:
        """Add a new triggered-job record and return it."""
        record: dict[str, Any] = {
            "job_name": job_name,
            "parameters": parameters,
            "queue_id": queue_id,
            "build_number": build_number,
            "trigger_time": datetime.now(tz=timezone.utc).isoformat(),
            "status": "RUNNING" if build_number is not None else "QUEUED",
        }
        with self._lock:
            records = self._load()
            records.append(record)
            self._save(records)
        return record

    def list_all(self) -> list[dict[str, Any]]:
        """Return all records (newest first)."""
        with self._lock:
            records = self._load()
        return list(reversed(records))

    def update_record(
        self,
        queue_id: int,
        *,
        build_number: int | None = None,
        status: str | None = None,
    ) -> None:
        """Update an existing record identified by *queue_id*."""
        with self._lock:
            records = self._load()
            for rec in records:
                if rec.get("queue_id") == queue_id:
                    if build_number is not None:
                        rec["build_number"] = build_number
                    if status is not None:
                        rec["status"] = status
                    break
            self._save(records)

    def clear(self) -> None:
        """Remove all records."""
        with self._lock:
            self._save([])


# Module-level singleton (lazy); tests can replace via patching.
_store: TriggerStore | None = None


def get_store() -> TriggerStore:
    """Return the module-level singleton store instance."""
    global _store
    if _store is None:
        _store = TriggerStore()
    return _store
