from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MetricsStore:
    """Small persistent metrics/event store for operational visibility."""

    def __init__(self, path: Path, max_events: int = 1000) -> None:
        self.path = path
        self.max_events = max_events
        self.lock = RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _empty(self) -> dict[str, Any]:
        return {
            "version": 1,
            "created_at": _now_iso(),
            "updated_at": None,
            "counters": {},
            "last": {},
            "events": [],
        }

    def read(self) -> dict[str, Any]:
        with self.lock:
            if not self.path.exists():
                return self._empty()
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    return self._empty()
                data.setdefault("version", 1)
                data.setdefault("counters", {})
                data.setdefault("last", {})
                data.setdefault("events", [])
                return data
            except Exception:
                return self._empty()

    def write(self, data: dict[str, Any]) -> None:
        with self.lock:
            data["updated_at"] = _now_iso()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(self.path)

    def event(self, name: str, *, ok: bool = True, detail: dict[str, Any] | None = None) -> dict[str, Any]:
        data = self.read()
        counters = data.setdefault("counters", {})
        counters[name] = int(counters.get(name, 0) or 0) + 1
        counters["events_total"] = int(counters.get("events_total", 0) or 0) + 1
        if ok:
            counters["ok_total"] = int(counters.get("ok_total", 0) or 0) + 1
        else:
            counters["error_total"] = int(counters.get("error_total", 0) or 0) + 1
        event = {"time": _now_iso(), "name": name, "ok": bool(ok), "detail": detail or {}}
        data.setdefault("events", []).append(event)
        if len(data["events"]) > self.max_events:
            del data["events"][: len(data["events"]) - self.max_events]
        data.setdefault("last", {})[name] = event
        self.write(data)
        return event

    def set_last(self, key: str, value: Any) -> None:
        data = self.read()
        data.setdefault("last", {})[key] = {"time": _now_iso(), "value": value}
        self.write(data)

    def get_last_value(self, key: str, default: Any = None) -> Any:
        item = self.read().get("last", {}).get(key)
        if isinstance(item, dict) and "value" in item:
            return item.get("value")
        return default

    def summary(self) -> dict[str, Any]:
        data = self.read()
        return {
            "path": str(self.path),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "counters": data.get("counters", {}),
            "last": data.get("last", {}),
            "events_tail": data.get("events", [])[-100:],
        }

    def events(self, limit: int = 100) -> dict[str, Any]:
        limit = max(1, min(int(limit), self.max_events))
        data = self.read()
        return {"events": data.get("events", [])[-limit:], "count": len(data.get("events", [])), "limit": limit}

    def reset(self) -> None:
        self.write(self._empty())
