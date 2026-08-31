from __future__ import annotations

import json
import logging
import os
import random
import re
import socket
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import quote as url_quote
from pathlib import Path
from threading import RLock
from typing import Any

import requests

from app.core.config import Settings


logger = logging.getLogger(__name__)


@dataclass
class ExecResult:
    exit_code: int
    output: str


@dataclass
class ExpressStatus:
    connected: bool
    raw: str
    country: str | None = None
    city: str | None = None
    server: str | None = None
    hostname: str | None = None
    technology: str | None = None
    protocol: str | None = None
    uptime: str | None = None
    uptime_seconds: int | None = None

    @property
    def actual_server(self) -> str | None:
        return self.hostname or self.server


@dataclass(frozen=True)
class WorkerNode:
    id: str
    host: str
    control_port: int
    socks_port: int
    haproxy_server: str
    country_hint: str = ""
    container_name: str = ""
    token_slot: int = 1

    @property
    def control_url(self) -> str:
        return f"http://{self.host}:{self.control_port}"


class VPNManager:
    """Multi-container PIA SOCKS5 pool manager.

    Refactor target:
    - External apps keep using one stable SOCKS5 gateway (HAProxy).
    - Four PIA worker containers can hold different public IPs.
    - Rotate is per-worker and uses drain/disable before reconnect.
    - Request/connection *new* traffic fails over to READY workers quickly.
    """

    def __init__(self, settings: Settings) -> None:
        settings.validate_required()
        self.settings = settings
        self.nodes = self._load_workers()
        self._locks: dict[str, RLock] = {node.id: RLock() for node in self.nodes}
        self._last_rotation_at: dict[str, float] = {}
        self._node_status_cache: dict[str, dict[str, Any]] = {}
        self._node_status_cache_at: dict[str, float] = {}
        self._fail_counts: dict[str, int] = {node.id: 0 for node in self.nodes}
        self._recovery_counts: dict[str, int] = {node.id: 0 for node in self.nodes}
        self._last_recovery_at: dict[str, float] = {}
        self._last_recovery_result: dict[str, dict[str, Any]] = {}
        self._recovery_executor = ThreadPoolExecutor(max_workers=max(1, int(settings.worker_recovery_max_parallel)), thread_name_prefix="worker-recovery")
        self._recovery_lock = RLock()
        self._recovery_futures: dict[str, Future[dict[str, Any]]] = {}
        self._next_auto_rotate_at: dict[str, float] = {}
        self._auto_rotate_executor = ThreadPoolExecutor(max_workers=max(1, int(settings.auto_rotate_max_parallel)), thread_name_prefix="auto-rotate")
        self._auto_rotate_lock = RLock()
        self._auto_rotate_futures: dict[str, Future[dict[str, Any]]] = {}
        self._last_auto_rotate_result: dict[str, Any] | None = None
        self._rotation_counts: dict[str, int] = {node.id: 0 for node in self.nodes}
        self._country_target_stats: dict[str, dict[str, Any]] = {}
        self._server_target_stats: dict[str, dict[str, Any]] = {}
        self._ready_success_streaks: dict[str, int] = {node.id: 0 for node in self.nodes}
        self._ready_failure_streaks: dict[str, int] = {node.id: 0 for node in self.nodes}
        self._ready_state: dict[str, bool] = {node.id: False for node in self.nodes}
        self._last_verified_ip: dict[str, str] = {}
        self._last_verified_at: dict[str, float] = {}
        self._active_gateway_node_id: str | None = None
        self._session_bindings_path = settings.credentials_container_path / "session_bindings.json"
        self._sessions_lock = RLock()
        now = time.time()
        for node in self.nodes:
            self._schedule_next_auto_rotate(node.id, now=now)

    def _runtime_mode(self) -> int:
        try:
            data = json.loads(self.settings.runtime_mode_path.read_text(encoding="utf-8"))
            value = int(data.get("worker_count") or data.get("mode") or self.settings.worker_count)
        except Exception:
            value = int(self.settings.worker_count)
        max_allowed = int(self.settings.max_worker_count)
        if value >= max_allowed:
            return max_allowed
        if value >= 8:
            return value
        return min(8, max_allowed)

    def _set_runtime_mode_file(self, worker_count: int) -> None:
        requested = int(worker_count)
        max_allowed = int(self.settings.max_worker_count)
        if requested >= max_allowed:
            mode = max_allowed
        elif requested >= 8:
            mode = requested
        else:
            mode = min(8, max_allowed)
        self.settings.runtime_mode_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.runtime_mode_path.write_text(json.dumps({"worker_count": mode, "updated_at": int(time.time())}, indent=2), encoding="utf-8")
        self._relax_runtime_file_permissions(self.settings.runtime_mode_path, mode=0o664)

    def _active_nodes(self) -> list[WorkerNode]:
        limit = self._runtime_mode()
        return self.nodes[:limit]

    def _inactive_nodes(self) -> list[WorkerNode]:
        active_ids = {node.id for node in self._active_nodes()}
        return [node for node in self.nodes if node.id not in active_ids]

    def _is_active_node(self, node: WorkerNode) -> bool:
        return node.id in {item.id for item in self._active_nodes()}

    def _effective_min_ready_workers(self) -> int:
        configured = max(1, int(self.settings.min_ready_workers))
        active_count = len(self._active_nodes())
        return min(configured, max(1, active_count - 1))

    def _auto_rotate_ready_floor(self, active_count: int | None = None) -> int:
        configured = max(1, int(self.settings.auto_rotate_min_ready_workers))
        if active_count is None:
            active_count = len(self._active_nodes())
        # A rotate needs at least one worker to take out of service.
        return min(configured, max(1, int(active_count) - 1))

    # ---------- Public API used by existing routes ----------
    def status(self, *, refresh: bool = False) -> dict[str, Any]:
        nodes = self.nodes_status(refresh=refresh)
        active_node_ids = {node.id for node in self._active_nodes()}
        active_statuses = [n for n in nodes if n.get("active")]
        connected_nodes = [n for n in active_statuses if n.get("connected")]
        ready_nodes = [n for n in active_statuses if n.get("ready")]
        gateway_active_nodes = [n for n in active_statuses if n.get("gateway_enabled")]
        active_node = gateway_active_nodes[0] if gateway_active_nodes else None
        active_worker_id = active_node.get("id") if active_node else self._active_gateway_node_id
        gateway_ip = self._gateway_current_ip() if refresh and ready_nodes else self._cached_gateway_ip(ready_nodes)
        primary = active_node or (ready_nodes[0] if ready_nodes else (connected_nodes[0] if connected_nodes else (active_statuses[0] if active_statuses else {})))
        any_logged = any(bool(n.get("logged_in")) for n in active_statuses)
        any_connected = bool(connected_nodes) and bool(gateway_ip or primary.get("current_ip"))
        actual_ip = gateway_ip or primary.get("current_ip")
        mode = self._runtime_mode()
        min_ready = self._effective_min_ready_workers()
        return {
            "mode": "multi_worker_gateway",
            "worker_mode": {
                "worker_count": mode,
                "max_worker_count": min(len(self.nodes), self.settings.max_worker_count),
                "active_worker_ids": sorted(active_node_ids, key=lambda item: int(re.sub(r"\D", "", item) or 0)),
                "token_slots": self._required_token_slots(),
                "tokens_required": len(self._required_token_slots()),
                "min_ready_workers": min_ready,
                "ready_policy_ok": len(ready_nodes) >= min_ready,
            },
            "connected": any_connected,
            "country": primary.get("country"),
            "server": primary.get("server"),
            "actual_server": primary.get("actual_server"),
            "current_ip": actual_ip,
            "proxy": self._public_proxy(mask=self.settings.mask_proxy_password_in_status),
            "proxies": {"socks5": self._public_proxy(mask=self.settings.mask_proxy_password_in_status)},
            "container": {
                "name": "proxy-gateway",
                "exists": True,
                "running": len(ready_nodes) > 0,
                "status": f"{len(ready_nodes)}/{len(active_statuses)} active workers ready",
            },
            "pia": {
                "logged_in": any_logged,
                "connected": bool(connected_nodes),
                "country": primary.get("country"),
                "city": primary.get("city"),
                "server": primary.get("server"),
                "hostname": primary.get("hostname"),
                "technology": primary.get("technology"),
                "protocol": primary.get("protocol"),
            },
            "gateway": {
                "host": self.settings.proxy_host,
                "port": self.settings.proxy_port,
                "haproxy_socket": str(self.settings.haproxy_runtime_socket),
                "active_worker": active_worker_id,
                "active_workers": [n.get("id") for n in gateway_active_nodes],
                "ready_workers": len(ready_nodes),
                "total_workers": len(active_statuses),
                "configured_workers": len(nodes),
                "min_ready_workers": min_ready,
                "target_failover_seconds": self.settings.gateway_target_failover_seconds,
            },
            "auth": self._auth_summary(active_statuses),
            "nodes": nodes,
            "selection_strategy": "gateway_multi_active_ready_pool",
        }

    def runtime_mode(self) -> dict[str, Any]:
        mode = self._runtime_mode()
        return {
            "ok": True,
            "worker_count": mode,
            "max_worker_count": min(len(self.nodes), self.settings.max_worker_count),
            "active_worker_ids": [node.id for node in self._active_nodes()],
            "token_slots": self._required_token_slots(),
            "tokens_required": len(self._required_token_slots()),
            "min_ready_workers": self._effective_min_ready_workers(),
            "stored_tokens": {str(slot): bool(self._read_stored_token(slot=slot) or self._env_token_for_slot(slot)) for slot in self._required_token_slots()},
        }

    def set_runtime_mode(self, worker_count: int) -> dict[str, Any]:
        requested = int(worker_count)
        max_allowed = int(self.settings.max_worker_count)
        if requested >= max_allowed:
            mode = max_allowed
        elif requested >= 8:
            mode = requested
        else:
            mode = min(8, max_allowed)
        self._set_runtime_mode_file(mode)
        docker_actions = []
        for node in self._inactive_nodes():
            self._disable_node(node, reason="mode_inactive")
            docker_actions.append({"node_id": node.id, "action": "stop_inactive", **self._docker_stop_container(node)})
        for node in self._active_nodes():
            docker_actions.append({"node_id": node.id, "action": "start_active", **self._docker_start_container(node)})
        return {"ok": True, "worker_count": mode, "min_ready_workers": self._effective_min_ready_workers(), "docker_actions": docker_actions, "overview": self.runtime_mode()}

    def token_status(self, *, refresh: bool = False) -> dict[str, Any]:
        nodes = self.nodes_status(refresh=refresh)
        return {"ok": True, **self._auth_summary([n for n in nodes if n.get("active")])}

    def update_tokens(self, *, token_1: str | None = None, token_2: str | None = None, persist: bool = True, apply: bool = True) -> dict[str, Any]:
        updates: dict[int, str] = {}
        if token_1 is not None and token_1.strip():
            updates[1] = token_1.strip()
        if token_2 is not None and token_2.strip():
            updates[2] = token_2.strip()
        if not updates:
            raise ValueError("At least one token is required.")
        if persist and self.settings.pia_token_storage_enabled:
            for slot, token in updates.items():
                self._write_stored_token(token, slot=slot)
        results: list[dict[str, Any]] = []
        if apply:
            for slot, token in updates.items():
                results.extend(self._login_slot(slot, token))
        recover = None
        if apply:
            nodes = self.nodes_status(refresh=True)
            down_nodes = [n for n in nodes if n.get("active") and not n.get("ready")]
            recover = {"ok": True, "mode": "background_recovery", "started": self._start_background_recoveries(down_nodes)}
        token_summary = self.token_status(refresh=False)
        apply_ok = all(item.get("ok") for item in results) if results else True
        return {
            **token_summary,
            "ok": apply_ok,
            "persisted_slots": sorted(updates.keys()) if persist else [],
            "applied_slots": sorted(updates.keys()) if apply else [],
            "nodes": results,
            "recover": recover,
        }

    def diagnostics(self) -> dict[str, Any]:
        nodes = self.nodes_status(refresh=False)
        haproxy = self._haproxy_command("show stat")
        checks = {
            "gateway_proxy": {
                "ok": bool(self._tcp_connect("proxy-gateway", self.settings.socks5_port, timeout=2) or self._tcp_connect("127.0.0.1", self.settings.proxy_port, timeout=2)),
                "public_proxy": self._public_proxy(mask=True),
                "haproxy_socket": str(self.settings.haproxy_runtime_socket),
            },
            "haproxy_runtime": {
                "ok": haproxy.get("ok", False),
                "error": haproxy.get("error"),
            },
            "workers": {
                "ok": any(n.get("ready") for n in nodes),
                "ready": [n["id"] for n in nodes if n.get("ready")],
                "down": [n["id"] for n in nodes if not n.get("ready")],
                "nodes": nodes,
            },
            "rotate_policy": {
                "ok": True,
                "strategy": "switch/drain worker before rotate",
                "auto_rotate_enabled": self.settings.auto_rotate_enabled,
                "auto_rotate_max_parallel": self.settings.auto_rotate_max_parallel,
                "auto_rotate_max_parallel_per_token": self.settings.auto_rotate_max_parallel_per_token,
                "auto_rotate_target_attempts": self.settings.auto_rotate_target_attempts,
                "auto_rotate_interval_seconds": [
                    self.settings.auto_rotate_interval_min_seconds,
                    self.settings.auto_rotate_interval_max_seconds,
                ],
                "auto_rotate_in_progress": self._auto_rotate_running_ids(),
                "last_auto_rotate_result": self._last_auto_rotate_result,
                "min_ready_workers": self._effective_min_ready_workers(),
                "auto_rotate_min_ready_workers": self._auto_rotate_ready_floor(len([n for n in nodes if n.get("active")])),
                "auto_rotate_pause_ready_threshold": self.settings.auto_rotate_pause_ready_threshold,
                "auto_rotate_max_uptime_seconds": self.settings.auto_rotate_max_uptime_seconds,
                "connect_timeout_seconds": self.settings.connect_timeout_seconds,
                "ip_check_timeout_seconds": self.settings.ip_check_timeout_seconds,
            },
            "worker_recovery": {
                "ok": True,
                "enabled": self.settings.worker_recovery_enabled,
                "auto_reconnect": self.settings.auto_reconnect,
                "connect_after_failures": self.settings.worker_recovery_connect_after_failures,
                "restart_after_failures": self.settings.worker_recovery_restart_after_failures,
                "docker_restart_after_failures": self.settings.worker_recovery_docker_restart_after_failures,
                "cooldown_seconds": self.settings.worker_recovery_cooldown_seconds,
                "connect_max_attempts": self.settings.worker_recovery_connect_max_attempts,
                "docker_recovery_enabled": self.settings.docker_recovery_enabled,
                "docker_socket_path": str(self.settings.docker_socket_path),
                "fail_counts": dict(self._fail_counts),
                "rotation_counts": dict(self._rotation_counts),
                "recovery_in_progress": self._recovery_running_ids(),
                "last_recovery": dict(self._last_recovery_result),
                "country_target_stats": self._country_target_snapshot(),
                "server_target_stats": self._server_target_snapshot(),
                "ready_hysteresis": {
                    "success_threshold": self.settings.ready_success_threshold,
                    "failure_threshold": self.settings.ready_failure_threshold,
                    "verified_grace_seconds": self.settings.ready_verified_grace_seconds,
                    "proxy_failure_fail_fast": self.settings.ready_proxy_failure_fail_fast,
                    "state": dict(self._ready_state),
                    "success_streaks": dict(self._ready_success_streaks),
                    "failure_streaks": dict(self._ready_failure_streaks),
                },
            },
        }
        return {"ok": all(c.get("ok", True) for c in checks.values()), "checks": checks}

    def nodes_status(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        enabled = self._haproxy_enabled_servers()
        if not refresh:
            return [self._decorate_cached_node_status(node, enabled) for node in self.nodes]

        result_by_id: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=max(1, len(self.nodes))) as pool:
            future_map = {pool.submit(self.node_status, node.id): node for node in self.nodes}
            for future in as_completed(future_map):
                node = future_map[future]
                try:
                    status = future.result()
                except Exception as exc:
                    status = {
                        "id": node.id,
                        "host": node.host,
                        "control_port": node.control_port,
                        "socks_port": node.socks_port,
                        "haproxy_server": node.haproxy_server,
                        "country_hint": node.country_hint,
                        "container_name": node.container_name,
                        "token_slot": node.token_slot,
                        "ready": False,
                        "service_ready": False,
                        "runtime_ok": False,
                        "runtime_error": str(exc),
                        "connected": False,
                        "verified": False,
                        "current_ip": None,
                    }
                status["gateway_enabled"] = enabled.get(node.haproxy_server)
                status["active"] = self._is_active_node(node)
                status["fail_count"] = self._fail_counts.get(node.id, 0)
                status["recovery_count"] = self._recovery_counts.get(node.id, 0)
                status["last_recovery_at"] = self._last_recovery_at.get(node.id)
                status["last_recovery"] = self._last_recovery_result.get(node.id)
                status["recovery_in_progress"] = node.id in self._recovery_futures
                status["rotation_count"] = self._rotation_counts.get(node.id, 0)
                status["next_auto_rotate_at"] = self._next_auto_rotate_at.get(node.id)
                status["auto_rotate_in_progress"] = node.id in self._auto_rotate_futures
                self._node_status_cache[node.id] = status
                self._node_status_cache_at[node.id] = time.time()
                result_by_id[node.id] = status
        return [result_by_id[node.id] for node in self.nodes]

    def _decorate_cached_node_status(self, node: WorkerNode, enabled: dict[str, bool | None]) -> dict[str, Any]:
        cached = dict(self._node_status_cache.get(node.id) or self._empty_node_status(node))
        cached["gateway_enabled"] = enabled.get(node.haproxy_server)
        cached["active"] = self._is_active_node(node)
        cached["fail_count"] = self._fail_counts.get(node.id, 0)
        cached["recovery_count"] = self._recovery_counts.get(node.id, 0)
        cached["last_recovery_at"] = self._last_recovery_at.get(node.id)
        cached["last_recovery"] = self._last_recovery_result.get(node.id)
        cached["recovery_in_progress"] = node.id in self._recovery_futures
        cached["rotation_count"] = self._rotation_counts.get(node.id, 0)
        cached["next_auto_rotate_at"] = self._next_auto_rotate_at.get(node.id)
        cached["auto_rotate_in_progress"] = node.id in self._auto_rotate_futures
        cached["cache_age_seconds"] = max(0, int(time.time() - self._node_status_cache_at.get(node.id, 0))) if node.id in self._node_status_cache_at else None
        return cached

    def _empty_node_status(self, node: WorkerNode) -> dict[str, Any]:
        return {
            "id": node.id,
            "host": node.host,
            "control_port": node.control_port,
            "socks_port": node.socks_port,
            "haproxy_server": node.haproxy_server,
            "country_hint": node.country_hint,
            "container_name": node.container_name,
            "token_slot": node.token_slot,
            "ready": False,
            "service_ready": False,
            "runtime_ok": False,
            "runtime_error": "status cache is warming up",
            "logged_in": False,
            "connected": False,
            "verified": False,
            "current_ip": self._last_verified_ip.get(node.id),
            "ip_error": None,
            "latency_ms": None,
        }

    def node_status(self, node_id: str) -> dict[str, Any]:
        node = self._node(node_id)
        started = time.perf_counter()
        runtime: dict[str, Any] | None = None
        runtime_error: str | None = None
        try:
            runtime = self._worker_request(node, "GET", "/runtime", timeout=min(1.5, self.settings.proxy_control_timeout_seconds))
        except Exception as exc:
            runtime_error = str(exc)
        vpn = ExpressStatus(connected=False, raw="")
        logged_in = False
        current_ip = None
        ip_error = None
        verified = False
        if runtime and runtime.get("service_ready"):
            vpn = ExpressStatus(
                connected=bool(runtime.get("connected")),
                raw=str(runtime.get("status") or ""),
                country=node.country_hint or None,
                server=node.country_hint or None,
            )
            logged_in = bool(runtime.get("logged_in") or vpn.connected or self._account_output_indicates_logged_in(vpn.raw))
            if vpn.connected:
                now = time.time()
                last_verified = self._last_verified_at.get(node.id, 0)
                cached_ip = self._last_verified_ip.get(node.id)
                grace_period = max(15, int(self.settings.ready_verified_grace_seconds))
                if cached_ip and (now - last_verified) < grace_period:
                    current_ip = cached_ip
                    verified = True
                else:
                    current_ip, ip_error = self._current_ip(node)
                    verified = bool(current_ip)
        ready = self._update_ready_state(
            node.id,
            service_ready=bool(runtime and runtime.get("service_ready")),
            connected=vpn.connected,
            current_ip=current_ip,
            verified=verified,
            verification_error=ip_error,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "id": node.id,
            "host": node.host,
            "control_port": node.control_port,
            "socks_port": node.socks_port,
            "haproxy_server": node.haproxy_server,
            "country_hint": node.country_hint,
            "container_name": node.container_name,
            "token_slot": node.token_slot,
            "active": self._is_active_node(node),
            "ready": ready,
            "service_ready": bool(runtime and runtime.get("service_ready")),
            "runtime_ok": bool(runtime and runtime.get("ok")),
            "runtime_error": runtime_error,
            "logged_in": logged_in,
            "connected": vpn.connected,
            "verified": verified,
            "country": vpn.country,
            "city": vpn.city,
            "server": vpn.server,
            "hostname": vpn.hostname,
            "actual_server": vpn.actual_server,
            "technology": vpn.technology,
            "protocol": vpn.protocol,
            "uptime": vpn.uptime,
            "uptime_seconds": vpn.uptime_seconds,
            "current_ip": current_ip,
            "ip_error": ip_error,
            "latency_ms": latency_ms,
            "last_rotation_at": self._last_rotation_at.get(node.id),
            "rotation_count": self._rotation_counts.get(node.id, 0),
            "recovery_in_progress": node.id in self._recovery_futures,
            "ready_success_streak": self._ready_success_streaks.get(node.id, 0),
            "ready_failure_streak": self._ready_failure_streaks.get(node.id, 0),
            "next_auto_rotate_at": self._next_auto_rotate_at.get(node.id),
            "auto_rotate_in_progress": node.id in self._auto_rotate_futures,
        }

    def countries(self, *, refresh: bool = False) -> dict[str, Any]:
        configured = list(self.settings.pia_countries)
        country_source_mode = (self.settings.pia_country_source or "all").strip().lower()
        if country_source_mode == "env":
            return {
                "mode": "multi_worker_gateway",
                "country_source_mode": self.settings.pia_country_source,
                "configured": configured,
                "countries": configured,
                "countries_available_now": self._country_selection_summary(configured),
                "count": len(configured),
                "using_all_pia_countries": False,
                "source": "env:PIA_COUNTRIES",
                "raw": "",
                "note": "Country selection is restricted by PIA_COUNTRY_SOURCE=env.",
            }
        node = self._first_available_node()
        if not node:
            return {
                "mode": "multi_worker_gateway",
                "country_source_mode": self.settings.pia_country_source,
                "configured": configured,
                "countries": configured,
                "count": len(configured),
                "using_all_pia_countries": False,
                "source": "env_fallback_no_worker",
                "raw": "",
            }
        cli = self._pia(node, ["get", "regions"], timeout=self.settings.cli_command_timeout_seconds)
        countries = self._parse_countries_output(cli.output)
        if not countries:
            countries = self.settings.pia_countries
        return {
            "mode": "multi_worker_gateway",
            "country_source_mode": self.settings.pia_country_source,
            "configured": self.settings.pia_countries,
            "countries": countries,
            "countries_available_now": self._country_selection_summary(countries),
            "count": len(countries),
            "using_all_pia_countries": bool(cli.exit_code == 0 and countries),
            "source": "piactl:location" if cli.exit_code == 0 and countries else "env_fallback",
            "raw": cli.output,
            "note": "Locations are read from the first reachable worker with `piactl get regions`.",
        }

    def pia_login(
        self,
        token: str,
        *,
        token_2: str | None = None,
        persist: bool = True,
        reconnect: bool = False,
        country: str | None = None,
        server: str | None = None,
    ) -> dict[str, Any]:
        token = (token or "").strip()
        if not token:
            raise ValueError("PIA account credential is required.")
        tokens = self._login_tokens_by_slot(token, token_2)
        results = []
        ok = True
        login_jobs: list[tuple[WorkerNode, str]] = []
        for node in self._active_nodes():
            node_token = tokens.get(node.token_slot, "").strip()
            if not node_token:
                results.append(
                    {
                        "node_id": node.id,
                        "token_slot": node.token_slot,
                        "ok": False,
                        "exit_code": 1,
                        "raw": f"Missing PIA account credential for slot {node.token_slot}.",
                        "account_raw": "",
                    }
                )
                ok = False
                continue
            login_jobs.append((node, node_token))
        results.extend(self._login_nodes_parallel(login_jobs))
        ok = ok and all(item.get("ok") for item in results)
        persisted_slots: list[int] = []
        if ok and persist and self.settings.pia_token_storage_enabled:
            for slot in self._required_token_slots():
                slot_token = tokens.get(slot, "").strip()
                if slot_token:
                    self._write_stored_token(slot_token, slot=slot)
                    persisted_slots.append(slot)
        response: dict[str, Any] = {
            "ok": ok,
            "persisted": bool(persisted_slots),
            "persisted_slots": persisted_slots,
            "tokens_required": len(self._required_token_slots()),
            "token_slots": self._required_token_slots(),
            "nodes": results,
        }
        if reconnect:
            response["connect"] = self.connect(country=country, server=server, force=True)
        return response

    def pia_logout(self, *, clear_stored_token: bool = True) -> dict[str, Any]:
        results = []
        for node in self._active_nodes():
            self._disable_node(node, reason="logout")
            self._pia(node, ["disconnect"], timeout=self.settings.cli_disconnect_timeout_seconds)
            cli = self._pia(node, ["logout"], timeout=self.settings.cli_command_timeout_seconds)
            results.append({"node_id": node.id, "ok": cli.exit_code == 0, "raw": self._redact_sensitive(cli.output)})
        if clear_stored_token:
            self._clear_stored_tokens()
        return {"ok": all(r["ok"] for r in results), "nodes": results, **self.status()}

    def _login_slot(self, slot: int, token: str) -> list[dict[str, Any]]:
        return self._login_nodes_parallel([(node, token) for node in self._active_nodes() if int(node.token_slot) == int(slot)])

    def _login_nodes_parallel(self, jobs: list[tuple[WorkerNode, str]]) -> list[dict[str, Any]]:
        if not jobs:
            return []
        results: list[dict[str, Any]] = []
        # Group jobs by token slot
        slots: dict[int, list[tuple[WorkerNode, str]]] = {}
        for node, token in jobs:
            slots.setdefault(int(node.token_slot), []).append((node, token))

        for slot, slot_jobs in slots.items():
            if not slot_jobs:
                continue
            leader_node, token = slot_jobs[0]
            leader_result = self._login_node_with_token(leader_node, token)
            results.append(leader_result)
            if leader_result.get("ok"):
                for other_node, _ in slot_jobs[1:]:
                    try:
                        reload_res = self._worker_request(other_node, "POST", "/session/reload", timeout=5)
                        reload_ok = bool(reload_res.get("ok"))
                    except Exception as exc:
                        reload_ok = False
                        reload_res = {"error": str(exc)}
                    results.append({
                        "node_id": other_node.id,
                        "token_slot": other_node.token_slot,
                        "ok": reload_ok,
                        "exit_code": 0 if reload_ok else 1,
                        "raw": "session loaded from slot leader" if reload_ok else f"session reload failed: {reload_res}",
                        "account_raw": "",
                    })
            else:
                for other_node, _ in slot_jobs[1:]:
                    results.append({
                        "node_id": other_node.id,
                        "token_slot": other_node.token_slot,
                        "ok": False,
                        "exit_code": leader_result.get("exit_code", 1),
                        "raw": f"slot leader login failed: {leader_result.get('raw')}",
                        "account_raw": "",
                    })

        results.sort(key=lambda item: int(re.sub(r"\D", "", str(item.get("node_id") or "0")) or 0))
        return results

    def _login_node_with_token(self, node: WorkerNode, token: str) -> dict[str, Any]:
        cli = self._login_with_token(node, token)
        output_lower = (cli.output or "").lower()
        node_ok = cli.exit_code == 0 or "already logged" in output_lower or "logged into account" in output_lower
        return {
            "node_id": node.id,
            "token_slot": node.token_slot,
            "ok": node_ok,
            "exit_code": 0 if node_ok else cli.exit_code,
            "raw": self._redact_sensitive(cli.output or ("Already logged into account" if node_ok else "Login failed")),
            "account_raw": "",
        }

    def connect(self, country: str | None = None, server: str | None = None, force: bool = True) -> dict[str, Any]:
        # Old API compatibility: prepare the whole worker pool. This is useful after login/startup.
        results = []
        for node in self._active_nodes():
            target = server or country or node.country_hint or None
            results.append(self.rotate_node(node.id, country=target if not server else None, server=server, wait_for_ready=True, require_new_ip=False, min_ready_workers=0))
        status = self.status()
        return {"ok": any(r.get("ok") for r in results), "operation": "connect_pool", "nodes_result": results, **status}

    def random_ip(self) -> dict[str, Any]:
        return self.rotate_any(wait_for_ready=False)

    def change_country(self, country: str | None = None, server: str | None = None) -> dict[str, Any]:
        return self.rotate_any(country=country, server=server, wait_for_ready=False)

    def disconnect(self) -> dict[str, Any]:
        results = []
        for node in self._active_nodes():
            self._disable_node(node, reason="disconnect")
            cli = self._pia(node, ["disconnect"], timeout=self.settings.cli_disconnect_timeout_seconds)
            results.append({"node_id": node.id, "ok": cli.exit_code == 0, "raw": cli.output})
        return {"ok": all(r["ok"] for r in results), "nodes_result": results, **self.status()}

    def test_proxy(self) -> dict[str, Any]:
        started = time.perf_counter()
        ip = None
        err = None
        try:
            res = self._ip_check_with_proxy(self._gateway_proxy_url(), timeout=self.settings.ip_check_timeout_seconds)
            ip, err = res
        except Exception as exc:
            err = str(exc)
        total_ms = int((time.perf_counter() - started) * 1000)
        nodes = self.nodes_status(refresh=True)
        return {
            "ok": bool(ip),
            "container_running": any(n.get("service_ready") for n in nodes),
            "pia_connected": any(n.get("connected") for n in nodes),
            "socks5_ok": bool(ip),
            "http_ok": False,
            "ip_check_ok": bool(ip),
            "all_enabled_proxies_ok": bool(ip),
            "current_ip": ip,
            "latency_ms": total_ms,
            "actual_server": next((n.get("actual_server") for n in nodes if n.get("current_ip") == ip), None),
            "proxy": self._public_proxy(mask=self.settings.mask_proxy_password_in_status),
            "error": err,
            "nodes": nodes,
        }

    def logs(self, tail: int = 100) -> dict[str, Any]:
        tail = max(1, min(int(tail), 500))
        parts = []
        vpn_status_parts = []
        for node in self.nodes:
            try:
                logs = self._worker_request(node, "GET", "/logs", params={"tail": tail}, timeout=8)
                parts.append(f"--- {node.id} / {node.host} ---\n{logs.get('log', '')}")
            except Exception as exc:
                parts.append(f"--- {node.id} / {node.host} ---\n<unreachable: {exc}>")
            status = self._pia(node, ["status"], timeout=8)
            vpn_status_parts.append(f"--- {node.id} ---\n{status.output}")
        haproxy = self._haproxy_command("show stat")
        return {
            "container": "proxy-gateway + workers",
            "tail": tail,
            "docker_logs": "\n\n".join(parts),
            "pia_status": "\n\n".join(vpn_status_parts),
            "haproxy": haproxy,
        }

    def health_tick(self) -> dict[str, Any]:
        """One watchdog pass.

        The monitor does three things:
        1. Keep HAProxy routing only READY workers.
        2. Count consecutive failures per worker.
        3. Self-heal each unhealthy worker so the pool returns to full READY.
        """
        nodes = self.nodes_status(refresh=True)
        active_nodes = [n for n in nodes if n.get("active")]
        ready_count = sum(1 for n in active_nodes if n.get("ready"))
        recovery_results: list[dict[str, Any]] = self._collect_finished_recoveries()
        auto_rotating = set(self._auto_rotate_running_ids())

        for n in nodes:
            node = self._node(n["id"])
            if not n.get("active"):
                self._disable_node(node, reason="health_tick_inactive_mode")
                continue
            if n.get("ready"):
                self._fail_counts[node.id] = 0
            elif node.id in auto_rotating:
                self._disable_node(node, reason="health_tick_auto_rotate")
            else:
                self._fail_counts[node.id] = self._fail_counts.get(node.id, 0) + 1
                if n.get("gateway_enabled"):
                    self._disable_node(node, reason="health_tick_not_ready")

        stored_auth_available = any(
            bool(self._read_stored_token(slot=slot) or self._env_token_for_slot(slot))
            for slot in self._required_token_slots()
        )
        pool_has_auth = any(bool(n.get("logged_in") or n.get("connected")) for n in active_nodes) or stored_auth_available
        if self.settings.auto_reconnect and self.settings.worker_recovery_enabled and pool_has_auth:
            down_nodes = [n for n in active_nodes if not n.get("ready") and n.get("id") not in auto_rotating]
            if down_nodes:
                recovery_results.extend(self._start_background_recoveries(down_nodes))
        elif self.settings.auto_reconnect and self.settings.worker_recovery_enabled and active_nodes:
            recovery_results.append({"ok": True, "mode": "recovery_paused_until_explicit_login"})

        gateway_sync = self._sync_ready_gateway_pool(nodes)
        auto_rotate_result = self._maybe_auto_rotate(nodes)
        final_ready_count = sum(1 for n in active_nodes if n.get("ready"))
        min_ready = self._effective_min_ready_workers()
        return {
            "ok": final_ready_count >= min_ready,
            "ready_count": final_ready_count,
            "min_ready_workers": min_ready,
            "previous_ready_count": ready_count,
            "total_workers": len(active_nodes),
            "recovery_results": recovery_results,
            "recovery_in_progress": self._recovery_running_ids(),
            "gateway_sync": gateway_sync,
            "auto_rotate_result": auto_rotate_result,
            "nodes": nodes,
        }

    # ---------- New node/session APIs ----------
    def healthy_nodes(self) -> dict[str, Any]:
        nodes = self.nodes_status(refresh=False)
        active = [n for n in nodes if n.get("active")]
        healthy = [n for n in active if n.get("ready")]
        min_ready = self._effective_min_ready_workers()
        return {"ok": len(healthy) >= min_ready, "ready_count": len(healthy), "min_ready_workers": min_ready, "total": len(active), "nodes": healthy}

    def _collect_finished_recoveries(self) -> list[dict[str, Any]]:
        completed: list[dict[str, Any]] = []
        with self._recovery_lock:
            items = list(self._recovery_futures.items())
        for node_id, future in items:
            if not future.done():
                continue
            with self._recovery_lock:
                self._recovery_futures.pop(node_id, None)
            try:
                completed.append(future.result())
            except Exception as exc:
                result = {"ok": False, "node_id": node_id, "error": str(exc)}
                self._last_recovery_result[node_id] = result
                completed.append(result)
                logger.exception("Background recovery worker %s crashed", node_id)
        return completed

    def _start_background_recoveries(self, down_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        started: list[dict[str, Any]] = []
        max_parallel = max(1, int(self.settings.worker_recovery_max_parallel))
        running = set(self._recovery_running_ids())
        available_slots = max(0, max_parallel - len(running))
        if available_slots <= 0:
            return [{"ok": True, "mode": "recovery_waiting_for_running_jobs", "running": sorted(running), "max_parallel": max_parallel}]
        for status in down_nodes:
            node_id = status["id"]
            if node_id in running:
                continue
            node = self._node(node_id)
            future = self._recovery_executor.submit(self._recover_node, node, status, automatic=True)
            with self._recovery_lock:
                self._recovery_futures[node_id] = future
            running.add(node_id)
            started.append({"ok": True, "mode": "background_recovery_started", "node_id": node_id})
            if len(started) >= available_slots:
                break
        return started

    def _recovery_running_ids(self) -> list[str]:
        with self._recovery_lock:
            return sorted(node_id for node_id, future in self._recovery_futures.items() if not future.done())

    def recover_all(self, *, force: bool = False) -> dict[str, Any]:
        nodes = self.nodes_status(refresh=True)
        active = [n for n in nodes if n.get("active")]
        targets = [n for n in active if force or not n.get("ready")]
        results: list[dict[str, Any]] = []
        if targets:
            max_workers = max(1, min(int(self.settings.worker_recovery_max_parallel), len(targets)))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = [pool.submit(self._recover_node, self._node(n["id"]), n, automatic=False, force=force) for n in targets]
                for future in as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        results.append({"ok": False, "error": str(exc)})
        final_nodes = self.nodes_status(refresh=True)
        final_active = [n for n in final_nodes if n.get("active")]
        ready_count = sum(1 for n in final_active if n.get("ready"))
        min_ready = self._effective_min_ready_workers()
        return {"ok": ready_count >= min_ready, "operation": "recover_all", "ready_count": ready_count, "min_ready_workers": min_ready, "total_workers": len(final_active), "results": results, "nodes": final_nodes}

    def recover_node(self, node_id: str, *, force: bool = False) -> dict[str, Any]:
        node = self._node(node_id)
        status = self.node_status(node.id)
        status["gateway_enabled"] = self._haproxy_enabled_servers().get(node.haproxy_server)
        return self._recover_node(node, status, automatic=False, force=force)

    def _maybe_auto_rotate(self, nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
        completed = self._collect_finished_auto_rotates()
        if not self.settings.auto_rotate_enabled:
            return {"ok": True, "mode": "auto_rotate_disabled", "completed": completed} if completed else None
        active_nodes = [n for n in nodes if n.get("active")]
        recovering_ids = set(self._recovery_running_ids())
        ready = [n for n in active_nodes if n.get("ready") and n.get("id") not in recovering_ids]
        min_ready = self._auto_rotate_ready_floor(len(active_nodes))
        pause_threshold = max(min_ready, int(self.settings.auto_rotate_pause_ready_threshold))
        running_ids = self._auto_rotate_running_ids()
        now = time.time()
        max_uptime = max(0, int(self.settings.auto_rotate_max_uptime_seconds))
        uptime_due = [
            n
            for n in ready
            if n["id"] not in running_ids
            and max_uptime
            and int(n.get("uptime_seconds") or 0) >= max_uptime
        ]
        force_uptime_rotate = bool(uptime_due)
        if len(ready) <= pause_threshold and not force_uptime_rotate:
            if completed or running_ids:
                return {
                    "ok": True,
                    "mode": "auto_rotate_paused_capacity",
                    "ready_workers": len(ready),
                    "auto_rotate_min_ready_workers": min_ready,
                    "pause_threshold": pause_threshold,
                    "running": running_ids,
                    "recovery_running": sorted(recovering_ids),
                    "completed": completed,
                }
            return None
        token_slots = self._required_token_slots()
        per_token_parallel = max(1, int(self.settings.auto_rotate_max_parallel_per_token))
        max_parallel = min(
            max(1, int(self.settings.auto_rotate_max_parallel)),
            max(1, len(token_slots)) * per_token_parallel,
        )
        available_slots = max_parallel - len(running_ids) if force_uptime_rotate else min(max_parallel - len(running_ids), len(ready) - pause_threshold)
        if available_slots <= 0:
            if completed or running_ids:
                return {
                    "ok": True,
                    "mode": "auto_rotate_waiting_for_running_jobs",
                    "running": running_ids,
                    "recovery_running": sorted(recovering_ids),
                    "completed": completed,
                    "max_parallel": max_parallel,
                    "auto_rotate_min_ready_workers": min_ready,
                }
            return None
        schedule_due = [n for n in ready if n["id"] not in running_ids and (self._next_auto_rotate_at.get(n["id"]) or 0) <= now]
        if not uptime_due and not schedule_due:
            return {"ok": True, "mode": "auto_rotate_collect", "running": running_ids, "recovery_running": sorted(recovering_ids), "completed": completed} if completed or running_ids else None
        uptime_due_ids = {n["id"] for n in uptime_due}
        schedule_due_ids = {n["id"] for n in schedule_due}
        due_ids = uptime_due_ids | schedule_due_ids
        eligible = uptime_due if force_uptime_rotate else [n for n in ready if n["id"] not in running_ids]
        eligible.sort(
            key=lambda item: (
                0 if item["id"] in uptime_due_ids else 1,
                -(int(item.get("uptime_seconds") or 0)),
                0 if item["id"] in due_ids else 1,
                self._last_rotation_at.get(item["id"], 0) or 0,
                self._next_auto_rotate_at.get(item["id"], 0),
                self._rotation_counts.get(item["id"], 0),
                item["id"],
            )
        )
        running_slot_counts: dict[int, int] = {}
        for node_id in running_ids:
            token_slot = int(self._node(node_id).token_slot)
            running_slot_counts[token_slot] = running_slot_counts.get(token_slot, 0) + 1
        selected_due: list[dict[str, Any]] = []
        selected_slot_counts: dict[int, int] = {}
        for candidate in eligible:
            token_slot = int(self._node(candidate["id"]).token_slot)
            slot_parallel = running_slot_counts.get(token_slot, 0) + selected_slot_counts.get(token_slot, 0)
            if slot_parallel >= per_token_parallel:
                continue
            selected_due.append(candidate)
            selected_slot_counts[token_slot] = selected_slot_counts.get(token_slot, 0) + 1
            if len(selected_due) >= available_slots:
                break

        started: list[dict[str, Any]] = []
        for selected in selected_due:
            selected_rotation_count = self._rotation_counts.get(selected["id"], 0)
            selected_last_rotation_at = self._last_rotation_at.get(selected["id"])
            selected_country = self.settings.auto_rotate_country.strip() or self._pick_random_country(
                exclude=selected.get("country") or selected.get("country_hint"),
                exclude_countries=self._countries_in_use(exclude_node_id=selected["id"]),
            )
            selected_server = self.settings.auto_rotate_server.strip() or None
            future = self._auto_rotate_executor.submit(
                self._run_scheduled_auto_rotate,
                selected["id"],
                selected_country if not selected_server else None,
                selected_server,
                now,
                selected_rotation_count,
                selected_last_rotation_at,
            )
            with self._auto_rotate_lock:
                self._auto_rotate_futures[selected["id"]] = future
            started.append(
                {
                    "node_id": selected["id"],
                    "selected_country": selected_country,
                    "selected_server": selected_server,
                    "selection_triggered_by_due_worker": selected["id"] in due_ids,
                    "selection_trigger": "max_uptime" if selected["id"] in uptime_due_ids else ("schedule" if selected["id"] in schedule_due_ids else "longest_uptime"),
                    "uptime_seconds_before": selected.get("uptime_seconds"),
                    "uptime_before": selected.get("uptime"),
                    "rotation_count_before": selected_rotation_count,
                    "last_rotation_at_before": selected_last_rotation_at,
                    "next_auto_rotate_at_before": self._next_auto_rotate_at.get(selected["id"]),
                }
            )
        return {
            "ok": True,
            "mode": "scheduled_background_rotate",
            "started": started,
            "running": self._auto_rotate_running_ids(),
            "completed": completed,
            "scheduled_at": now,
            "fairness": {
                "selection_mode": "longest_uptime_ready_workers",
                "due_workers": sorted(due_ids),
                "uptime_due_workers": sorted(uptime_due_ids),
                "schedule_due_workers": sorted(schedule_due_ids),
                "auto_rotate_max_uptime_seconds": max_uptime,
                "force_uptime_rotate": force_uptime_rotate,
                "available_slots": available_slots,
                "max_parallel": max_parallel,
                "auto_rotate_min_ready_workers": min_ready,
                "pause_threshold": pause_threshold,
                "recovery_running": sorted(recovering_ids),
            },
        }

    def _collect_finished_auto_rotates(self) -> list[dict[str, Any]]:
        completed: list[dict[str, Any]] = []
        with self._auto_rotate_lock:
            items = list(self._auto_rotate_futures.items())
        for node_id, future in items:
            if not future.done():
                continue
            with self._auto_rotate_lock:
                self._auto_rotate_futures.pop(node_id, None)
            try:
                result = future.result()
            except Exception as exc:
                result = {"ok": False, "mode": "scheduled_background_rotate", "node_id": node_id, "error": str(exc)}
                logger.exception("Auto-rotate worker %s crashed", node_id)
            self._last_auto_rotate_result = result
            completed.append(result)
        return completed

    def _auto_rotate_running_ids(self) -> list[str]:
        with self._auto_rotate_lock:
            return sorted(node_id for node_id, future in self._auto_rotate_futures.items() if not future.done())

    def _run_scheduled_auto_rotate(
        self,
        node_id: str,
        country: str | None,
        server: str | None,
        scheduled_at: float,
        rotation_count_before: int,
        last_rotation_at_before: float | None,
    ) -> dict[str, Any]:
        started_at = time.time()
        tried: set[str] = set()
        targets: list[str | None] = []
        max_targets = max(1, int(self.settings.auto_rotate_target_attempts))
        if server:
            targets.append(None)
        else:
            if country:
                targets.append(country)
                tried.add(self._normalize_country_key(country))
            node_status = self._node_status_cache.get(node_id) or {}
            fallback_targets = self._pick_country_candidates(
                exclude=country or node_status.get("country") or node_status.get("country_hint"),
                exclude_countries=self._countries_in_use(exclude_node_id=node_id),
                limit=max(0, max_targets - len(targets)),
            )
            for target in fallback_targets:
                key = self._normalize_country_key(target)
                if key and key not in tried:
                    targets.append(target)
                    tried.add(key)
        if not targets:
            targets.append(None)

        attempts: list[dict[str, Any]] = []
        last_payload: dict[str, Any] | None = None
        try:
            for target in targets[:max_targets]:
                result = self.rotate_node(
                    node_id,
                    country=target if not server else None,
                    server=server,
                    wait_for_ready=False,
                    require_new_ip=True,
                    connect_timeout_seconds=self.settings.auto_rotate_connect_timeout_seconds,
                    retry_after_disconnect=False,
                    min_ready_workers=self._auto_rotate_ready_floor(),
                )
                attempts.append({"target": server or target or "quick-connect", "ok": bool(result.get("ok")), "error": result.get("error") or result.get("last_error")})
                last_payload = result
                if result.get("ok"):
                    break
            result = last_payload or {"ok": False, "error": "No auto-rotate target was attempted."}
            payload = {
                "ok": result.get("ok", False),
                "mode": "scheduled_background_rotate",
                "selected_node": node_id,
                "selected_country": country,
                "selected_server": server,
                "target_attempts": attempts,
                "scheduled_at": scheduled_at,
                "started_at": started_at,
                "finished_at": time.time(),
                "fairness": {
                    "rotation_count_before": rotation_count_before,
                    "last_rotation_at_before": last_rotation_at_before,
                    "selection_mode": "longest_uptime_ready_workers",
                },
                **result,
            }
            if payload["ok"]:
                logger.info("Auto-rotate succeeded for %s: %s -> %s", node_id, result.get("old_ip"), result.get("current_ip"))
            else:
                logger.warning("Auto-rotate failed for %s: %s", node_id, result.get("error") or result.get("last_error"))
            return payload
        finally:
            self._schedule_next_auto_rotate(node_id, now=time.time())

    def rotate_any(self, country: str | None = None, server: str | None = None, wait_for_ready: bool = False) -> dict[str, Any]:
        nodes = self.nodes_status(refresh=True)
        active_nodes = [n for n in nodes if n.get("active")]
        ready = [n for n in active_nodes if n.get("ready")]
        candidates = [n for n in active_nodes if n.get("service_ready")]
        selected = None
        selection_mode = "random_worker"
        active_gateway = next((n for n in nodes if n.get("gateway_enabled") and n.get("service_ready")), None)
        gateway_ip = active_gateway.get("current_ip") if active_gateway else (self._gateway_current_ip() if ready else None)
        if active_gateway:
            selected = active_gateway
            selection_mode = "gateway_enabled_worker"
        elif gateway_ip:
            gateway_matches = [n for n in ready if n.get("current_ip") == gateway_ip]
            if gateway_matches:
                selected = random.choice(gateway_matches)
                selection_mode = "gateway_active_worker"
        # Prefer rotating the worker currently backing the gateway IP. If that cannot be
        # inferred, fall back to any READY worker that still leaves enough capacity.
        if not selected and len(ready) > self._effective_min_ready_workers():
            selected = random.choice(ready)
        elif candidates:
            selected = random.choice(candidates)
            selection_mode = "service_ready_fallback"
        else:
            raise RuntimeError("No worker is reachable for rotation.")
        selected_country = country
        if not server and not selected_country:
            selected_country = self._pick_random_country(
                exclude=selected.get("country") or selected.get("country_hint"),
                exclude_countries=self._countries_in_use(exclude_node_id=selected["id"]),
            )
        result = self.rotate_node(selected["id"], country=selected_country, server=server, wait_for_ready=wait_for_ready, require_new_ip=True)
        country_pool = None
        if not server:
            country_pool = {
                "selected_country": selected_country or result.get("country"),
                "selection_mode": "explicit" if country else "random_pool",
            }
        return {
            "ok": result.get("ok", False),
            "operation": "rotate_any",
            "selected_node": selected["id"],
            "worker_selection_mode": selection_mode,
            "gateway_ip_before_rotate": gateway_ip,
            "country_pool": country_pool,
            **result,
            **self.status(),
        }

    def rotate_node(
        self,
        node_id: str,
        *,
        country: str | None = None,
        server: str | None = None,
        wait_for_ready: bool = True,
        require_new_ip: bool = True,
        connect_timeout_seconds: int | None = None,
        retry_after_disconnect: bool = True,
        min_ready_workers: int | None = None,
    ) -> dict[str, Any]:
        node = self._node(node_id)
        if not self._is_active_node(node):
            return {"ok": False, "node_id": node.id, "error": "Worker is inactive in the current mode."}
        lock = self._locks[node.id]
        with lock:
            self._enforce_rotation_cooldown(node.id)
            old_ip, _ = self._current_ip(node)
            started = time.perf_counter()
            target = server or country or node.country_hint or None
            target_key = self._normalize_country_key(country if country else (None if server else target))
            standby_promotion = None
            ready_before = [n for n in self.nodes_status(refresh=True) if n.get("active") and n.get("ready") and n.get("id") != node.id]
            min_ready = self._effective_min_ready_workers() if min_ready_workers is None else max(0, int(min_ready_workers))
            if len(ready_before) < min_ready:
                return {
                    "ok": False,
                    "node_id": node.id,
                    "old_ip": old_ip,
                    "current_ip": old_ip,
                    "target": target or "quick-connect",
                    "error": f"Refusing to rotate because current mode requires at least {min_ready} READY workers.",
                    "gateway_reenabled": True,
                }
            self._disable_node(node, reason="rotate_start")
            self._last_verified_at.pop(node.id, None)
            self._last_verified_ip.pop(node.id, None)
            self._ready_state[node.id] = False
            attempts: list[dict[str, Any]] = []
            last_error = ""
            self._rotation_counts[node.id] = self._rotation_counts.get(node.id, 0) + 1
            try:
                cli_ok, cli_error = self._connect_with_fallback(
                    node,
                    target=target,
                    attempts=attempts,
                    timeout_seconds=connect_timeout_seconds,
                    retry_after_disconnect=retry_after_disconnect,
                )
                if not cli_ok:
                    last_error = str(cli_error or "")
                    raise RuntimeError(f"pia connect failed on {node.id}: {last_error[-1200:]}")
                ip = None
                ip_error = None
                if wait_for_ready:
                    ip, wait_ms, ip_error = self._wait_for_verified_ip(node)
                else:
                    # Short wait for smooth API response, background health_tick will re-enable later if not ready yet.
                    ip, wait_ms, ip_error = self._wait_for_verified_ip(node, max_seconds=min(8, self.settings.connect_timeout_seconds))
                if not ip:
                    last_error = ip_error or "No verified IP returned."
                    raise RuntimeError(f"{node.id} connected but IP verification failed: {last_error}")
                if require_new_ip and old_ip and ip == old_ip:
                    last_error = f"IP did not change: {ip}"
                    raise RuntimeError(last_error)
                vpn = ExpressStatus(connected=True, raw="", country=country or node.country_hint or None, server=target)
                self._last_rotation_at[node.id] = time.time()
                self._record_country_result(target_key, ok=True, error=None)
                self._record_server_result(vpn.actual_server, ok=True, error=None)
                self._enable_node(node, reason="rotate_success")
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                return {
                    "ok": True,
                    "node_id": node.id,
                    "old_ip": old_ip,
                    "current_ip": ip,
                    "country": vpn.country,
                    "server": vpn.server,
                    "actual_server": vpn.actual_server,
                    "target": target or "quick-connect",
                    "connect_time_ms": elapsed_ms,
                    "wait_ip_ms": wait_ms,
                    "gateway_reenabled": True,
                    "standby_promotion": standby_promotion,
                    "country_target_health": self._country_health_view(target_key),
                    "server_target_health": self._server_health_view(vpn.actual_server),
                    "attempts": attempts,
                }
            except Exception as exc:
                # Keep the failing worker out of the gateway. Other READY workers continue serving traffic.
                self._disable_node(node, reason="rotate_failed")
                self._record_country_result(target_key, ok=False, error=last_error or str(exc))
                self._record_server_result(self._extract_server_hostname(last_error or str(exc)), ok=False, error=last_error or str(exc))
                return {
                    "ok": False,
                    "node_id": node.id,
                    "old_ip": old_ip,
                    "current_ip": None,
                    "target": target or "quick-connect",
                    "error": str(exc),
                    "last_error": last_error[-1200:],
                    "gateway_reenabled": False,
                    "standby_promotion": standby_promotion,
                    "country_target_health": self._country_health_view(target_key),
                    "server_target_health": self._server_health_view(self._extract_server_hostname(last_error or str(exc))),
                    "attempts": attempts,
                }

    def disable_node(self, node_id: str) -> dict[str, Any]:
        node = self._node(node_id)
        return self._disable_node(node, reason="manual")

    def enable_node(self, node_id: str) -> dict[str, Any]:
        node = self._node(node_id)
        self._active_gateway_node_id = node.id
        return self._enable_node(node, reason="manual")

    def session_rotate(self, session_id: str, country: str | None = None, server: str | None = None) -> dict[str, Any]:
        # HAProxy cannot inspect SOCKS username deeply in TCP mode. We still persist a control-plane
        # binding for clients that coordinate with the API, and we rotate a non-critical worker.
        session_id = session_id.strip()
        if not session_id:
            raise ValueError("session_id is required.")
        sessions = self._read_sessions()
        current = sessions.get(session_id)
        nodes = self.nodes_status(refresh=True)
        ready = [n for n in nodes if n.get("active") and n.get("ready") and n.get("id") != current]
        if not ready:
            ready = [n for n in nodes if n.get("active") and n.get("ready")]
        if not ready:
            raise RuntimeError("No ready worker available for session rotate.")
        replacement = random.choice(ready)
        sessions[session_id] = replacement["id"]
        self._write_sessions(sessions)
        old_worker = current
        # Rotate the old worker in-band only if it exists and we still have enough ready nodes.
        rotate_result = None
        if old_worker and old_worker != replacement["id"] and len(ready) > self._effective_min_ready_workers():
            rotate_result = self.rotate_node(old_worker, country=country, server=server, wait_for_ready=False, require_new_ip=True)
        return {
            "ok": True,
            "session_id": session_id,
            "old_worker": old_worker,
            "new_worker": replacement["id"],
            "new_ip": replacement.get("current_ip"),
            "note": "TCP HAProxy mode does not migrate already-open SOCKS connections; new requests use healthy gateway workers.",
            "background_rotate": rotate_result,
        }

    # ---------- Worker self-healing ----------
    def _recover_node(
        self,
        node: WorkerNode,
        status: dict[str, Any] | None = None,
        *,
        automatic: bool = True,
        force: bool = False,
    ) -> dict[str, Any]:
        lock = self._locks[node.id]
        acquired = lock.acquire(blocking=False)
        if not acquired:
            return {"ok": False, "node_id": node.id, "skipped": True, "reason": "node is busy rotating/recovering"}

        try:
            status = status or self.node_status(node.id)
            fail_count = int(self._fail_counts.get(node.id, 0))
            now = time.time()
            last_recovery = self._last_recovery_at.get(node.id, 0)
            cooldown = max(0, int(self.settings.worker_recovery_cooldown_seconds))

            is_disconnected = not bool(status.get("connected"))
            if not force and automatic and not is_disconnected and fail_count < int(self.settings.worker_recovery_connect_after_failures):
                return {"ok": False, "node_id": node.id, "skipped": True, "reason": f"waiting for fail threshold ({fail_count})", "fail_count": fail_count}
            if not force and automatic and cooldown and last_recovery and now - last_recovery < cooldown:
                return {
                    "ok": False,
                    "node_id": node.id,
                    "skipped": True,
                    "reason": "recovery cooldown",
                    "retry_after_seconds": max(0, int(cooldown - (now - last_recovery))),
                    "fail_count": fail_count,
                }

            self._last_recovery_at[node.id] = now
            self._disable_node(node, reason="recovery_start")
            actions: list[dict[str, Any]] = []

            def add_action(name: str, result: dict[str, Any]) -> None:
                actions.append({"action": name, **result})

            # If the worker control API/runtime is broken, restart immediately. A dead control API
            # is more disruptive than a temporary VPN disconnect and usually needs a stronger reset.
            if force or not status.get("service_ready"):
                restart = self._restart_worker_control(node)
                add_action("worker_control_restart", restart)
                if not restart.get("ok") or not self.node_status(node.id).get("service_ready"):
                    add_action("docker_restart", self._docker_restart_container(node))

            # If the control API is unreachable for many ticks, fall back to Docker restart.
            if (force or fail_count >= int(self.settings.worker_recovery_docker_restart_after_failures)) and not actions:
                latest_runtime_ok = False
                try:
                    latest_runtime_ok = bool(self._worker_request(node, "GET", "/runtime", timeout=3).get("service_ready"))
                except Exception:
                    latest_runtime_ok = False
                if not latest_runtime_ok:
                    add_action("docker_restart", self._docker_restart_container(node))

            # Login if there is a stored/env token and this node is logged out.
            latest = self.node_status(node.id)
            if force or not latest.get("logged_in"):
                add_action("login", self._login_node_from_stored_token(node))
                latest = self.node_status(node.id)

            # Reconnect if PIA is disconnected or the SOCKS path cannot verify an IP.
            if force or not latest.get("connected") or not latest.get("current_ip"):
                add_action("connect", self._connect_node_for_recovery(node))

            final = self.node_status(node.id)
            if final.get("ready"):
                self._fail_counts[node.id] = 0
                self._recovery_counts[node.id] = self._recovery_counts.get(node.id, 0) + 1
                self._enable_node(node, reason="recovery_success")
                result = {
                    "ok": True,
                    "node_id": node.id,
                    "ready": True,
                    "current_ip": final.get("current_ip"),
                    "fail_count_before": fail_count,
                    "actions": actions,
                }
            else:
                self._disable_node(node, reason="recovery_still_not_ready")
                result = {
                    "ok": False,
                    "node_id": node.id,
                    "ready": False,
                    "fail_count": self._fail_counts.get(node.id, fail_count),
                    "final_error": final.get("runtime_error") or final.get("ip_error") or "worker is still not ready",
                    "actions": actions,
                }
            self._last_recovery_result[node.id] = result
            return result
        finally:
            lock.release()

    def _login_node_from_stored_token(self, node: WorkerNode) -> dict[str, Any]:
        # Try reloading session first from credentials cache
        try:
            reload_res = self._worker_request(node, "POST", "/session/reload", timeout=3)
            if reload_res.get("ok") and reload_res.get("logged_in"):
                return {
                    "ok": True,
                    "token_slot": node.token_slot,
                    "exit_code": 0,
                    "raw": "session restored from credentials cache",
                    "account_raw": "",
                }
        except Exception:
            pass

        token = (self._read_stored_token(slot=node.token_slot) or self._env_token_for_slot(node.token_slot)).strip()
        if not token:
            return {"ok": False, "skipped": True, "reason": f"no PIA account credential available for slot {node.token_slot}", "token_slot": node.token_slot}

        # Serialize logins to prevent PIA API rate limiting across workers
        slot_lock = getattr(self, f"_login_slot_lock_{node.token_slot}", None)
        if slot_lock is None:
            slot_lock = RLock()
            setattr(self, f"_login_slot_lock_{node.token_slot}", slot_lock)

        with slot_lock:
            # Check again if another thread already logged in and saved session
            try:
                reload_res = self._worker_request(node, "POST", "/session/reload", timeout=3)
                if reload_res.get("ok") and reload_res.get("logged_in"):
                    return {
                        "ok": True,
                        "token_slot": node.token_slot,
                        "exit_code": 0,
                        "raw": "session restored from credentials cache",
                        "account_raw": "",
                    }
            except Exception:
                pass

            cli = self._login_with_token(node, token)
            ok = cli.exit_code == 0 or (cli.exit_code == 127 and "already logged into account" in cli.output.lower())
            return {
                "ok": ok,
                "token_slot": node.token_slot,
                "exit_code": 0 if ok else cli.exit_code,
                "raw": self._redact_sensitive(cli.output[-1200:]),
                "account_raw": "",
            }

    def _connect_node_for_recovery(self, node: WorkerNode) -> dict[str, Any]:
        preferred_target = node.country_hint or self.settings.pia_connect_target or self.settings.pia_default_country or None
        recovery_targets: list[str | None] = []
        target_keys: set[str] = set()
        if preferred_target:
            recovery_targets.append(preferred_target)
            target_keys.add(self._normalize_country_key(preferred_target))
        fallback_countries = self._pick_country_candidates(
            exclude=preferred_target,
            exclude_countries=self._countries_in_use(exclude_node_id=node.id),
            limit=5,
        )
        for fallback_country in fallback_countries:
            key = self._normalize_country_key(fallback_country)
            if key and key not in target_keys:
                recovery_targets.append(fallback_country)
                target_keys.add(key)
        if not recovery_targets:
            recovery_targets.append(None)
        attempts: list[dict[str, Any]] = []
        max_attempts = max(1, min(int(self.settings.worker_recovery_connect_max_attempts), 3))
        last_error = ""
        for target in recovery_targets:
            target_error = ""
            for attempt in range(1, max_attempts + 1):
                cli_attempts: list[dict[str, Any]] = []
                cli_ok, cli_error = self._connect_with_fallback(node, target=target, attempts=cli_attempts, attempt=attempt)
                attempts.extend(cli_attempts)
                if not cli_ok:
                    last_error = str(cli_error or "")
                    target_error = last_error
                    time.sleep(1)
                    continue
                ip, wait_ms, ip_error = self._wait_for_verified_ip(node, max_seconds=self.settings.worker_recovery_verify_seconds)
                attempts.append({"attempt": attempt, "target": target or "quick-connect", "phase": "verify_ip", "ok": bool(ip), "ip": ip, "wait_ms": wait_ms, "error": ip_error})
                if ip:
                    vpn = ExpressStatus(connected=True, raw="", country=target or node.country_hint or None, server=target)
                    self._record_country_result(self._normalize_country_key(target), ok=True, error=None)
                    self._record_server_result(vpn.actual_server, ok=True, error=None)
                    return {"ok": True, "target": target or "quick-connect", "current_ip": ip, "attempts": attempts}
                last_error = ip_error or "IP verification failed"
                target_error = last_error
                time.sleep(1)
            self._record_country_result(self._normalize_country_key(target), ok=False, error=target_error or last_error)
        self._record_country_result(self._normalize_country_key(preferred_target or (recovery_targets[0] if recovery_targets else None)), ok=False, error=last_error)
        self._record_server_result(self._extract_server_hostname(last_error), ok=False, error=last_error)
        return {"ok": False, "target": preferred_target or (recovery_targets[0] if recovery_targets else None) or "quick-connect", "error": str(last_error)[-1200:], "attempts": attempts}

    def _restart_worker_control(self, node: WorkerNode) -> dict[str, Any]:
        try:
            data = self._worker_request(node, "POST", "/restart", payload={}, timeout=4)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        # The request intentionally makes the worker exit; Docker restart policy brings it back.
        deadline = time.time() + max(5, int(self.settings.worker_recovery_verify_seconds))
        last_error = None
        time.sleep(2)
        while time.time() < deadline:
            try:
                runtime = self._worker_request(node, "GET", "/runtime", timeout=3)
                if runtime.get("service_ready"):
                    return {"ok": True, "raw": data, "runtime": runtime}
                last_error = str(runtime)
            except Exception as exc:
                last_error = str(exc)
            time.sleep(1)
        return {"ok": False, "raw": data, "error": last_error or "worker did not return after control restart"}

    def _docker_restart_container(self, node: WorkerNode) -> dict[str, Any]:
        if not self.settings.docker_recovery_enabled:
            return {"ok": False, "skipped": True, "reason": "DOCKER_RECOVERY_ENABLED=false"}
        sock_path = Path(self.settings.docker_socket_path)
        if not sock_path.exists():
            return {"ok": False, "skipped": True, "reason": f"Docker socket not found: {sock_path}"}
        container_name = node.container_name or self._default_container_name_for_host(node.host)
        path = f"/containers/{url_quote(container_name, safe='')}/restart?t={int(self.settings.container_stop_timeout_seconds)}"
        try:
            response = self._docker_unix_http("POST", path)
        except Exception as exc:
            return {"ok": False, "container": container_name, "error": str(exc)}
        ok = response.get("status_code") in {200, 204, 304}
        return {"ok": ok, "container": container_name, **response}

    def _docker_start_container(self, node: WorkerNode) -> dict[str, Any]:
        sock_path = Path(self.settings.docker_socket_path)
        if not sock_path.exists():
            return {"ok": False, "skipped": True, "reason": f"Docker socket not found: {sock_path}"}
        container_name = node.container_name or self._default_container_name_for_host(node.host)
        path = f"/containers/{url_quote(container_name, safe='')}/start"
        try:
            response = self._docker_unix_http("POST", path)
        except Exception as exc:
            return {"ok": False, "container": container_name, "error": str(exc)}
        ok = response.get("status_code") in {200, 204, 304}
        return {"ok": ok, "container": container_name, **response}

    def _docker_stop_container(self, node: WorkerNode) -> dict[str, Any]:
        sock_path = Path(self.settings.docker_socket_path)
        if not sock_path.exists():
            return {"ok": False, "skipped": True, "reason": f"Docker socket not found: {sock_path}"}
        container_name = node.container_name or self._default_container_name_for_host(node.host)
        path = f"/containers/{url_quote(container_name, safe='')}/stop?t={int(self.settings.container_stop_timeout_seconds)}"
        try:
            response = self._docker_unix_http("POST", path)
        except Exception as exc:
            return {"ok": False, "container": container_name, "error": str(exc)}
        ok = response.get("status_code") in {200, 204, 304}
        return {"ok": ok, "container": container_name, **response}

    def _connect_with_fallback(
        self,
        node: WorkerNode,
        *,
        target: str | None,
        attempts: list[dict[str, Any]],
        attempt: int | None = None,
        timeout_seconds: int | None = None,
        retry_after_disconnect: bool = True,
    ) -> tuple[bool, str | None]:
        if target and ".pia.com" in target.lower():
            if self._server_is_on_cooldown(target) or self._server_is_bad_target(target):
                return False, f"Server target is blocked by cooldown/blacklist: {target}"
        args = ["connect"]
        if target:
            args.append(target)
        connect_timeout = max(5, int(timeout_seconds or self.settings.cli_connect_timeout_seconds))
        cli = self._pia(node, args, timeout=connect_timeout)
        cli_ok = cli.exit_code == 0 or self._connect_output_indicates_success(cli.output)
        attempts.append(
            {
                **({"attempt": attempt} if attempt is not None else {}),
                "target": target or "quick-connect",
                "phase": "pia_connect_direct",
                "ok": cli_ok,
                "output": cli.output[-1200:],
            }
        )
        if cli_ok:
            return True, None
        if not retry_after_disconnect:
            return False, cli.output

        self._pia(node, ["disconnect"], timeout=self.settings.cli_disconnect_timeout_seconds)
        retry_cli = self._pia(node, args, timeout=connect_timeout)
        retry_ok = retry_cli.exit_code == 0 or self._connect_output_indicates_success(retry_cli.output)
        attempts.append(
            {
                **({"attempt": attempt} if attempt is not None else {}),
                "target": target or "quick-connect",
                "phase": "pia_connect_after_disconnect",
                "ok": retry_ok,
                "output": retry_cli.output[-1200:],
            }
        )
        if retry_ok:
            return True, None
        return False, retry_cli.output or cli.output

    def _docker_unix_http(self, method: str, path: str) -> dict[str, Any]:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(8)
            client.connect(str(self.settings.docker_socket_path))
            request = f"{method} {path} HTTP/1.1\r\nHost: docker\r\nUser-Agent: pia-watchdog\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            client.sendall(request.encode("utf-8"))
            chunks: list[bytes] = []
            while True:
                data = client.recv(65536)
                if not data:
                    break
                chunks.append(data)
        raw = b"".join(chunks).decode("utf-8", errors="replace")
        first = raw.splitlines()[0] if raw.splitlines() else ""
        match = re.search(r"HTTP/\d(?:\.\d)?\s+(\d+)", first)
        status_code = int(match.group(1)) if match else 0
        body = raw.split("\r\n\r\n", 1)[1] if "\r\n\r\n" in raw else ""
        return {"status_code": status_code, "status_line": first, "body": body[-1200:]}

    # ---------- Internal helpers ----------
    def _load_workers(self) -> list[WorkerNode]:
        raw = self.settings.proxy_workers_raw.strip()
        if not raw:
            raw = ",".join(f"worker{i}:vpn-worker-{i}:9000:1080" for i in range(1, 21))
        nodes: list[WorkerNode] = []
        for index, item in enumerate([part.strip() for part in raw.split(",") if part.strip()], start=1):
            parts = [p.strip() for p in item.split(":")]
            if len(parts) < 4:
                raise ValueError(f"Invalid PROXY_WORKERS item {item!r}. Expected id:host:control_port:socks_port[:country_hint[:container_name[:token_slot]]].")
            node_id, host, control_port, socks_port = parts[:4]
            country_hint = parts[4] if len(parts) >= 5 else ""
            container_name = parts[5] if len(parts) >= 6 else self._default_container_name_for_host(host)
            token_slot = int(parts[6]) if len(parts) >= 7 and parts[6] else 1
            nodes.append(
                WorkerNode(
                    id=node_id,
                    host=host,
                    control_port=int(control_port),
                    socks_port=int(socks_port),
                    haproxy_server=node_id,
                    country_hint=country_hint,
                    container_name=container_name,
                    token_slot=token_slot,
                )
            )
        if not nodes:
            raise ValueError("At least one proxy worker is required.")
        return nodes

    @staticmethod
    def _default_container_name_for_host(host: str) -> str:
        if host.startswith("vpn-worker-"):
            return "pia-worker-" + host.rsplit("-", 1)[-1]
        return host

    def _node(self, node_id: str) -> WorkerNode:
        needle = node_id.strip()
        for node in self.nodes:
            if node.id == needle or node.host == needle or node.haproxy_server == needle:
                return node
        raise ValueError(f"Unknown worker node: {node_id}")

    def _first_available_node(self) -> WorkerNode | None:
        for node in self._active_nodes():
            try:
                runtime = self._worker_request(node, "GET", "/runtime", timeout=3)
                if runtime.get("service_ready"):
                    return node
            except Exception:
                continue
        active = self._active_nodes()
        return active[0] if active else None

    def _worker_request(
        self,
        node: WorkerNode,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: int | float | None = None,
    ) -> dict[str, Any]:
        url = node.control_url + path
        headers = {}
        if self.settings.proxy_control_token:
            headers["x-proxy-control-token"] = self.settings.proxy_control_token
        with requests.Session() as session:
            session.trust_env = False
            res = session.request(method, url, json=payload, params=params, headers=headers, timeout=timeout or self.settings.proxy_control_timeout_seconds)
        try:
            data = res.json()
        except Exception:
            data = {"ok": False, "raw": res.text}
        if res.status_code >= 400:
            raise RuntimeError(f"{node.id} control {path} HTTP {res.status_code}: {data}")
        return data

    def _pia(self, node: WorkerNode, args: list[str], timeout: int | None = None) -> ExecResult:
        try:
            payload = {"args": args, "timeout": int(timeout or self.settings.cli_command_timeout_seconds)}
            data = self._worker_request(node, "POST", "/pia", payload=payload, timeout=(timeout or self.settings.cli_command_timeout_seconds) + 5)
            return ExecResult(exit_code=int(data.get("exit_code", 1)), output=str(data.get("output", "")))
        except Exception as exc:
            return ExecResult(exit_code=1, output=f"{type(exc).__name__}: {exc}")

    def _status_from_cli(self, node: WorkerNode) -> ExpressStatus:
        cli = self._pia(node, ["status"], timeout=self.settings.cli_command_timeout_seconds)
        return self._parse_express_status(cli.output)

    def _is_logged_in(self, node: WorkerNode) -> bool:
        runtime = self._worker_runtime(node)
        if runtime and runtime.get("logged_in"):
            return True
        cli = self._pia(node, ["status"], timeout=self.settings.cli_command_timeout_seconds)
        return self._account_output_indicates_logged_in(cli.output)

    @staticmethod
    def _split_account_credential(value: str) -> tuple[str, str]:
        raw = (value or "").strip()
        if not raw:
            raise ValueError("PIA account credential is empty.")
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                email = str(data.get("username") or data.get("email") or "").strip()
                password = str(data.get("password") or "").strip()
                if email and password:
                    return email, password
        except Exception:
            pass
        if "|" in raw:
            email, password = raw.split("|", 1)
            email = email.strip()
            password = password.strip()
            if email and password:
                return email, password
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if len(lines) >= 2:
            return lines[0], lines[1]
        raise ValueError("PIA account credential must be username/password, username|password, or JSON.")

    def _login_with_token(self, node: WorkerNode, token: str) -> ExecResult:
        username, password = self._split_account_credential(token)
        return self._pia(node, ["login", username, password], timeout=self.settings.pia_login_timeout_seconds)

    def _network_lock_enabled(self, node: WorkerNode) -> bool:
        return False

    def _pick_random_country(self, *, exclude: str | None = None, exclude_countries: set[str] | None = None) -> str | None:
        candidates = self._pick_country_candidates(exclude=exclude, exclude_countries=exclude_countries, limit=1)
        return candidates[0] if candidates else None

    def _pick_country_candidates(self, *, exclude: str | None = None, exclude_countries: set[str] | None = None, limit: int = 1) -> list[str]:
        data = self.countries(refresh=False)
        countries = [str(item).strip() for item in data.get("countries", []) if str(item).strip()]
        if not countries:
            return []
        excluded_keys = {self._normalize_country_key(item) for item in (exclude_countries or set()) if self._normalize_country_key(item)}
        if exclude:
            excluded_keys.add(self._normalize_country_key(exclude))
        if excluded_keys:
            filtered = [item for item in countries if self._normalize_country_key(item) not in excluded_keys]
            if filtered:
                countries = filtered
        preferred, deferred = self._split_country_candidates(countries)
        pool = preferred or deferred or countries
        return self._rank_country_candidates(pool)[: max(1, int(limit))]

    def _pick_least_attempted_country(self, countries: list[str]) -> str | None:
        ranked = self._rank_country_candidates(countries)
        return ranked[0] if ranked else None

    def _rank_country_candidates(self, countries: list[str]) -> list[str]:
        if not countries:
            return []
        ranked = []
        for country in countries:
            stats = self._get_country_stats(country)
            attempts = 0
            if stats:
                attempts = int(stats.get("successes", 0)) + int(stats.get("failures", 0))
            ranked.append((attempts, random.random(), country))
        ranked.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in ranked]

    def _countries_in_use(self, *, exclude_node_id: str | None = None) -> set[str]:
        countries: set[str] = set()
        for status in self.nodes_status(refresh=False):
            if not status.get("active"):
                continue
            if status.get("id") == exclude_node_id:
                continue
            country = str(status.get("country") or status.get("country_hint") or "").strip()
            if country:
                countries.add(country)
        return countries

    def _update_ready_state(
        self,
        node_id: str,
        *,
        service_ready: bool,
        connected: bool,
        current_ip: str | None,
        verified: bool,
        verification_error: str | None = None,
    ) -> bool:
        now = time.time()
        fail_fast = bool(
            self.settings.ready_proxy_failure_fail_fast
            and service_ready
            and connected
            and not verified
            and self._is_proxy_path_failure(verification_error)
        )
        if verified and current_ip:
            self._last_verified_ip[node_id] = current_ip
            self._last_verified_at[node_id] = now
            self._ready_success_streaks[node_id] = self._ready_success_streaks.get(node_id, 0) + 1
            self._ready_failure_streaks[node_id] = 0
        else:
            self._ready_success_streaks[node_id] = 0
            if service_ready and connected:
                self._ready_failure_streaks[node_id] = self._ready_failure_streaks.get(node_id, 0) + 1
                if fail_fast:
                    self._ready_failure_streaks[node_id] = max(
                        self.settings.ready_failure_threshold,
                        self._ready_failure_streaks[node_id],
                    )
            else:
                self._ready_failure_streaks[node_id] = max(
                    self.settings.ready_failure_threshold,
                    self._ready_failure_streaks.get(node_id, 0) + 1,
                )

        previous_ready = self._ready_state.get(node_id, False)
        if verified and self._ready_success_streaks[node_id] >= max(1, int(self.settings.ready_success_threshold)):
            self._ready_state[node_id] = True
            return True

        grace_deadline = float(self._last_verified_at.get(node_id, 0)) + max(0, int(self.settings.ready_verified_grace_seconds))
        in_grace = bool(service_ready and connected and previous_ready and grace_deadline > now)
        if in_grace and self._ready_failure_streaks[node_id] < max(1, int(self.settings.ready_failure_threshold)):
            self._ready_state[node_id] = True
            return True

        if self._ready_failure_streaks[node_id] >= max(1, int(self.settings.ready_failure_threshold)):
            self._ready_state[node_id] = False
        return self._ready_state.get(node_id, False)

    @staticmethod
    def _is_proxy_path_failure(error: str | None) -> bool:
        if not error:
            return False
        lowered = error.lower()
        patterns = (
            "general socks server failure",
            "socks server failure",
            "0x01",
            "connection refused",
            "failed to establish a new connection",
            "network is unreachable",
            "no route to host",
            "connection reset",
            "connection aborted",
        )
        return any(pattern in lowered for pattern in patterns)

    @staticmethod
    def _normalize_country_key(country: str | None) -> str | None:
        if not country:
            return None
        return country.strip().replace(" ", "_").lower() or None

    @staticmethod
    def _normalize_server_key(server: str | None) -> str | None:
        if not server:
            return None
        return server.strip().lower() or None

    @staticmethod
    def _extract_server_hostname(text: str | None) -> str | None:
        if not text:
            return None
        match = re.search(r"\b([a-z0-9.-]+\.pia\.com)\b", text, re.I)
        return match.group(1) if match else None

    def _get_country_stats(self, country: str | None) -> dict[str, Any] | None:
        key = self._normalize_country_key(country)
        if not key:
            return None
        return self._country_target_stats.get(key)

    def _ensure_country_stats(self, country: str | None) -> dict[str, Any] | None:
        key = self._normalize_country_key(country)
        if not key:
            return None
        return self._country_target_stats.setdefault(
            key,
            {
                "country": country,
                "successes": 0,
                "failures": 0,
                "consecutive_failures": 0,
                "cooldown_until": 0.0,
                "last_error": None,
                "last_failure_at": None,
                "last_success_at": None,
            },
        )

    def _record_country_result(self, country: str | None, *, ok: bool, error: str | None) -> None:
        stats = self._ensure_country_stats(country)
        if not stats:
            return
        now = time.time()
        stats["country"] = country
        if ok:
            stats["successes"] = int(stats.get("successes", 0)) + 1
            stats["consecutive_failures"] = 0
            stats["last_success_at"] = now
            stats["last_error"] = None
            stats["cooldown_until"] = 0.0
            return
        stats["failures"] = int(stats.get("failures", 0)) + 1
        stats["consecutive_failures"] = int(stats.get("consecutive_failures", 0)) + 1
        stats["last_failure_at"] = now
        stats["last_error"] = (error or "")[-500:]
        threshold = max(1, int(self.settings.target_failure_cooldown_threshold))
        if self.settings.target_failure_cooldown_enabled and int(stats["consecutive_failures"]) >= threshold:
            stats["cooldown_until"] = now + max(1, int(self.settings.target_failure_cooldown_seconds))

    def _country_is_on_cooldown(self, country: str | None, *, now: float | None = None) -> bool:
        stats = self._get_country_stats(country)
        if not stats:
            return False
        return float(stats.get("cooldown_until") or 0) > float(now if now is not None else time.time())

    def _country_is_bad_target(self, country: str | None) -> bool:
        if not self.settings.target_avoid_bad:
            return False
        stats = self._get_country_stats(country)
        if not stats:
            return False
        failures = int(stats.get("failures", 0))
        successes = int(stats.get("successes", 0))
        total = failures + successes
        if failures < int(self.settings.target_bad_failure_threshold) or total <= 0:
            return False
        success_rate = successes / total
        return success_rate < float(self.settings.target_bad_success_rate_threshold)

    def _split_country_candidates(self, countries: list[str]) -> tuple[list[str], list[str]]:
        preferred: list[str] = []
        deferred: list[str] = []
        now = time.time()
        for country in countries:
            if self._country_is_on_cooldown(country, now=now):
                continue
            if self._country_is_bad_target(country):
                deferred.append(country)
                continue
            preferred.append(country)
        if preferred:
            return preferred, deferred
        cooldown_free = [country for country in countries if not self._country_is_on_cooldown(country, now=now)]
        if cooldown_free:
            return [], cooldown_free
        return [], countries

    def _country_health_view(self, country: str | None) -> dict[str, Any] | None:
        stats = self._get_country_stats(country)
        if not stats:
            return None
        now = time.time()
        failures = int(stats.get("failures", 0))
        successes = int(stats.get("successes", 0))
        total = failures + successes
        return {
            "country": country,
            "successes": successes,
            "failures": failures,
            "consecutive_failures": int(stats.get("consecutive_failures", 0)),
            "success_rate": (successes / total) if total else None,
            "on_cooldown": self._country_is_on_cooldown(country, now=now),
            "cooldown_until": stats.get("cooldown_until"),
            "last_error": stats.get("last_error"),
            "marked_bad": self._country_is_bad_target(country),
        }

    def _country_target_snapshot(self) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}
        for key, stats in self._country_target_stats.items():
            view = self._country_health_view(str(stats.get("country") or key))
            if view:
                snapshot[key] = view
        return snapshot

    def _country_selection_summary(self, countries: list[str]) -> dict[str, Any]:
        preferred, deferred = self._split_country_candidates(countries)
        cooldown = [country for country in countries if self._country_is_on_cooldown(country)]
        return {
            "preferred": preferred,
            "deferred_bad_targets": deferred,
            "cooldown_blocked": cooldown,
        }

    def _get_server_stats(self, server: str | None) -> dict[str, Any] | None:
        key = self._normalize_server_key(server)
        if not key:
            return None
        return self._server_target_stats.get(key)

    def _ensure_server_stats(self, server: str | None) -> dict[str, Any] | None:
        key = self._normalize_server_key(server)
        if not key:
            return None
        return self._server_target_stats.setdefault(
            key,
            {
                "server": server,
                "successes": 0,
                "failures": 0,
                "consecutive_failures": 0,
                "cooldown_until": 0.0,
                "last_error": None,
                "last_failure_at": None,
                "last_success_at": None,
            },
        )

    def _record_server_result(self, server: str | None, *, ok: bool, error: str | None) -> None:
        stats = self._ensure_server_stats(server)
        if not stats:
            return
        now = time.time()
        stats["server"] = server
        if ok:
            stats["successes"] = int(stats.get("successes", 0)) + 1
            stats["consecutive_failures"] = 0
            stats["last_success_at"] = now
            stats["last_error"] = None
            stats["cooldown_until"] = 0.0
            return
        stats["failures"] = int(stats.get("failures", 0)) + 1
        stats["consecutive_failures"] = int(stats.get("consecutive_failures", 0)) + 1
        stats["last_failure_at"] = now
        stats["last_error"] = (error or "")[-500:]
        if self.settings.target_failure_cooldown_enabled and int(stats["consecutive_failures"]) >= max(1, int(self.settings.target_failure_cooldown_threshold)):
            stats["cooldown_until"] = now + max(1, int(self.settings.target_failure_cooldown_seconds))

    def _server_is_on_cooldown(self, server: str | None, *, now: float | None = None) -> bool:
        stats = self._get_server_stats(server)
        if not stats:
            return False
        return float(stats.get("cooldown_until") or 0) > float(now if now is not None else time.time())

    def _server_is_bad_target(self, server: str | None) -> bool:
        if not self.settings.server_target_avoid_bad:
            return False
        stats = self._get_server_stats(server)
        if not stats:
            return False
        failures = int(stats.get("failures", 0))
        successes = int(stats.get("successes", 0))
        total = failures + successes
        if failures < int(self.settings.target_bad_failure_threshold) or total <= 0:
            return False
        return (successes / total) < float(self.settings.target_bad_success_rate_threshold)

    def _server_health_view(self, server: str | None) -> dict[str, Any] | None:
        stats = self._get_server_stats(server)
        if not stats:
            return None
        now = time.time()
        failures = int(stats.get("failures", 0))
        successes = int(stats.get("successes", 0))
        total = failures + successes
        return {
            "server": server,
            "successes": successes,
            "failures": failures,
            "consecutive_failures": int(stats.get("consecutive_failures", 0)),
            "success_rate": (successes / total) if total else None,
            "on_cooldown": self._server_is_on_cooldown(server, now=now),
            "cooldown_until": stats.get("cooldown_until"),
            "last_error": stats.get("last_error"),
            "marked_bad": self._server_is_bad_target(server),
        }

    def _server_target_snapshot(self) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}
        for key, stats in self._server_target_stats.items():
            view = self._server_health_view(str(stats.get("server") or key))
            if view:
                snapshot[key] = view
        return snapshot

    def _schedule_next_auto_rotate(self, node_id: str, *, now: float | None = None) -> float:
        current = float(now if now is not None else time.time())
        minimum = max(1, int(self.settings.auto_rotate_interval_min_seconds))
        maximum = max(minimum, int(self.settings.auto_rotate_interval_max_seconds))
        next_at = current + random.randint(minimum, maximum)
        self._next_auto_rotate_at[node_id] = next_at
        return next_at

    def _wait_for_verified_ip(self, node: WorkerNode, max_seconds: int | float | None = None) -> tuple[str | None, int, str | None]:
        timeout = float(max_seconds if max_seconds is not None else self.settings.connect_timeout_seconds)
        deadline = time.time() + timeout
        started = time.perf_counter()
        last_error = None
        while time.time() < deadline:
            try:
                runtime = self._worker_request(node, "GET", "/runtime", timeout=min(3, self.settings.proxy_control_timeout_seconds))
            except Exception as exc:
                runtime = {}
                last_error = str(exc)
            if not runtime.get("connected"):
                last_error = last_error or "PIA route is not connected yet."
                time.sleep(self.settings.ip_check_interval_seconds)
                continue
            ip, err = self._current_ip(node)
            if ip:
                return ip, int((time.perf_counter() - started) * 1000), None
            last_error = err
            time.sleep(self.settings.ip_check_interval_seconds)
        return None, int((time.perf_counter() - started) * 1000), last_error or f"timeout after {timeout}s"

    def _current_ip(self, node: WorkerNode) -> tuple[str | None, str | None]:
        return self._ip_check_with_proxy(self._worker_proxy_url(node), timeout=self.settings.ip_check_timeout_seconds)

    def _gateway_current_ip(self) -> str | None:
        ip, _ = self._ip_check_with_proxy(self._gateway_proxy_url(), timeout=self.settings.ip_check_timeout_seconds)
        return ip

    def _cached_gateway_ip(self, ready_nodes: list[dict[str, Any]]) -> str | None:
        for item in ready_nodes:
            ip = item.get("current_ip") or self._last_verified_ip.get(str(item.get("id") or ""))
            if ip:
                return str(ip)
        for node_id, ip in self._last_verified_ip.items():
            if ip:
                return ip
        return None

    def _ip_check_with_proxy(self, proxy_url: str, *, timeout: int | float) -> tuple[str | None, str | None]:
        proxies = {"http": proxy_url, "https": proxy_url}
        last_error = None
        for endpoint in self.settings.ip_check_endpoints:
            try:
                res = requests.get(endpoint, proxies=proxies, timeout=timeout)
                if not res.ok:
                    last_error = f"{endpoint}: HTTP {res.status_code}"
                    continue
                text = res.text.strip()
                ip = None
                try:
                    data = res.json()
                    ip = data.get("ip") or data.get("query") or data.get("ip_addr")
                except Exception:
                    m = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)
                    ip = m.group(0) if m else None
                if ip:
                    return ip, None
                last_error = f"{endpoint}: could not parse IP"
            except Exception as exc:
                last_error = f"{endpoint}: {exc}"
        return None, last_error

    def _worker_proxy_url(self, node: WorkerNode) -> str:
        auth = self._proxy_auth_fragment()
        return f"socks5h://{auth}{node.host}:{node.socks_port}"

    def _gateway_proxy_url(self) -> str:
        auth = self._proxy_auth_fragment()
        # Inside Docker, use proxy-gateway service. From host, users use PROXY_HOST:PROXY_PORT.
        return f"socks5h://{auth}proxy-gateway:{self.settings.socks5_port}"

    def _public_proxy(self, *, mask: bool) -> str:
        from urllib.parse import quote

        user = quote(self.settings.socks5_username, safe="")
        password = "***" if mask and self.settings.socks5_password else quote(self.settings.socks5_password, safe="")
        auth = f"{user}:{password}@" if user or self.settings.socks5_password else ""
        return f"socks5h://{auth}{self.settings.proxy_host}:{self.settings.proxy_port}"

    def _proxy_auth_fragment(self) -> str:
        from urllib.parse import quote

        user = quote(self.settings.socks5_username, safe="")
        password = quote(self.settings.socks5_password, safe="")
        return f"{user}:{password}@" if user or password else ""

    def _disable_node(self, node: WorkerNode, *, reason: str) -> dict[str, Any]:
        if self._active_gateway_node_id == node.id:
            self._active_gateway_node_id = None
        return self._haproxy_command(f"disable server socks5_workers/{node.haproxy_server}", node=node, reason=reason)

    def _enable_node(self, node: WorkerNode, *, reason: str) -> dict[str, Any]:
        return self._haproxy_command(f"enable server socks5_workers/{node.haproxy_server}", node=node, reason=reason)

    def _set_single_active_gateway(self, node: WorkerNode, *, reason: str) -> dict[str, Any]:
        results = []
        for other in self.nodes:
            if other.id == node.id:
                continue
            results.append(self._disable_node(other, reason=reason))
        results.append(self._enable_node(node, reason=reason))
        self._active_gateway_node_id = node.id
        return {"ok": all(bool(item.get("ok")) for item in results), "active_node_id": node.id, "results": results}

    def _promote_ready_gateway_worker(self, *, exclude_node_id: str | None = None, reason: str) -> dict[str, Any] | None:
        nodes = self.nodes_status(refresh=True)
        ready = [n for n in nodes if n.get("ready") and n.get("id") != exclude_node_id]
        if not ready:
            return None
        preferred = next((item for item in ready if item["id"] == self._active_gateway_node_id), None)
        selected = preferred or ready[0]
        return self._set_single_active_gateway(self._node(selected["id"]), reason=reason)

    def _promote_verified_standby_for_rotation(self, node_id: str) -> dict[str, Any] | None:
        nodes = self.nodes_status(refresh=True)
        candidates = [
            n
            for n in nodes
            if n.get("id") != node_id and n.get("ready") and n.get("verified") and n.get("service_ready") and n.get("connected")
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: (
                self._rotation_counts.get(item["id"], 0),
                self._last_rotation_at.get(item["id"], 0) or 0,
                0 if item.get("gateway_enabled") else 1,
                item["id"],
            )
        )
        selected = candidates[0]
        promote = self._set_single_active_gateway(self._node(selected["id"]), reason="rotate_promote_verified_standby")
        if not promote.get("ok"):
            return promote
        stable_seconds = max(0, int(self.settings.rotate_promote_stable_seconds))
        if stable_seconds:
            deadline = time.time() + stable_seconds
            while time.time() < deadline:
                status = self.node_status(selected["id"])
                if not (status.get("ready") and status.get("verified") and status.get("connected")):
                    return {
                        "ok": False,
                        "active_node_id": selected["id"],
                        "error": f"Standby worker {selected['id']} lost readiness during promotion stabilization.",
                    }
                time.sleep(1)
        return {
            "ok": True,
            "active_node_id": selected["id"],
            "stable_seconds": stable_seconds,
            "selection_mode": "verified_standby_before_rotate",
        }

    def _sync_single_active_gateway(self, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        ready = [n for n in nodes if n.get("ready")]
        if not ready:
            self._active_gateway_node_id = None
            return {"ok": False, "reason": "no_ready_workers", "active_node_id": None}
        preferred = next((item for item in ready if item["id"] == self._active_gateway_node_id), None)
        selected = preferred or ready[0]
        return self._set_single_active_gateway(self._node(selected["id"]), reason="health_tick_single_active")

    def _sync_ready_gateway_pool(self, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        active_ids = {node.id for node in self._active_nodes()}
        ready_ids = {n["id"] for n in nodes if n.get("active") and n.get("ready")}
        results = []
        for node in self.nodes:
            if node.id in ready_ids and node.id in active_ids:
                results.append(self._enable_node(node, reason="health_tick_ready_pool"))
            else:
                results.append(self._disable_node(node, reason="health_tick_ready_pool"))
        if ready_ids:
            preferred = next((n["id"] for n in nodes if n.get("id") == self._active_gateway_node_id and n.get("ready")), None)
            self._active_gateway_node_id = preferred or next(iter(ready_ids))
        else:
            self._active_gateway_node_id = None
        return {
            "ok": len(ready_ids) >= self._effective_min_ready_workers(),
            "mode": "ready_pool",
            "active_node_id": self._active_gateway_node_id,
            "enabled_nodes": sorted(list(ready_ids)),
            "results": results,
        }

    def _haproxy_command(self, command: str, *, node: WorkerNode | None = None, reason: str | None = None) -> dict[str, Any]:
        sock_path = Path(self.settings.haproxy_runtime_socket)
        if not sock_path.exists():
            return {"ok": False, "command": command, "error": f"HAProxy socket not found: {sock_path}", "node_id": node.id if node else None, "reason": reason}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(3)
                client.connect(str(sock_path))
                client.sendall((command.strip() + "\n").encode("utf-8"))
                chunks = []
                while True:
                    try:
                        data = client.recv(65536)
                    except socket.timeout:
                        break
                    if not data:
                        break
                    chunks.append(data)
            output = b"".join(chunks).decode("utf-8", errors="replace")
            return {"ok": True, "command": command, "output": output, "node_id": node.id if node else None, "reason": reason}
        except Exception as exc:
            return {"ok": False, "command": command, "error": str(exc), "node_id": node.id if node else None, "reason": reason}

    def _haproxy_enabled_servers(self) -> dict[str, bool | None]:
        result: dict[str, bool | None] = {node.haproxy_server: None for node in self.nodes}
        stat = self._haproxy_command("show stat")
        if not stat.get("ok"):
            return result
        text = stat.get("output", "")
        for line in str(text).splitlines():
            if not line or line.startswith("#"):
                continue
            cols = line.split(",")
            if len(cols) < 16:
                continue
            pxname, svname, status = cols[0], cols[1], cols[17]
            if pxname == "socks5_workers" and svname in result:
                # MAINT means manually disabled. UP/DOWN still can be enabled in config.
                result[svname] = status.upper() != "MAINT"
        return result

    def _enforce_rotation_cooldown(self, node_id: str) -> None:
        min_seconds = max(0, self.settings.min_seconds_between_rotations)
        last = self._last_rotation_at.get(node_id)
        if min_seconds and last and time.time() - last < min_seconds:
            raise RuntimeError(f"Worker {node_id} rotated too recently. Wait {min_seconds - int(time.time() - last)}s.")

    def _tcp_connect(self, host: str, port: int, *, timeout: int | float) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except Exception:
            return False

    @staticmethod
    def _parse_key_value_output(text: str) -> dict[str, str]:
        data: dict[str, str] = {}
        for line in text.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            data[key.strip().lower()] = value.strip()
        return data

    @staticmethod
    def _parse_duration_seconds(text: str | None) -> int | None:
        if not text:
            return None
        total = 0
        matched = False
        for amount, unit in re.findall(r"(\d+)\s*([A-Za-z]+)", text):
            matched = True
            value = int(amount)
            unit = unit.lower()
            if unit.startswith("day"):
                total += value * 86400
            elif unit.startswith("hour"):
                total += value * 3600
            elif unit.startswith("minute"):
                total += value * 60
            elif unit.startswith("second"):
                total += value
        return total if matched else None

    @classmethod
    def _parse_express_status(cls, text: str) -> ExpressStatus:
        cleaned = re.sub(r"\x1b\[[0-9;]*m", "", text or "")
        lowered = cleaned.lower()
        disconnected = bool(re.search(r"connected:\s*false|not[ -]*(connected|protected)|disconnected|not[ -]*(logged|signed)[ -]*in|sign[ -]*in|required", lowered))
        connected = not disconnected and bool(re.search(r"connected:\s*true|\bconnected\b|\bprotected\b", lowered))
        data = cls._parse_key_value_output(cleaned)
        uptime = data.get("uptime")
        location = (
            data.get("location")
            or data.get("server location")
            or data.get("vpn location")
            or data.get("connected location")
            or data.get("region")
        )
        match = re.search(r"connected\s+to\s+(.+?)(?:\.|\n|$)", cleaned, re.I)
        if not location and match:
            location = match.group(1).strip()
        country = data.get("country")
        city = data.get("city")
        if location and not country:
            parts = [part.strip() for part in re.split(r"\s+-\s+", location) if part.strip()]
            country = parts[0] if parts else location
            city = parts[1] if len(parts) > 1 else None
        return ExpressStatus(
            connected=connected,
            raw=cleaned,
            country=country,
            city=city,
            server=data.get("server") or location,
            hostname=data.get("hostname") or data.get("vpnip") or data.get("vpn ip"),
            technology=data.get("current technology") or data.get("technology"),
            protocol=data.get("current protocol") or data.get("protocol"),
            uptime=uptime,
            uptime_seconds=cls._parse_duration_seconds(uptime),
        )

    @staticmethod
    def _account_output_indicates_logged_in(text: str) -> bool:
        cleaned = (text or "").strip()
        if not cleaned:
            return False
        lowered = cleaned.lower()
        if re.search(r"connected\s*:\s*true", lowered, re.I):
            return True
        if re.search(r"not[ -]*(logged|signed)[ -]*in|please\s+log\s+in|please\s+login|sign[ -]*in|required|activation", lowered, re.I):
            return False
        if "account information" in lowered:
            return True
        if re.search(r"email(?:\s+address)?\s*:", lowered, re.I):
            return True
        if re.search(r"subscription\s*:", lowered, re.I):
            return True
        return False

    @staticmethod
    def _connect_output_indicates_success(text: str) -> bool:
        lowered = (text or "").lower()
        return "you are connected" in lowered or "connected to" in lowered or "protected" in lowered or bool(re.search(r"(status|connectionstate)\s*:\s*connected", lowered, re.I))

    @staticmethod
    def _parse_countries_output(text: str) -> list[str]:
        # piactl get regions prints region names line-by-line.
        cleaned = re.sub(r"\x1b\[[0-9;]*m", "", text or "")
        tokens: list[str] = []
        for part in re.split(r"[\n\r]+", cleaned):
            item = part.strip().strip("-•*")
            if not item:
                continue
            if re.search(r"^(name|regions?|locations?|recommended|all locations|smart location)\b", item, re.I):
                continue
            if len(item) > 80:
                continue
            if re.search(r"[A-Za-z]", item):
                tokens.append(re.sub(r"\s+", " ", item))
        seen = set()
        out = []
        for token in tokens:
            if token.lower() not in seen:
                out.append(token)
                seen.add(token.lower())
        return out

    def _required_token_slots(self) -> list[int]:
        return sorted({max(1, int(node.token_slot)) for node in self._active_nodes()})

    def _token_path_for_slot(self, slot: int) -> Path:
        if int(slot) == 2:
            return self.settings.pia_token_path_2
        return self.settings.pia_token_path

    def _env_token_for_slot(self, slot: int) -> str:
        if int(slot) == 2:
            return self.settings.pia_token_2
        return self.settings.pia_token

    def _login_tokens_by_slot(self, token: str, token_2: str | None) -> dict[int, str]:
        tokens = {1: (token or "").strip()}
        if token_2 is not None:
            tokens[2] = token_2.strip()
        for slot in self._required_token_slots():
            if slot == 1:
                continue
            if slot not in tokens:
                tokens[slot] = self._env_token_for_slot(slot).strip() or self._read_stored_token(slot=slot)
            if not tokens[slot]:
                tokens[slot] = tokens[1]
        return tokens

    def _auth_summary(self, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        groups = []
        for slot in self._required_token_slots():
            slot_nodes = [n for n in nodes if int(n.get("token_slot") or 1) == slot]
            logged_in = sum(1 for n in slot_nodes if n.get("logged_in"))
            groups.append(
                {
                    "slot": slot,
                    "workers": len(slot_nodes),
                    "logged_in_workers": logged_in,
                    "all_logged_in": bool(slot_nodes) and logged_in == len(slot_nodes),
                    "stored_token": bool(self._read_stored_token(slot=slot) or self._env_token_for_slot(slot)),
                    "stored_account": bool(self._read_stored_token(slot=slot) or self._env_token_for_slot(slot)),
                }
            )
        return {
            "tokens_required": len(groups),
            "all_logged_in": bool(groups) and all(g["all_logged_in"] for g in groups),
            "groups": groups,
        }

    def _read_stored_token(self, *, slot: int = 1) -> str:
        try:
            return self._token_path_for_slot(slot).read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def _write_stored_token(self, token: str, *, slot: int = 1) -> None:
        path = self._token_path_for_slot(slot)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token.strip() + "\n", encoding="utf-8")
        self._relax_runtime_file_permissions(path, mode=0o660)

    def _clear_stored_token(self, *, slot: int = 1) -> None:
        try:
            self._token_path_for_slot(slot).unlink(missing_ok=True)
        except Exception:
            pass

    def _clear_stored_tokens(self) -> None:
        for slot in {1, 2, *self._required_token_slots()}:
            self._clear_stored_token(slot=slot)

    @staticmethod
    def _redact_sensitive(text: str) -> str:
        text = text or ""
        text = re.sub(r"--token\s+\S+", "--token ***", text)
        text = re.sub(r"(?i)(token\s*[=:]\s*)\S+", r"\1***", text)
        text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "***", text)
        text = re.sub(r"(?i)(password\s*[=:]\s*)\S+", r"\1***", text)
        text = re.sub(r"\b[A-Z0-9]{20,}\b", "***", text)
        text = re.sub(r"\bp\d{7,}\b", "***", text, flags=re.I)
        text = re.sub(r"(?i)(email address:\s*)[^\s]+", r"\1***", text)
        text = re.sub(r"(?i)(username\s*[:=]\s*)[^\s]+", r"\1***", text)
        return text

    def _read_sessions(self) -> dict[str, str]:
        with self._sessions_lock:
            try:
                return json.loads(self._session_bindings_path.read_text(encoding="utf-8"))
            except Exception:
                return {}

    def _write_sessions(self, sessions: dict[str, str]) -> None:
        with self._sessions_lock:
            self._session_bindings_path.parent.mkdir(parents=True, exist_ok=True)
            self._session_bindings_path.write_text(json.dumps(sessions, indent=2, ensure_ascii=False), encoding="utf-8")
            self._relax_runtime_file_permissions(self._session_bindings_path, mode=0o664)

    @staticmethod
    def _relax_runtime_file_permissions(path: Path, *, mode: int) -> None:
        try:
            parent_stat = path.parent.stat()
            os.chown(path, parent_stat.st_uid, parent_stat.st_gid)
        except Exception:
            pass
        try:
            os.chmod(path, mode)
        except Exception:
            pass
