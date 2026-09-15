from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class APIClientError(Exception):
    def __init__(self, message: str, status_code: int | None = None, response_body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class APIClient:
    def __init__(self, base_url: str, token: str = "", timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            if query:
                url = f"{url}?{query}"

        headers = {
            "User-Agent": "pia-proxy-cli/1.0",
            "Accept": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        data_bytes = None
        if json_data is not None:
            data_bytes = json.dumps(json_data).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method.upper())

        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                if not raw.strip():
                    return {}
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            raw_err = e.read().decode("utf-8", errors="ignore")
            try:
                body = json.loads(raw_err)
            except Exception:
                body = raw_err
            raise APIClientError(
                message=f"HTTP {e.code}: {e.reason}",
                status_code=e.code,
                response_body=body,
            ) from e
        except urllib.error.URLError as e:
            raise APIClientError(message=f"Connection failed: {e.reason}") from e
        except Exception as e:
            raise APIClientError(message=f"Request error: {str(e)}") from e

    def is_alive(self) -> bool:
        try:
            res = self._request("GET", "/healthz", timeout=3.0)
            return bool(res.get("ok"))
        except Exception:
            return False

    def get_status(self, refresh: bool = False) -> dict[str, Any]:
        return self._request("GET", "/api/status", params={"refresh": refresh}, timeout=12.0)

    def get_nodes(self, refresh: bool = False) -> list[dict[str, Any]]:
        res = self._request("GET", "/api/nodes", params={"refresh": refresh}, timeout=10.0)
        return res.get("nodes", [])

    def get_healthy_nodes(self) -> dict[str, Any]:
        return self._request("GET", "/api/nodes/healthy", timeout=6.0)

    def get_node(self, node_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/nodes/{node_id}", timeout=6.0)

    def set_mode(self, worker_count: int) -> dict[str, Any]:
        return self._request("POST", "/api/mode", json_data={"worker_count": worker_count}, timeout=30.0)

    def get_mode(self) -> dict[str, Any]:
        return self._request("GET", "/api/mode", timeout=5.0)

    def rotate_any(self, country: str | None = None, server: str | None = None, wait_for_ready: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {"wait_for_ready": wait_for_ready}
        if country:
            payload["country"] = country
        if server:
            payload["server"] = server
        return self._request("POST", "/api/rotate-any", json_data=payload, timeout=20.0)

    def rotate_node(self, node_id: str, country: str | None = None, server: str | None = None, wait_for_ready: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {"wait_for_ready": wait_for_ready}
        if country:
            payload["country"] = country
        if server:
            payload["server"] = server
        return self._request("POST", f"/api/nodes/{node_id}/rotate", json_data=payload, timeout=25.0)

    def recover_all(self, force: bool = False) -> dict[str, Any]:
        return self._request("POST", "/api/recover", json_data={"force": force}, timeout=15.0)

    def recover_node(self, node_id: str, force: bool = False) -> dict[str, Any]:
        return self._request("POST", f"/api/nodes/{node_id}/recover", json_data={"force": force}, timeout=15.0)

    def test_proxy(self) -> dict[str, Any]:
        return self._request("GET", "/api/test-proxy", timeout=15.0)

    def get_countries(self, refresh: bool = False) -> dict[str, Any]:
        return self._request("GET", "/api/countries", params={"refresh": refresh}, timeout=15.0)

    def get_logs(self, tail: int = 100) -> dict[str, Any]:
        return self._request("GET", "/api/logs", params={"tail": tail}, timeout=10.0)
