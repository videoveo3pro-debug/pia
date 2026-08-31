from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def make_target_key(country: str | None = None, server: str | None = None, target: str | None = None) -> str:
    if target:
        return f"target:{target.strip().lower()}"
    if server:
        return f"server:{server.strip().lower()}"
    if country:
        return f"country:{country.strip().lower()}"
    return "target:quick-connect"


class IPUsageStore:
    """Persistent usage/reliability history for PIA CLI targets.

    Without .ovpn files, the API cannot choose the exact PIA exit IP before
    connecting. It records every verified IP and the actual server hostname from
    `pia status` when available. Future rotations can reject overused IPs and
    retry CLI connect until it finds a better/new IP or reaches the attempt limit.
    """

    def __init__(self, path: Path, max_events: int = 500) -> None:
        self.path = path
        self.max_events = max_events
        self.lock = RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> dict[str, Any]:
        with self.lock:
            if not self.path.exists():
                return self._empty()
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    return self._empty()
                data.setdefault("version", 3)
                data.setdefault("ips", {})
                data.setdefault("targets", {})
                data.setdefault("servers", {})
                data.setdefault("events", [])
                return data
            except Exception:
                return self._empty()

    def write(self, data: dict[str, Any]) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(self.path)

    def reset(self) -> None:
        self.write(self._empty())

    def summary(self) -> dict[str, Any]:
        data = self.read()
        ips = data.get("ips", {})
        targets = data.get("targets", {})
        servers = data.get("servers", {})
        sorted_ips = sorted(ips.items(), key=lambda item: (int(item[1].get("use_count", 0)), str(item[1].get("last_used_at", "")), item[0]))
        sorted_targets = sorted(targets.items(), key=lambda item: (bool(item[1].get("bad_target", False)), -float(item[1].get("success_rate", 0.0)), int(item[1].get("failure_count", 0)), item[0]))
        return {
            "path": str(self.path),
            "ip_count": len(ips),
            "target_count": len(targets),
            "server_count": len(servers),
            "least_used_ips": [
                {
                    "ip": ip,
                    "use_count": int(meta.get("use_count", 0)),
                    "last_used_at": meta.get("last_used_at"),
                    "countries": meta.get("countries", {}),
                    "targets": meta.get("targets", {}),
                    "servers": meta.get("servers", {}),
                }
                for ip, meta in sorted_ips[:50]
            ],
            "targets": [self._public_target_meta(key, meta) for key, meta in sorted_targets[:100]],
            "bad_targets": [self._public_target_meta(key, meta) for key, meta in sorted(targets.items()) if bool(meta.get("bad_target", False))],
            "servers": [
                {"server": key, **meta}
                for key, meta in sorted(servers.items(), key=lambda item: (-int(item[1].get("success_count", 0)), item[0]))[:100]
            ],
            "events_tail": data.get("events", [])[-50:],
        }


    def export_data(self) -> dict[str, Any]:
        return self.read()

    def import_data(self, payload: dict[str, Any], *, merge: bool = True) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        incoming = payload.get("data", payload)
        if not isinstance(incoming, dict):
            raise ValueError("data must be a JSON object")
        current = self.read() if merge else self._empty()
        for section in ["ips", "targets", "servers"]:
            current.setdefault(section, {})
            for key, value in incoming.get(section, {}).items():
                if isinstance(value, dict):
                    current[section][key] = value
        current.setdefault("events", [])
        events = incoming.get("events", [])
        if isinstance(events, list):
            current["events"].extend([e for e in events if isinstance(e, dict)])
            self._trim_events(current["events"])
        current["version"] = max(int(current.get("version", 3) or 3), int(incoming.get("version", 3) or 3))
        self.write(current)
        return self.summary()

    def clear_target(self, key: str) -> dict[str, Any]:
        data = self.read()
        removed = data.setdefault("targets", {}).pop(key, None)
        self.write(data)
        return {"ok": True, "removed": bool(removed), "target": key, "summary": self.summary()}

    def mark_target(self, key: str, *, bad: bool) -> dict[str, Any]:
        data = self.read()
        meta = self._ensure_target(data, key, _now_iso())
        meta["bad_target"] = bool(bad)
        if not bad:
            meta["cooldown_until"] = None
            meta["failure_streak"] = 0
        self.write(data)
        return self._public_target_meta(key, meta)

    def ip_use_count(self, ip: str | None) -> int:
        if not ip:
            return 0
        return int(self.read().get("ips", {}).get(ip, {}).get("use_count", 0) or 0)

    def least_ip_use_count(self) -> int:
        ips = self.read().get("ips", {})
        if not ips:
            return 0
        return min(int(meta.get("use_count", 0) or 0) for meta in ips.values())

    def order_targets(
        self,
        target_keys: list[str],
        *,
        randomize_ties: bool = True,
        cooldown_enabled: bool = True,
        cooldown_seconds: int = 900,
        avoid_bad: bool = True,
    ) -> list[str]:
        unique = list(dict.fromkeys([t for t in target_keys if t]))
        if not unique:
            return []
        data = self.read()
        targets = data.get("targets", {})

        def flags(key: str) -> dict[str, Any]:
            return self._candidate_flags(targets.get(key, {}), cooldown_enabled=cooldown_enabled, cooldown_seconds=cooldown_seconds)

        healthy = [key for key in unique if not flags(key)["cooldown_active"] and not (avoid_bad and flags(key)["bad_target"])]
        fallback = [key for key in unique if key not in healthy]
        pool = healthy + fallback

        def score(key: str) -> tuple[Any, ...]:
            meta = targets.get(key, {})
            cand = flags(key)
            cooldown_rank = 1 if cand["cooldown_active"] else 0
            bad_rank = 1 if cand["bad_target"] else 0
            last_ip = meta.get("last_ip")
            ip_use = self.ip_use_count(last_ip) if last_ip else 0
            unknown_rank = 0 if not last_ip else 1
            success_rate_penalty = 1.0 - float(meta.get("success_rate", 0.0) or 0.0)
            failure_streak = int(meta.get("failure_streak", 0) or 0)
            avg_connect = int(meta.get("avg_connect_time_ms", 0) or 0)
            tie = random.random() if randomize_ties else key
            return (cooldown_rank, bad_rank if avoid_bad else 0, ip_use, unknown_rank, success_rate_penalty, failure_streak, avg_connect, tie)

        return sorted(pool, key=score)

    def record_success(
        self,
        *,
        target_key: str,
        ip: str,
        country: str | None = None,
        server: str | None = None,
        actual_server: str | None = None,
        connect_time_ms: int | None = None,
    ) -> dict[str, Any]:
        data = self.read()
        now = _now_iso()
        ips = data.setdefault("ips", {})
        ip_meta = ips.setdefault(ip, {"use_count": 0, "first_used_at": now, "last_used_at": None, "countries": {}, "targets": {}, "servers": {}})
        ip_meta["use_count"] = int(ip_meta.get("use_count", 0)) + 1
        ip_meta["last_used_at"] = now
        if country:
            ip_meta.setdefault("countries", {})[country] = int(ip_meta.setdefault("countries", {}).get(country, 0)) + 1
        ip_meta.setdefault("targets", {})[target_key] = int(ip_meta.setdefault("targets", {}).get(target_key, 0)) + 1
        if actual_server:
            ip_meta.setdefault("servers", {})[actual_server] = int(ip_meta.setdefault("servers", {}).get(actual_server, 0)) + 1

        target_meta = self._ensure_target(data, target_key, now, country=country, server=server)
        if not target_meta.get("first_success_at"):
            target_meta["first_success_at"] = now
        target_meta["success_count"] = int(target_meta.get("success_count", 0)) + 1
        target_meta["attempt_count"] = int(target_meta.get("attempt_count", 0)) + 1
        target_meta["last_success_at"] = now
        target_meta["last_ip"] = ip
        target_meta["last_actual_server"] = actual_server
        target_meta["last_error"] = None
        target_meta["last_error_type"] = None
        target_meta["failure_streak"] = 0
        target_meta["cooldown_until"] = None
        target_meta["bad_target"] = False
        if connect_time_ms is not None:
            total_success = int(target_meta.get("success_count", 0))
            prev_avg = float(target_meta.get("avg_connect_time_ms", 0) or 0)
            target_meta["avg_connect_time_ms"] = int(((prev_avg * (total_success - 1)) + connect_time_ms) / total_success)
            target_meta["last_connect_time_ms"] = connect_time_ms
        self._recompute_rates(target_meta)

        if actual_server:
            server_meta = data.setdefault("servers", {}).setdefault(actual_server, {"success_count": 0, "last_ip": None, "last_seen_at": None, "countries": {}})
            server_meta["success_count"] = int(server_meta.get("success_count", 0)) + 1
            server_meta["last_ip"] = ip
            server_meta["last_seen_at"] = now
            if country:
                server_meta.setdefault("countries", {})[country] = int(server_meta.setdefault("countries", {}).get(country, 0)) + 1

        data.setdefault("events", []).append({
            "type": "success",
            "time": now,
            "target": target_key,
            "country": country,
            "server": server,
            "actual_server": actual_server,
            "ip": ip,
            "ip_use_count_after": ip_meta["use_count"],
            "connect_time_ms": connect_time_ms,
        })
        self._trim_events(data["events"])
        self.write(data)
        return {
            "ip": ip,
            "ip_use_count": int(ip_meta.get("use_count", 0)),
            "target_success_count": int(target_meta.get("success_count", 0)),
            "success_rate": float(target_meta.get("success_rate", 0.0)),
            "avg_connect_time_ms": target_meta.get("avg_connect_time_ms"),
            "actual_server": actual_server,
        }

    def record_failure(
        self,
        *,
        target_key: str,
        error: str | None = None,
        country: str | None = None,
        server: str | None = None,
        error_type: str | None = None,
        cooldown_enabled: bool = True,
        cooldown_seconds: int = 900,
        cooldown_threshold: int = 2,
        bad_failure_threshold: int = 4,
        bad_success_rate_threshold: float = 0.25,
    ) -> dict[str, Any]:
        data = self.read()
        now = _now_iso()
        meta = self._ensure_target(data, target_key, now, country=country, server=server)
        meta["failure_count"] = int(meta.get("failure_count", 0)) + 1
        meta["attempt_count"] = int(meta.get("attempt_count", 0)) + 1
        meta["failure_streak"] = int(meta.get("failure_streak", 0)) + 1
        meta["last_failure_at"] = now
        meta["last_error"] = (error or "")[-1200:]
        meta["last_error_type"] = error_type or self.classify_error(error or "")
        self._recompute_rates(meta)
        if cooldown_enabled and int(meta.get("failure_streak", 0)) >= cooldown_threshold:
            meta["cooldown_until"] = (_now() + timedelta(seconds=cooldown_seconds)).isoformat()
        if int(meta.get("failure_count", 0)) >= bad_failure_threshold and float(meta.get("success_rate", 0.0)) <= bad_success_rate_threshold:
            meta["bad_target"] = True

        event = {
            "type": "failure",
            "time": now,
            "target": target_key,
            "country": country,
            "server": server,
            "error_type": meta.get("last_error_type"),
            "error": (error or "")[-1200:],
            "failure_streak": meta.get("failure_streak"),
            "cooldown_until": meta.get("cooldown_until"),
            "bad_target": meta.get("bad_target", False),
        }
        data.setdefault("events", []).append(event)
        self._trim_events(data["events"])
        self.write(data)
        return self._public_target_meta(target_key, meta, cooldown_seconds=cooldown_seconds)

    @staticmethod
    def classify_error(error: str) -> str:
        text = (error or "").lower()
        mapping = [
            ("auth", ["not logged in", "login", "authentication", "invalid token", "token"]),
            ("timeout", ["timed out", "timeout", "deadline"]),
            ("network", ["network unreachable", "no route to host", "connection refused", "could not connect"]),
            ("daemon", ["daemon", "piad", "permission denied accessing /run/pia"]),
            ("country", ["country", "invalid", "not recognized", "not supported"]),
            ("ip_check", ["no working vpn ip", "no ip field", "socks"]),
        ]
        for label, needles in mapping:
            if any(needle in text for needle in needles):
                return label
        return "unknown"

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {"version": 3, "ips": {}, "targets": {}, "servers": {}, "events": []}

    def _ensure_target(self, data: dict[str, Any], key: str, now: str, *, country: str | None = None, server: str | None = None) -> dict[str, Any]:
        targets = data.setdefault("targets", {})
        meta = targets.setdefault(key, {
            "country": country,
            "server": server,
            "success_count": 0,
            "failure_count": 0,
            "attempt_count": 0,
            "success_rate": 0.0,
            "failure_streak": 0,
            "first_success_at": None,
            "last_success_at": None,
            "last_failure_at": None,
            "last_ip": None,
            "last_actual_server": None,
            "last_error_type": None,
            "last_error": None,
            "cooldown_until": None,
            "bad_target": False,
            "created_at": now,
        })
        meta["country"] = country
        meta["server"] = server
        meta.setdefault("attempt_count", int(meta.get("success_count", 0)) + int(meta.get("failure_count", 0)))
        meta.setdefault("failure_streak", 0)
        meta.setdefault("success_rate", 0.0)
        meta.setdefault("bad_target", False)
        return meta

    @staticmethod
    def _recompute_rates(meta: dict[str, Any]) -> None:
        success = int(meta.get("success_count", 0) or 0)
        failure = int(meta.get("failure_count", 0) or 0)
        attempts = max(int(meta.get("attempt_count", 0) or 0), success + failure)
        meta["attempt_count"] = attempts
        meta["success_rate"] = round(success / attempts, 4) if attempts else 0.0

    def _candidate_flags(self, meta: dict[str, Any], *, cooldown_enabled: bool, cooldown_seconds: int) -> dict[str, Any]:
        cooldown_until = _parse_iso(meta.get("cooldown_until"))
        active = bool(cooldown_enabled and cooldown_until and cooldown_until > _now())
        return {
            "cooldown_active": active,
            "cooldown_until": cooldown_until.isoformat() if cooldown_until else None,
            "cooldown_seconds": cooldown_seconds,
            "bad_target": bool(meta.get("bad_target", False)),
        }

    def _public_target_meta(self, key: str, meta: dict[str, Any], *, cooldown_seconds: int = 900) -> dict[str, Any]:
        flags = self._candidate_flags(meta, cooldown_enabled=True, cooldown_seconds=cooldown_seconds)
        return {
            "key": key,
            "country": meta.get("country"),
            "server": meta.get("server"),
            "last_ip": meta.get("last_ip"),
            "last_actual_server": meta.get("last_actual_server"),
            "success_count": int(meta.get("success_count", 0) or 0),
            "failure_count": int(meta.get("failure_count", 0) or 0),
            "attempt_count": int(meta.get("attempt_count", 0) or 0),
            "success_rate": float(meta.get("success_rate", 0.0) or 0.0),
            "failure_streak": int(meta.get("failure_streak", 0) or 0),
            "bad_target": bool(meta.get("bad_target", False)),
            "cooldown": {"active": flags["cooldown_active"], "until": flags["cooldown_until"]},
            "avg_connect_time_ms": meta.get("avg_connect_time_ms"),
            "last_connect_time_ms": meta.get("last_connect_time_ms"),
            "last_success_at": meta.get("last_success_at"),
            "last_failure_at": meta.get("last_failure_at"),
            "last_error_type": meta.get("last_error_type"),
            "last_error": meta.get("last_error"),
        }

    def _trim_events(self, events: list[dict[str, Any]]) -> None:
        if len(events) > self.max_events:
            del events[: len(events) - self.max_events]
