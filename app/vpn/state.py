from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import RLock
from typing import Any


@dataclass
class DesiredState:
    enabled: bool = False
    country: str | None = None
    server: str | None = None
    target: str | None = None
    current_ip: str | None = None
    actual_server: str | None = None


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> DesiredState:
        with self.lock:
            if not self.path.exists():
                return DesiredState()
            try:
                data: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
                return DesiredState(
                    enabled=bool(data.get("enabled", False)),
                    country=data.get("country"),
                    server=data.get("server"),
                    target=data.get("target"),
                    current_ip=data.get("current_ip"),
                    actual_server=data.get("actual_server"),
                )
            except Exception:
                return DesiredState()

    def write(self, state: DesiredState) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
