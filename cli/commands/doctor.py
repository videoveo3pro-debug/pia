from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from cli.config import CLIConfig


def _is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


@click.command("doctor", help="Inspect system readiness, tun device, ports, swap, and Docker requirements.")
@click.pass_obj
def doctor_cmd(obj: dict[str, Any]) -> None:
    config: CLIConfig = obj["config"]
    console = Console()

    table = Table(title="[bold cyan]System Environment & Health Diagnostics[/bold cyan]", expand=True)
    table.add_column("Component", style="bold white", width=22)
    table.add_column("Status", width=16)
    table.add_column("Details", style="dim")

    # 1. Docker Engine
    docker_ok = False
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=3)
        docker_ok = r.returncode == 0
    except Exception:
        pass

    if docker_ok:
        table.add_row("Docker Engine", Text("✔ OK", style="bold green"), "Daemon is active and reachable")
    else:
        table.add_row("Docker Engine", Text("✗ ERROR", style="bold red"), "Docker daemon not running or access denied")

    # 2. Docker Compose
    compose_ok = False
    try:
        r = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True, timeout=3)
        compose_ok = r.returncode == 0
        compose_ver = r.stdout.strip()
    except Exception:
        compose_ver = "Not installed"

    if compose_ok:
        table.add_row("Docker Compose", Text("✔ OK", style="bold green"), compose_ver)
    else:
        table.add_row("Docker Compose", Text("✗ ERROR", style="bold red"), "docker compose command missing")

    # 3. TUN device
    tun_path = Path("/dev/net/tun")
    if tun_path.exists():
        table.add_row("TUN Device", Text("✔ OK", style="bold green"), "/dev/net/tun is present")
    else:
        table.add_row("TUN Device", Text("✗ MISSING", style="bold red"), "Run 'mkdir -p /dev/net && mknod /dev/net/tun c 10 200'")

    # 3.5. WireGuard Kernel Module
    wg_ok = Path("/sys/module/wireguard").exists()
    if not wg_ok:
        try:
            subprocess.run(["modprobe", "wireguard"], capture_output=True, check=False)
            wg_ok = Path("/sys/module/wireguard").exists()
        except Exception:
            pass
    if wg_ok:
        table.add_row("WireGuard Module", Text("✔ OK", style="bold green"), "In-kernel WireGuard active")
    else:
        table.add_row("WireGuard Module", Text("⚠ WARN", style="bold yellow"), "Run 'modprobe wireguard' for 10x faster VPN")

    # 4. RAM & Swap
    mem_ok = False
    mem_info = "Unable to read /proc/meminfo"
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
            total_ram = 0
            total_swap = 0
            for line in lines:
                if line.startswith("MemTotal:"):
                    total_ram = int(line.split()[1]) // 1024
                elif line.startswith("SwapTotal:"):
                    total_swap = int(line.split()[1]) // 1024
            mem_info = f"RAM: {total_ram}MB | Swap: {total_swap}MB"
            mem_ok = total_swap >= 1000 or total_ram >= 3000
    except Exception:
        pass

    if mem_ok:
        table.add_row("Memory & Swap", Text("✔ OK", style="bold green"), mem_info)
    else:
        table.add_row("Memory & Swap", Text("⚠ WARN", style="bold yellow"), f"{mem_info} (Recommend adding >= 2GB swap)")

    # 5. PIA Credentials
    u, p = config.get_pia_account()
    if u and p:
        table.add_row("PIA Account", Text("✔ READY", style="bold green"), f"Username: {u}")
    else:
        table.add_row("PIA Account", Text("✗ NOT SET", style="bold red"), "Configure with 'pia-proxy config set-credentials'")

    # 6. Gateway Port (1087)
    gw_in_use = _is_port_open(config.proxy_port)
    table.add_row(f"Proxy Port ({config.proxy_port})", Text("IN USE" if gw_in_use else "AVAILABLE", style="cyan" if gw_in_use else "green"), "SOCKS5 Proxy Gateway")

    # 7. API Port (8007)
    api_in_use = _is_port_open(config.api_port)
    table.add_row(f"API Port ({config.api_port})", Text("IN USE" if api_in_use else "AVAILABLE", style="cyan" if api_in_use else "green"), "FastAPI Backend")

    console.print(table)
