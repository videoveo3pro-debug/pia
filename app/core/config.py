from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on", "enable", "enabled"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


def _float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return float(value)


def _csv(name: str, default: str = "") -> list[str]:
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def _worker_count() -> int:
    value = (os.getenv("WORKER_COUNT") or os.getenv("WORKER_MODE") or "14").strip().lower()
    try:
        iv = int(value)
        if iv >= 14:
            return 14
        if iv >= 8:
            return iv
        return 8
    except ValueError:
        pass
    return 14


def _default_proxy_workers(count: int | None = None) -> str:
    total = min(count or _int("MAX_WORKER_COUNT", 14), 14)
    workers = []
    for i in range(1, total + 1):
        country = os.getenv(f"WORKER_{i}_COUNTRY", "").strip()
        if country.lower() in {"", "random", "__random__", "any", "all"}:
            workers.append(f"worker{i}:vpn-worker-{i}:9000:1080")
        else:
            workers.append(f"worker{i}:vpn-worker-{i}:9000:1080:{country}")
    return ",".join(workers)


def _proxy_workers_raw() -> str:
    value = os.getenv("PROXY_WORKERS", "").strip()
    if value and value.lower() not in {"auto", "default"}:
        return value
    return _default_proxy_workers()


@dataclass(frozen=True)
class Settings:
    # PIA CLI auth. Values are packed as "username\\npassword" internally.
    pia_token: str = os.getenv("PIA_ACCOUNT", os.getenv("PIA_TOKEN", ""))
    pia_token_2: str = os.getenv("PIA_ACCOUNT_2", os.getenv("PIA_TOKEN_2", ""))
    pia_username: str = os.getenv("PIA_USERNAME", "")
    pia_password: str = os.getenv("PIA_PASSWORD", "")
    pia_token_storage_enabled: bool = _bool("PIA_ACCOUNT_STORAGE_ENABLED", _bool("PIA_TOKEN_STORAGE_ENABLED", True))
    pia_token_path: Path = Path(os.getenv("PIA_ACCOUNT_PATH", os.getenv("PIA_TOKEN_PATH", "/app/credentials/pia_account_1")))
    pia_token_path_2: Path = Path(os.getenv("PIA_ACCOUNT_PATH_2", os.getenv("PIA_TOKEN_PATH_2", "/app/credentials/pia_account_2")))
    pia_login_timeout_seconds: int = _int("PIA_LOGIN_TIMEOUT_SECONDS", 60)

    # Countries are now optional hints. No configs/.ovpn files are required.
    pia_countries: list[str] = None  # type: ignore[assignment]
    pia_default_country: str = os.getenv("PIA_DEFAULT_COUNTRY", "")
    pia_connect_target: str = os.getenv("PIA_CONNECT_TARGET", "")
    pia_discover_countries: bool = _bool("PIA_DISCOVER_COUNTRIES", True)
    # all/cli = use every location returned by `piactl get regions` for random rotation.
    # env = only use PIA_COUNTRIES. auto = cli when available, otherwise env fallback.
    pia_country_source: str = os.getenv("PIA_COUNTRY_SOURCE", "all").strip().lower()
    pia_country_cache_ttl_seconds: int = _int("PIA_COUNTRY_CACHE_TTL_SECONDS", 3600)

    # PIA CLI runtime settings.
    pia_technology: str = os.getenv("PIA_TECHNOLOGY", "")
    pia_protocol: str = os.getenv("PIA_PROTOCOL", "auto")
    pia_killswitch: bool = _bool("PIA_NETWORK_LOCK", False)
    pia_lan_discovery: bool = _bool("PIA_LAN_DISCOVERY", True)
    pia_whitelist_socks_port: bool = _bool("PIA_WHITELIST_SOCKS_PORT", False)
    pia_threat_protection_lite: bool = _bool("PIA_THREAT_PROTECTION_LITE", False)
    pia_post_quantum: bool = _bool("PIA_POST_QUANTUM", False)
    pia_meshnet: bool = _bool("PIA_MESHNET", False)
    pia_obfuscate: bool = _bool("PIA_OBFUSCATE", False)
    pia_autoconnect: bool = _bool("PIA_AUTOCONNECT", False)
    pia_autoconnect_target: str = os.getenv("PIA_AUTOCONNECT_TARGET", "")
    pia_dns: list[str] = None  # type: ignore[assignment]
    pia_allowlist_ports: list[str] = None  # type: ignore[assignment]
    pia_allowlist_subnets: list[str] = None  # type: ignore[assignment]

    socks5_username: str = os.getenv("SOCKS5_USERNAME", "")
    socks5_password: str = os.getenv("SOCKS5_PASSWORD", "")
    socks5_port: int = _int("SOCKS5_PORT", 1080)

    # SOCKS5-only mode. HTTP proxy was intentionally removed to keep the runtime simple and stable.

    proxy_host: str = os.getenv("PROXY_HOST", "127.0.0.1")
    proxy_port: int = _int("PROXY_PORT", 1087)
    proxy_service_host: str = os.getenv("PROXY_SERVICE_HOST", "proxy")
    proxy_control_port: int = _int("PROXY_CONTROL_PORT", 9000)
    proxy_control_token: str = os.getenv("PROXY_CONTROL_TOKEN", "")
    proxy_control_timeout_seconds: int = _int("PROXY_CONTROL_TIMEOUT_SECONDS", 10)

    # Multi-worker gateway mode. PROXY_WORKERS format:
    # id:service_host:control_port:socks_port[:startup_country],...
    worker_count: int = _worker_count()
    max_worker_count: int = min(_int("MAX_WORKER_COUNT", 14), 14)
    proxy_workers_raw: str = _proxy_workers_raw()
    runtime_mode_path: Path = Path(os.getenv("RUNTIME_MODE_PATH", "/app/credentials/runtime_mode.json"))
    haproxy_runtime_socket: Path = Path(os.getenv("HAPROXY_RUNTIME_SOCKET", "/run/haproxy/admin.sock"))
    min_ready_workers: int = _int("MIN_READY_WORKERS", 3)
    gateway_target_failover_seconds: int = _int("GATEWAY_TARGET_FAILOVER_SECONDS", 10)


    # API security and operations hardening. Defaults keep local development easy;
    # enable API_AUTH_ENABLED=true + API_TOKEN=... before exposing outside localhost.
    api_auth_enabled: bool = _bool("API_AUTH_ENABLED", False)
    api_token: str = os.getenv("API_TOKEN", "")
    api_auth_exempt_paths: list[str] = None  # type: ignore[assignment]
    cors_allow_origins: list[str] = None  # type: ignore[assignment]
    mask_proxy_password_in_status: bool = _bool("MASK_PROXY_PASSWORD_IN_STATUS", True)

    # Rotation/rate control.
    min_seconds_between_rotations: int = _int("MIN_SECONDS_BETWEEN_ROTATIONS", 5)
    auto_rotate_enabled: bool = _bool("AUTO_ROTATE_ENABLED", True)
    auto_rotate_interval_seconds: int = _int("AUTO_ROTATE_INTERVAL_SECONDS", 1800)
    auto_rotate_interval_min_seconds: int = _int("AUTO_ROTATE_INTERVAL_MIN_SECONDS", 36)
    auto_rotate_interval_max_seconds: int = _int("AUTO_ROTATE_INTERVAL_MAX_SECONDS", 69)
    auto_rotate_min_ready_workers: int = _int("AUTO_ROTATE_MIN_READY_WORKERS", 2)
    auto_rotate_max_parallel: int = _int("AUTO_ROTATE_MAX_PARALLEL", 4)
    auto_rotate_max_parallel_per_token: int = _int("AUTO_ROTATE_MAX_PARALLEL_PER_TOKEN", 2)
    auto_rotate_target_attempts: int = _int("AUTO_ROTATE_TARGET_ATTEMPTS", 2)
    auto_rotate_connect_timeout_seconds: int = _int("AUTO_ROTATE_CONNECT_TIMEOUT_SECONDS", 20)
    auto_rotate_max_uptime_seconds: int = _int("AUTO_ROTATE_MAX_UPTIME_SECONDS", 150)
    auto_rotate_country: str = os.getenv("AUTO_ROTATE_COUNTRY", "")
    auto_rotate_server: str = os.getenv("AUTO_ROTATE_SERVER", "")

    # Runtime metrics / support bundle.
    metrics_path: Path = Path(os.getenv("METRICS_PATH", "/app/credentials/runtime_metrics.json"))
    metrics_events_max: int = _int("METRICS_EVENTS_MAX", 1000)
    support_bundle_tail_lines: int = _int("SUPPORT_BUNDLE_TAIL_LINES", 200)

    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = _int("API_PORT", 8007)

    credentials_container_path: Path = Path(os.getenv("CREDENTIALS_CONTAINER_PATH", "/app/credentials"))

    proxy_image: str = os.getenv("PROXY_IMAGE", "piactl-socks5-proxy:local")
    # Bump this whenever the proxy image runtime changes. Backend uses it to
    # auto-rebuild old local images and recreate old containers.
    proxy_image_version: str = os.getenv("PROXY_IMAGE_VERSION", "2026-08-08-piactl-v1")
    proxy_container_name: str = os.getenv("PROXY_CONTAINER_NAME", "piactl-socks5-proxy")
    docker_network: str = os.getenv("DOCKER_NETWORK", "pia_proxy_net")
    auto_build_proxy_image: bool = _bool("AUTO_BUILD_PROXY_IMAGE", True)
    proxy_build_context: Path = Path(os.getenv("PROXY_BUILD_CONTEXT", "/app"))
    proxy_dockerfile: str = os.getenv("PROXY_DOCKERFILE", "app/docker/proxy/Dockerfile")

    health_interval_seconds: int = _int("HEALTH_INTERVAL_SECONDS", 5)
    auto_reconnect: bool = _bool("AUTO_RECONNECT", True)

    # Worker self-healing/watchdog. The backend keeps unhealthy workers out of
    # HAProxy, then tries reconnect -> worker restart -> Docker restart.
    worker_recovery_enabled: bool = _bool("WORKER_RECOVERY_ENABLED", True)
    worker_recovery_connect_after_failures: int = _int("WORKER_RECOVERY_CONNECT_AFTER_FAILURES", 1)
    worker_recovery_restart_after_failures: int = _int("WORKER_RECOVERY_RESTART_AFTER_FAILURES", 3)
    worker_recovery_docker_restart_after_failures: int = _int("WORKER_RECOVERY_DOCKER_RESTART_AFTER_FAILURES", 5)
    worker_recovery_cooldown_seconds: int = _int("WORKER_RECOVERY_COOLDOWN_SECONDS", 15)
    worker_recovery_verify_seconds: int = _int("WORKER_RECOVERY_VERIFY_SECONDS", 12)
    worker_recovery_connect_max_attempts: int = _int("WORKER_RECOVERY_CONNECT_MAX_ATTEMPTS", 1)
    worker_recovery_max_parallel: int = _int("WORKER_RECOVERY_MAX_PARALLEL", 4)
    docker_recovery_enabled: bool = _bool("DOCKER_RECOVERY_ENABLED", True)
    docker_socket_path: Path = Path(os.getenv("DOCKER_SOCKET_PATH", "/var/run/docker.sock"))
    ready_success_threshold: int = _int("READY_SUCCESS_THRESHOLD", 1)
    ready_failure_threshold: int = _int("READY_FAILURE_THRESHOLD", 3)
    ready_verified_grace_seconds: int = _int("READY_VERIFIED_GRACE_SECONDS", 30)
    ready_proxy_failure_fail_fast: bool = _bool("READY_PROXY_FAILURE_FAIL_FAST", True)
    rotate_promote_stable_seconds: int = _int("ROTATE_PROMOTE_STABLE_SECONDS", 4)

    # CLI and IP verification timeouts. With CLI, we no longer recreate the
    # container for every change; reconnect is usually faster than .ovpn mode.
    cli_command_timeout_seconds: int = _int("CLI_COMMAND_TIMEOUT_SECONDS", 20)
    cli_connect_timeout_seconds: int = _int("CLI_CONNECT_TIMEOUT_SECONDS", 45)
    cli_disconnect_timeout_seconds: int = _int("CLI_DISCONNECT_TIMEOUT_SECONDS", 15)
    connect_timeout_seconds: int = _int("CONNECT_TIMEOUT_SECONDS", 60)
    ip_check_timeout_seconds: int = _int("IP_CHECK_TIMEOUT_SECONDS", 4)
    ip_check_interval_seconds: float = _float("IP_CHECK_INTERVAL_SECONDS", 1.2)
    ip_check_endpoints: list[str] = None  # type: ignore[assignment]

    # Multiple CLI reconnect attempts. This replaces .ovpn fallback.
    pia_connect_max_attempts: int = _int("PIA_CONNECT_MAX_ATTEMPTS", 5)
    require_new_ip_on_change: bool = _bool("REQUIRE_NEW_IP_ON_CHANGE", True)
    least_used_retry_enabled: bool = _bool("LEAST_USED_RETRY_ENABLED", True)
    max_existing_ip_use_count_delta: int = _int("MAX_EXISTING_IP_USE_COUNT_DELTA", 0)

    # Container lifecycle. Container is kept alive; recreate only when missing/broken.
    container_stop_timeout_seconds: int = _int("CONTAINER_STOP_TIMEOUT_SECONDS", 5)
    container_recreate_delay_seconds: float = _float("CONTAINER_RECREATE_DELAY_SECONDS", 0.2)

    # Cooldown/bad-target tracking. With CLI we track requested targets and the
    # actual PIA server hostname reported by `pia status` when available.
    target_failure_cooldown_enabled: bool = _bool("TARGET_FAILURE_COOLDOWN_ENABLED", True)
    target_failure_cooldown_seconds: int = _int("TARGET_FAILURE_COOLDOWN_SECONDS", 900)
    target_failure_cooldown_threshold: int = _int("TARGET_FAILURE_COOLDOWN_THRESHOLD", 2)
    target_bad_failure_threshold: int = _int("TARGET_BAD_FAILURE_THRESHOLD", 4)
    target_bad_success_rate_threshold: float = _float("TARGET_BAD_SUCCESS_RATE_THRESHOLD", 0.25)
    target_avoid_bad: bool = _bool("TARGET_AVOID_BAD", True)
    server_target_avoid_bad: bool = _bool("SERVER_TARGET_AVOID_BAD", True)
    auto_rotate_pause_ready_threshold: int = _int("AUTO_ROTATE_PAUSE_READY_THRESHOLD", 4)

    ip_selection_strategy: str = os.getenv("IP_SELECTION_STRATEGY", "least_used_ip").strip().lower()
    ip_usage_history_enabled: bool = _bool("IP_USAGE_HISTORY_ENABLED", True)
    ip_usage_history_path: Path = Path(os.getenv("IP_USAGE_HISTORY_PATH", "/app/credentials/ip_usage.json"))
    ip_usage_randomize_ties: bool = _bool("IP_USAGE_RANDOMIZE_TIES", True)

    def __post_init__(self) -> None:
        object.__setattr__(self, "pia_countries", _csv("PIA_COUNTRIES", ""))
        object.__setattr__(self, "pia_dns", _csv("PIA_DNS", ""))
        default_allow_ports = str(self.socks5_port)
        object.__setattr__(self, "pia_allowlist_ports", _csv("PIA_ALLOWLIST_PORTS", default_allow_ports if self.pia_whitelist_socks_port else ""))
        object.__setattr__(self, "pia_allowlist_subnets", _csv("PIA_ALLOWLIST_SUBNETS", ""))
        object.__setattr__(self, "api_auth_exempt_paths", _csv("API_AUTH_EXEMPT_PATHS", "/,/static,/healthz,/api-docs,/docs,/openapi.json"))
        object.__setattr__(self, "cors_allow_origins", _csv("CORS_ALLOW_ORIGINS", ""))
        object.__setattr__(
            self,
            "ip_check_endpoints",
            _csv(
                "IP_CHECK_ENDPOINTS",
                "https://api.ipify.org?format=json,https://ipinfo.io/json,https://ifconfig.me/all.json",
            ),
        )

    def validate_required(self) -> None:
        # Backend can start without a token so the web UI can be used to login later.
        # PIA CLI authentication is checked by /api/status, /api/login and diagnostics.
        return None

    @property
    def internal_proxy_url(self) -> str:
        user = quote(self.socks5_username, safe="")
        password = quote(self.socks5_password, safe="")
        auth = f"{user}:{password}@" if user or password else ""
        return f"socks5h://{auth}{self.settings_proxy_internal_host}:{self.socks5_port}"

    @property
    def settings_proxy_internal_host(self) -> str:
        return self.proxy_service_host

    @property
    def proxy_control_url(self) -> str:
        return f"http://{self.proxy_service_host}:{self.proxy_control_port}"

    @property
    def public_proxy_url(self) -> str:
        user = quote(self.socks5_username, safe="")
        password = quote(self.socks5_password, safe="")
        auth = f"{user}:{password}@" if user or password else ""
        return f"socks5h://{auth}{self.proxy_host}:{self.proxy_port}"

    @property
    def public_proxy_url_masked(self) -> str:
        user = quote(self.socks5_username, safe="")
        auth = f"{user}:***@" if user or self.socks5_password else ""
        return f"socks5h://{auth}{self.proxy_host}:{self.proxy_port}"



settings = Settings()
