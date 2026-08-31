from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class IPCheckResult:
    ok: bool
    ip: str | None
    latency_ms: int
    endpoint: str | None
    error: str | None = None


class IPChecker:
    def __init__(self, proxy_url: str, timeout: int = 6, endpoints: list[str] | None = None) -> None:
        self.proxy_url = proxy_url
        self.timeout = timeout
        self.endpoints = endpoints or [
            "https://api.ipify.org?format=json",
            "https://ipinfo.io/json",
            "https://ifconfig.me/all.json",
        ]

    def check(self) -> IPCheckResult:
        proxies = {
            "http": self.proxy_url,
            "https": self.proxy_url,
        }
        start = time.perf_counter()
        last_error: str | None = None
        for url in self.endpoints:
            try:
                response = requests.get(url, proxies=proxies, timeout=self.timeout)
                response.raise_for_status()
                ip = self._extract_ip(response)
                latency_ms = int((time.perf_counter() - start) * 1000)
                if ip:
                    return IPCheckResult(ok=True, ip=ip, latency_ms=latency_ms, endpoint=url)
                last_error = f"No IP field in response from {url}"
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                continue
        latency_ms = int((time.perf_counter() - start) * 1000)
        return IPCheckResult(ok=False, ip=None, latency_ms=latency_ms, endpoint=None, error=last_error)

    def current_ip(self) -> str | None:
        return self.check().ip

    @staticmethod
    def _extract_ip(response: requests.Response) -> str | None:
        content_type = response.headers.get("content-type", "").lower()
        text = response.text.strip()
        if "application/json" in content_type or text.startswith("{"):
            data: dict[str, Any] = response.json()
            for key in ("ip", "ip_addr", "query", "origin"):
                value = data.get(key)
                if value:
                    # httpbin can return comma-separated IPs.
                    return str(value).split(",")[0].strip()
            return None
        if text and len(text) <= 80:
            return text.split()[0].strip()
        return None
