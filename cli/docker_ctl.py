from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any, Callable

from cli.config import CLIConfig


class DockerController:
    def __init__(self, config: CLIConfig):
        self.config = config
        self.compose_dir = config.compose_dir

    def _run_compose(
        self,
        args: list[str],
        capture_output: bool = True,
        check: bool = False,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        cmd = ["docker", "compose"] + args
        return subprocess.run(
            cmd,
            cwd=str(self.compose_dir),
            capture_output=capture_output,
            text=True,
            check=check,
            timeout=timeout,
        )

    def is_docker_running(self) -> bool:
        try:
            res = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            return res.returncode == 0
        except Exception:
            return False

    is_docker_available = is_docker_running

    def get_running_containers(self) -> list[dict[str, str]]:
        try:
            res = subprocess.run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    "name=pia-",
                    "--format",
                    "{{.Names}}\t{{.Status}}\t{{.Ports}}",
                ],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if res.returncode != 0 or not res.stdout.strip():
                return []
            containers = []
            for line in res.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    containers.append({
                        "name": parts[0],
                        "status": parts[1],
                        "ports": parts[2] if len(parts) > 2 else "",
                    })
            return containers
        except Exception:
            return []

    def staggered_start(
        self,
        worker_count: int,
        log_callback: Callable[[str, str], None] | None = None,
        delay: float = 0.3,
        session_wait_timeout: int = 30,
    ) -> bool:
        def log(msg: str, level: str = "info") -> None:
            if log_callback:
                log_callback(msg, level)

        # 1. Check PIA account file
        acc_file = self.config.credentials_dir / "pia_account_1"
        if not acc_file.exists() or not acc_file.read_text().strip():
            log(f"Missing PIA account file at {acc_file}. Please configure it first.", "error")
            return False

        # 2. Pull images if not cached
        log("Checking and pulling core images...", "info")
        self._run_compose(["pull", "proxy-gateway"], capture_output=True)

        # 3. Step 1: Start Worker 1 for Session Cache
        log("Starting Worker 1 to acquire/verify PIA Session Token...", "info")
        res = self._run_compose(["up", "-d", "vpn-worker-1"], capture_output=True)
        if res.returncode != 0:
            log(f"Failed to start vpn-worker-1: {res.stderr.strip()}", "error")
            return False

        # Wait for Session Token Cache file
        session_file = self.config.credentials_dir / "pia_session_slot_1.json"
        waited = 0
        while not (session_file.exists() and session_file.stat().st_size > 0) and waited < session_wait_timeout:
            time.sleep(2)
            waited += 2

        if session_file.exists() and session_file.stat().st_size > 0:
            log(f"PIA Session Token cached successfully ({waited}s).", "success")
        else:
            log("Worker 1 taking longer to login. Continuing staggered startup...", "warn")

        # 4. Step 2: Staggered start of Worker 2..N
        log(f"Starting remaining Workers 2 to {worker_count} (staggered {delay}s)...", "info")
        for i in range(2, worker_count + 1):
            service_name = f"vpn-worker-{i}"
            self._run_compose(["up", "-d", service_name], capture_output=True)
            if delay > 0:
                time.sleep(delay)

        log(f"Started all {worker_count} worker containers.", "success")

        # 5. Step 3: Start HAProxy Gateway & Backend API
        log("Starting HAProxy Gateway & Backend API...", "info")
        res = self._run_compose(["up", "-d", "proxy-gateway", "backend"], capture_output=True)
        if res.returncode != 0:
            log(f"Failed to start gateway/backend: {res.stderr.strip()}", "error")
            return False

        log("Gateway & Backend initialized.", "success")
        return True

    def scale_workers(
        self,
        target_count: int,
        delay: float = 0.2,
        log_callback: Callable[[str, str], None] | None = None,
    ) -> bool:
        def log(msg: str, level: str = "info") -> None:
            if log_callback:
                log_callback(msg, level)

        running = self.get_running_containers()
        running_worker_ids = set()
        for c in running:
            name = c.get("name", "")
            if name.startswith("pia-worker-"):
                num_str = name.replace("pia-worker-", "")
                if num_str.isdigit():
                    running_worker_ids.add(int(num_str))

        if target_count > len(running_worker_ids):
            needed = [i for i in range(1, target_count + 1) if i not in running_worker_ids]
            log(f"Scaling up: starting {len(needed)} worker container(s)...", "info")
            for i in needed:
                service = f"vpn-worker-{i}"
                self._run_compose(["up", "-d", service], capture_output=True)
                if delay > 0:
                    time.sleep(delay)
            log(f"Started {len(needed)} worker container(s).", "success")

        elif target_count < len(running_worker_ids):
            excess = [i for i in running_worker_ids if i > target_count]
            log(f"Scaling down: stopping {len(excess)} excess worker container(s)...", "info")
            for i in excess:
                self.stop_worker(i)
                if delay > 0:
                    time.sleep(delay)
            log(f"Stopped {len(excess)} worker container(s).", "success")

        return True

    def stop_all(self) -> bool:
        res = self._run_compose(["down"], capture_output=True)
        return res.returncode == 0

    def stop_worker(self, worker_id: str | int) -> bool:
        container_name = f"pia-worker-{worker_id}" if isinstance(worker_id, int) or worker_id.isdigit() else worker_id
        res = subprocess.run(["docker", "stop", container_name], capture_output=True, text=True)
        return res.returncode == 0

    def restart_service(self, service_name: str) -> bool:
        res = self._run_compose(["restart", service_name], capture_output=True)
        return res.returncode == 0

    def stream_logs(
        self,
        service: str | None = None,
        tail: int = 100,
        follow: bool = False,
    ) -> Generator[str, None, None]:
        args = ["logs", f"--tail={tail}"]
        if follow:
            args.append("-f")
        if service:
            args.append(service)

        cmd = ["docker", "compose"] + args
        proc = subprocess.Popen(
            cmd,
            cwd=str(self.compose_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        try:
            if proc.stdout:
                for line in iter(proc.stdout.readline, ""):
                    yield line.rstrip()
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
