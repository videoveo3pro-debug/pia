#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


HOST = os.getenv("PROXY_CONTROL_HOST", "0.0.0.0")
PORT = int(os.getenv("PROXY_CONTROL_PORT", "9000"))
TOKEN = os.getenv("PROXY_CONTROL_TOKEN", "").strip()
SOCKS5_PORT = int(os.getenv("SOCKS5_PORT", "1080"))
WORKER_ID = os.getenv("WORKER_ID", "worker")
TOKEN_SLOT = os.getenv("TOKEN_SLOT", "1").strip() or "1"
CREDENTIALS_DIR = os.getenv("CREDENTIALS_CONTAINER_PATH", "/app/credentials")
SESSION_PATH = os.path.join(CREDENTIALS_DIR, f"pia_session_slot_{TOKEN_SLOT}.json")
ACCOUNT_JSON_PATH = "/opt/piavpn/etc/account.json"
LOG_PATH = os.getenv("PROXY_LOG_PATH", "/tmp/proxy-runtime.log")
DEFAULT_TIMEOUT = int(os.getenv("CLI_COMMAND_TIMEOUT_SECONDS", "20"))
STATUS_TIMEOUT = int(os.getenv("CLI_STATUS_TIMEOUT_SECONDS", os.getenv("CLI_COMMAND_TIMEOUT_SECONDS", "20")))
CLI_SETTLE_SECONDS = float(os.getenv("CLI_STATUS_SETTLE_SECONDS", "6"))
MAX_TIMEOUT = 300
PIA_LOCK_PATH = os.getenv("PIA_CLI_LOCK_PATH", "/tmp/piactl.lock")
PIA_LOCK_WAIT_SECONDS = int(os.getenv("PIA_CLI_LOCK_WAIT_SECONDS", "5"))


def log(message: str) -> None:
    print(f"[proxy-control] {message}", flush=True)


def redact(text: str) -> str:
    text = text or ""
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "<redacted-email>", text)
    text = re.sub(r"(?i)\bpia[0-9a-z]+\b", "<redacted-user>", text)
    text = re.sub(r"\bp\d{7,}\b", "<redacted-user>", text, flags=re.I)
    text = re.sub(r"(?i)(password\s*[:=]\s*)\S+", r"\1***", text)
    text = re.sub(r"\b[A-Z0-9]{20,}\b", "<redacted>", text)
    return text


