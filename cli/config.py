from __future__ import annotations

import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


import shutil

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _get_project_root() -> Path:
    env_dir = os.getenv("PIA_PROJECT_DIR")
    if env_dir:
        p = Path(env_dir).resolve()
        if p.exists():
            return p

    # Current working directory if compose exists
    cwd = Path.cwd()
    if (cwd / "docker-compose.yml").exists() or (cwd / "prod" / "docker-compose.yml").exists():
        return cwd

    # Dev repository root if compose exists
    repo_dir = Path(__file__).resolve().parent.parent
    if (repo_dir / "prod" / "docker-compose.yml").exists() or (repo_dir / "docker-compose.yml").exists():
        return repo_dir

    # Global standalone fallback: ~/.pia-proxy
    user_dir = Path.home() / ".pia-proxy"
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


@dataclass
class CLIConfig:
    project_root: Path
    compose_dir: Path
    env_file: Path
    credentials_dir: Path
    api_host: str = "127.0.0.1"
    api_port: int = 8007
    proxy_port: int = 1087
    socks5_user: str = "proxy_user"
    socks5_pass: str = "proxy_password_secure123"
    worker_count: int = 32
    max_worker_count: int = 48
    api_token: str = ""
    public_ip: str = ""

    @classmethod
    def load(cls, custom_dir: Path | str | None = None) -> CLIConfig:
        root = Path(custom_dir).resolve() if custom_dir else _get_project_root()

        # Decide compose_dir: prefer prod if prod/docker-compose.yml exists
        if (root / "prod" / "docker-compose.yml").exists():
            compose_dir = root / "prod"
        elif (root / "docker-compose.yml").exists():
            compose_dir = root
        else:
            compose_dir = root

        # Self-initialize templates if docker-compose.yml is missing in standalone mode
        if not (compose_dir / "docker-compose.yml").exists() and (TEMPLATES_DIR / "docker-compose.yml").exists():
            compose_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(TEMPLATES_DIR / "docker-compose.yml", compose_dir / "docker-compose.yml")

        # Locate .env
        env_file = compose_dir / ".env"
        if not env_file.exists():
            if (root / ".env").exists():
                env_file = root / ".env"
            elif (TEMPLATES_DIR / ".env.example").exists():
                shutil.copy(TEMPLATES_DIR / ".env.example", env_file)

        # Locate credentials dir
        credentials_dir = compose_dir / "credentials"
        if not credentials_dir.exists() and (root / "credentials").exists():
            credentials_dir = root / "credentials"
        credentials_dir.mkdir(parents=True, exist_ok=True)

        cfg = cls(
            project_root=root,
            compose_dir=compose_dir,
            env_file=env_file,
            credentials_dir=credentials_dir,
        )

        cfg._parse_env()
        return cfg

    def _parse_env(self) -> None:
        if not self.env_file.exists():
            return

        with open(self.env_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")

                if key == "API_PORT":
                    try:
                        self.api_port = int(val)
                    except ValueError:
                        pass
                elif key == "PROXY_PORT":
                    try:
                        self.proxy_port = int(val)
                    except ValueError:
                        pass
                elif key == "SOCKS5_USERNAME":
                    self.socks5_user = val
                elif key == "SOCKS5_PASSWORD":
                    self.socks5_pass = val
                elif key == "WORKER_COUNT":
                    try:
                        self.worker_count = int(val)
                    except ValueError:
                        pass
                elif key == "MAX_WORKER_COUNT":
                    try:
                        self.max_worker_count = int(val)
                    except ValueError:
                        pass
                elif key == "API_TOKEN":
                    self.api_token = val

    def update_env_value(self, key: str, value: Any) -> None:
        """Update or insert a key-value pair in .env file."""
        if not self.env_file.exists():
            self.env_file.write_text(f"{key}={value}\n", encoding="utf-8")
            self._parse_env()
            return

        lines = self.env_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        found = False
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(f"{key}=") or stripped.startswith(f"{key} ="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(line)

        if not found:
            new_lines.append(f"{key}={value}")

        self.env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        self._parse_env()

    @property
    def api_base_url(self) -> str:
        return f"http://{self.api_host}:{self.api_port}"

    def get_public_ip(self, timeout: float = 3.0) -> str:
        if self.public_ip:
            return self.public_ip
        endpoints = [
            "https://api.ipify.org",
            "https://icanhazip.com",
            "https://ifconfig.me/ip",
        ]
        for url in endpoints:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "curl/7.88.1"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    ip = resp.read().decode().strip()
                    if ip and "." in ip:
                        self.public_ip = ip
                        return ip
            except Exception:
                continue
        self.public_ip = "127.0.0.1"
        return self.public_ip

    def get_pia_account(self) -> tuple[str, str]:
        """Returns (username, password) if available from credentials/pia_account_1"""
        acc_file = self.credentials_dir / "pia_account_1"
        if not acc_file.exists():
            return "", ""
        try:
            lines = [line.strip() for line in acc_file.read_text().splitlines() if line.strip()]
            if len(lines) >= 2:
                return lines[0], lines[1]
            elif len(lines) == 1 and ":" in lines[0]:
                u, p = lines[0].split(":", 1)
                return u.strip(), p.strip()
        except Exception:
            pass
        return "", ""

    def set_pia_account(self, username: str, password: str) -> None:
        self.credentials_dir.mkdir(parents=True, exist_ok=True)
        acc_file = self.credentials_dir / "pia_account_1"
        acc_file.write_text(f"{username.strip()}\n{password.strip()}\n", encoding="utf-8")
        try:
            os.chmod(acc_file, 0o600)
        except OSError:
            pass