def run_command(args: list[str], *, timeout: int, stdin: str | None = None) -> tuple[int, str]:
    timeout = max(1, min(int(timeout), MAX_TIMEOUT))
    effective_timeout = timeout
    command = args
    if args and args[0] == "piactl":
        lock_wait = max(1, min(PIA_LOCK_WAIT_SECONDS, 30))
        command = ["flock", "-w", str(lock_wait), PIA_LOCK_PATH, args[0], "--timeout", str(timeout), *args[1:]]
        effective_timeout = min(MAX_TIMEOUT, timeout + lock_wait + 5)
    try:
        completed = subprocess.run(
            ["timeout", "-k", "3", f"{effective_timeout}s", *command],
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    output = ((completed.stdout or "") + (completed.stderr or "")).strip()
    return int(completed.returncode), redact(output)


def route_snapshot() -> str:
    code, output = run_command(["sh", "-lc", "ip route get 1.1.1.1 2>/dev/null || true"], timeout=5)
    return output if code == 0 else ""


def route_connected() -> bool:
    route = route_snapshot().lower()
    if not route:
        return False
    return not bool(re.search(r"\bdev\s+eth0\b|\bdev\s+docker", route))


def is_account_logged_in() -> bool:
    try:
        if os.path.exists(ACCOUNT_JSON_PATH) and os.path.getsize(ACCOUNT_JSON_PATH) > 10:
            with open(ACCOUNT_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return bool(data.get("loggedIn"))
    except Exception:
        pass
    return False


def save_account_session() -> bool:
    try:
        if os.path.exists(ACCOUNT_JSON_PATH) and os.path.getsize(ACCOUNT_JSON_PATH) > 10:
            os.makedirs(CREDENTIALS_DIR, exist_ok=True)
            shutil.copyfile(ACCOUNT_JSON_PATH, SESSION_PATH)
            os.chmod(SESSION_PATH, 0o600)
            log(f"Cached account session to {SESSION_PATH}")
            return True
    except Exception as exc:
        log(f"Failed to cache account session: {exc}")
    return False


def reload_account_session() -> bool:
    try:
        if os.path.exists(SESSION_PATH) and os.path.getsize(SESSION_PATH) > 10:
            os.makedirs(os.path.dirname(ACCOUNT_JSON_PATH), exist_ok=True)
            shutil.copyfile(SESSION_PATH, ACCOUNT_JSON_PATH)
            os.chmod(ACCOUNT_JSON_PATH, 0o600)
            try:
                shutil.chown(ACCOUNT_JSON_PATH, user="root", group="piavpn")
            except Exception:
                pass
            log(f"Restored account session from {SESSION_PATH}")
            return True
    except Exception as exc:
        log(f"Failed to reload account session: {exc}")
    return False


def run_pia_cli(args: list[str], *, timeout: int) -> tuple[int, str]:
    def settle_if_needed() -> None:
        if args and args[0] in {"login", "connect", "disconnect", "logout"} and CLI_SETTLE_SECONDS > 0:
            time.sleep(min(CLI_SETTLE_SECONDS, 30))

    if args and args[0] in {"session_reload", "reload_session"}:
        if reload_account_session():
            return 0, "session reloaded successfully"
        return 1, "session file not found or invalid"

    if args and args[0] == "login":
        username = args[1] if len(args) > 1 else ""
        password = args[2] if len(args) > 2 else ""
        if not username.strip() or not password:
            # Try reloading session first if available
            if reload_account_session() and is_account_logged_in():
                return 0, "session restored from credentials cache"
            return 2, "username and password are required"
        path = f"/tmp/pia-login-{os.getpid()}-{int(time.time() * 1000)}.txt"
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(username.strip() + "\n" + password + "\n")
            os.chmod(path, 0o600)
            result = run_command(["piactl", "login", path], timeout=timeout + 5)
            settle_if_needed()
            if result[0] == 0:
                save_account_session()
            return result
        finally:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    if args and args[0] == "connect":
        target = args[1].strip() if len(args) > 1 else ""
        warnings: list[str] = []
        background_result = run_command(["piactl", "background", "enable"], timeout=min(timeout + 5, 60))
        if background_result[0] != 0:
            settle_if_needed()
            return background_result
        if target and target.lower() not in {"random", "__random__", "any", "all"}:
            cleaned_target = target.strip().lower()
            region_result = run_command(["piactl", "set", "region", cleaned_target], timeout=min(timeout + 5, 25))
            if region_result[0] != 0 and " " in cleaned_target:
                cleaned_target = cleaned_target.replace(" ", "-")
                region_result = run_command(["piactl", "set", "region", cleaned_target], timeout=min(timeout + 5, 25))
            if region_result[0] != 0:
                warnings.append(f"Region target '{target}' was rejected; using quick-connect. {region_result[1]}")
        result = run_command(["piactl", "connect"], timeout=timeout + 5)
        settle_if_needed()
        if warnings and result[0] == 0:
            output = "\n".join([*warnings, result[1]]).strip()
            return result[0], output
        return result

    if args and args[0] == "disconnect":
        result = run_command(["piactl", "disconnect"], timeout=timeout + 5)
        settle_if_needed()
        return result

    if args and args[0] == "logout":
        result = run_command(["piactl", "logout"], timeout=timeout + 5, stdin="y\n")
        settle_if_needed()
        try:
            if os.path.exists(SESSION_PATH):
                os.unlink(SESSION_PATH)
        except Exception:
            pass
        return result

    if args and args[0] == "status":
        chunks: list[str] = []
        code_state, state = run_command(["piactl", "get", "connectionstate"], timeout=STATUS_TIMEOUT)
        code_ip, vpnip = run_command(["piactl", "get", "vpnip"], timeout=STATUS_TIMEOUT)
        code_region, region = run_command(["piactl", "get", "region"], timeout=STATUS_TIMEOUT)
        route = route_snapshot()
        route_ok = route_connected()
        connected = bool(re.search(r"\bconnected\b", state or "", re.I)) or route_ok
        chunks.append(f"ConnectionState: {state or 'unknown'}")
        chunks.append(f"Connected: {'true' if connected else 'false'}")
        chunks.append(f"RouteConnected: {'true' if route_ok else 'false'}")
        chunks.append(f"LoggedIn: {'true' if is_account_logged_in() or connected else 'false'}")
        if vpnip:
            chunks.append(f"VPNIP: {vpnip}")
        if region:
            chunks.append(f"Region: {region}")
        if route:
            chunks.append("Route: " + route)
        return 0 if code_state == 0 or connected else max(code_state, code_ip, code_region), "\n".join(chunks).strip()

    if args and args[0] in {"get", "location", "locations"}:
        if len(args) >= 2 and args[1] in {"regions", "locations"}:
            return run_command(["piactl", "get", "regions"], timeout=timeout + 5)
        if len(args) >= 2 and args[1] in {"region", "vpnip", "connectionstate", "protocol"}:
            return run_command(["piactl", "get", args[1]], timeout=timeout + 5)

    if args and args[0] == "set" and len(args) >= 3 and args[1] == "region":
        return run_command(["piactl", "set", "region", args[2]], timeout=timeout + 5)

    if args and args[0] == "set" and len(args) >= 3 and args[1] == "protocol":
        return run_command(["piactl", "set", "protocol", args[2]], timeout=timeout + 5)

    if args and args[0] == "protocol":
        proto = args[1] if len(args) > 1 else ""
        command = ["piactl", "set", "protocol", proto] if proto else ["piactl", "get", "protocol"]
        return run_command(command, timeout=timeout + 5)

    return 2, f"unsupported piactl command: {' '.join(args)}"


def bool_command(args: list[str]) -> bool:
    code, _ = run_command(args, timeout=5)
    return code == 0


def socks5_listening() -> bool:
    code, output = run_command(["ss", "-ltnH"], timeout=5)
    if code != 0:
        return False
    suffix = f":{SOCKS5_PORT}"
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[3].endswith(suffix):
            return True
    return False


def status_connected(text: str) -> bool:
    lowered = (text or "").lower()
    if re.search(r"connected:\s*true|\bprotected\b", lowered):
        return True
    if re.search(r"connected:\s*false|not[ -]*(connected|protected)|disconnected|unable|not[ -]*(logged|signed)[ -]*in", lowered):
        return False
    return bool(re.search(r"\bconnected\b", lowered))


def tail_text(path: str, limit_lines: int) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return "".join(deque(handle, maxlen=limit_lines)).strip()
    except FileNotFoundError:
        return ""
    except Exception as exc:
        return f"<unable to read {path}: {exc}>"


def runtime_snapshot(*, include_status: bool = False) -> dict[str, object]:
    cli_available = bool_command(["sh", "-lc", "command -v piactl >/dev/null 2>&1"])
    socks_listen = socks5_listening()
    status_ok, status = run_pia_cli(["status"], timeout=STATUS_TIMEOUT) if cli_available and include_status else (False, "")
    route_ok = route_connected()
    logged_in = is_account_logged_in() or route_ok or status_connected(status)
    connected = (status_connected(status) or route_ok) if include_status else route_ok
    return {
        "worker_id": WORKER_ID,
        "token_slot": TOKEN_SLOT,
        "ok": bool(cli_available and socks_listen),
        "service_ready": bool(cli_available and socks_listen),
        "pia_cli_available": cli_available,
        "logged_in": logged_in,
        "connected": connected,
        "status_ok": bool(status_ok == 0),
        "status": status,
        "socks5_listening": socks_listen,
        "socks5_port": SOCKS5_PORT,
        "session_present": bool(os.path.exists(ACCOUNT_JSON_PATH)),
        "log_path": LOG_PATH,
        "timestamp": int(time.time()),
    }


def delayed_exit() -> None:
    time.sleep(0.2)
    os._exit(3)


class Handler(BaseHTTPRequestHandler):
    server_version = "PIAProxyControl/1.0"

    def log_message(self, format: str, *args) -> None:
        log(format % args)

    def _authorized(self) -> bool:
        if not TOKEN:
            return True
        provided = self.headers.get("x-proxy-control-token", "").strip()
        return provided == TOKEN

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("content-length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send(self, payload: dict[str, object], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reject_unauthorized(self) -> bool:
        if self._authorized():
            return False
        self._send({"ok": False, "error": "Unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
        return True

    def do_GET(self) -> None:
        if self._reject_unauthorized():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            runtime = runtime_snapshot(include_status=False)
            status = HTTPStatus.OK if runtime["service_ready"] else HTTPStatus.SERVICE_UNAVAILABLE
            self._send(runtime, status=status)
            return
        if parsed.path == "/runtime":
            params = parse_qs(parsed.query)
            include_status = (params.get("include_status") or ["false"])[0].lower() in {"1", "true", "yes", "on"}
            self._send(runtime_snapshot(include_status=include_status))
            return
        if parsed.path == "/logs":
            params = parse_qs(parsed.query)
            try:
                tail = max(1, min(int((params.get("tail") or ["120"])[0]), 500))
            except ValueError:
                tail = 120
            self._send({"ok": True, "tail": tail, "log": redact(tail_text(LOG_PATH, tail)), "path": LOG_PATH})
            return
        self._send({"ok": False, "error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self._reject_unauthorized():
            return
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
        except Exception as exc:
            self._send({"ok": False, "error": f"Invalid JSON: {exc}"}, status=HTTPStatus.BAD_REQUEST)
            return

        if parsed.path == "/pia":
            args = payload.get("args", [])
            timeout = int(payload.get("timeout", DEFAULT_TIMEOUT) or DEFAULT_TIMEOUT)
            if not isinstance(args, list) or not all(isinstance(item, str) and item.strip() for item in args):
                self._send({"ok": False, "error": "args must be a non-empty list of strings"}, status=HTTPStatus.BAD_REQUEST)
                return
            code, output = run_pia_cli(args, timeout=timeout)
            safe_args = ["login", "<redacted-username>", "<redacted-password>"] if args and args[0] == "login" else args
            self._send({"ok": code == 0, "exit_code": code, "output": output, "args": safe_args})
            return

        if parsed.path == "/session/reload":
            ok = reload_account_session()
            self._send({"ok": ok, "logged_in": is_account_logged_in()})
            return

        if parsed.path == "/restart":
            threading.Thread(target=delayed_exit, daemon=True).start()
            self._send({"ok": True, "restarting": True}, status=HTTPStatus.ACCEPTED)
            return

        self._send({"ok": False, "error": "Not found"}, status=HTTPStatus.NOT_FOUND)


def main() -> None:
    log(f"{WORKER_ID} listening on {HOST}:{PORT}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
