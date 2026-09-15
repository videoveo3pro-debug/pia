from __future__ import annotations

import json
import time
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cli.api_client import APIClient, APIClientError
from cli.config import CLIConfig
from cli.docker_ctl import DockerController


def render_status_view(config: CLIConfig, client: APIClient, docker_ctl: DockerController, refresh: bool = False, show_all: bool = False) -> None:
    console = Console()

    # Try fetching status from Backend API
    status_data: dict[str, Any] | None = None
    try:
        status_data = client.get_status(refresh=refresh)
    except Exception:
        pass

    if status_data and ("nodes" in status_data or "gateway" in status_data or status_data.get("ok")):
        _render_online_status(console, config, status_data, show_all=show_all)
    else:
        _render_offline_status(console, config, docker_ctl)


def _render_online_status(console: Console, config: CLIConfig, data: dict[str, Any], show_all: bool = False) -> None:
    gateway = data.get("gateway", {})
    nodes = data.get("nodes", [])

    active_nodes = [n for n in nodes if n.get("active")]
    ready_nodes = [n for n in active_nodes if n.get("ready")]
    unique_ips = set(n.get("current_ip") for n in ready_nodes if n.get("current_ip"))

    server_ip = config.get_public_ip()
    proxy_port = gateway.get("port") or config.proxy_port
    proxy_url = f"socks5h://{config.socks5_user}:{config.socks5_pass}@{server_ip}:{proxy_port}"

    # Header Panel
    header_text = Text()
    header_text.append(" SOCKS5 Gateway: ", style="bold cyan")
    header_text.append(proxy_url, style="bold green")
    header_text.append("\n Backend API:    ", style="bold cyan")
    header_text.append(f"{config.api_base_url} (Online)", style="green")
    header_text.append("\n Active Pool:    ", style="bold cyan")
    header_text.append(f"{len(ready_nodes)} READY", style="bold green" if len(ready_nodes) >= 20 else "bold yellow")
    header_text.append(f" / {len(active_nodes)} Active ({len(nodes)} Configured)")
    header_text.append(" | Unique Public IPs: ", style="bold cyan")
    header_text.append(f"{len(unique_ips)}", style="bold green" if len(unique_ips) >= 20 else "bold yellow")
    header_text.append("\n Auto-Rotate:    ", style="bold cyan")
    header_text.append("Active (36s - 69s) | Strict Hard Cap: 70s", style="magenta")

    panel = Panel(
        header_text,
        title="[bold yellow]PIA SOCKS5 Multi-Worker Gateway - Live Status[/bold yellow]",
        border_style="cyan",
    )
    console.print(panel)

    # Worker Table
    table = Table(show_header=True, header_style="bold magenta", expand=True)
    table.add_column("Worker", style="bold white", width=12)
    table.add_column("Status", width=12)
    table.add_column("Exit IP", style="cyan", width=18)
    table.add_column("Uptime", width=12)
    table.add_column("Rotations", justify="right", width=10)
    table.add_column("Country / Target", style="dim white", width=18)
    table.add_column("Note / Error", style="red")

    over_70s = 0
    display_nodes = nodes if show_all else [n for n in nodes if n.get("active")]
    if not display_nodes:
        display_nodes = nodes

    for node in display_nodes:
        wid = node.get("id", "")
        active = node.get("active", False)
        ready = node.get("ready", False)
        ip = node.get("current_ip") or "—"
        uptime_sec = node.get("uptime_seconds")
        rot_cnt = str(node.get("rotation_count", 0))
        country = node.get("country") or node.get("country_hint") or "random"
        note = ""

        if not active:
            status_cell = Text("○ INACTIVE", style="dim")
            uptime_cell = Text("—", style="dim")
            ip = "—"
        elif ready:
            status_cell = Text("● READY", style="bold green")
            if uptime_sec is not None:
                if uptime_sec > 70:
                    over_70s += 1
                    uptime_cell = Text(f"{uptime_sec}s (rotating)", style="bold yellow")
                else:
                    uptime_cell = Text(f"{uptime_sec}s", style="white")
            else:
                uptime_cell = Text("—")
        else:
            if node.get("auto_rotate_in_progress") or node.get("recovery_in_progress"):
                status_cell = Text("◐ ROTATING", style="bold yellow")
            else:
                status_cell = Text("✗ DOWN", style="bold red")
            uptime_cell = Text("—", style="dim")
            note = node.get("runtime_error") or node.get("ip_error") or "Connecting..."

        table.add_row(wid, status_cell, ip, uptime_cell, rot_cnt, country, note[:30])

    console.print(table)

    summary_text = Text()
    if len(unique_ips) >= 20:
        summary_text.append("✔ Target achieved: Pool is providing 20+ independent IPs!\n", style="bold green")
    else:
        summary_text.append(f"⏳ Pool warming up: Currently {len(unique_ips)}/20+ independent IPs.\n", style="yellow")

    if not show_all and len(nodes) > len(display_nodes):
        summary_text.append(f"ℹ Hiển thị {len(display_nodes)} active workers. Dùng 'pia-proxy status -a' để xem toàn bộ {len(nodes)} worker slots.\n", style="dim")

    if over_70s > 0:
        summary_text.append(f"ℹ {over_70s} worker(s) undergoing rotation after reaching 70s uptime limit.", style="dim")

    console.print(summary_text)


def _render_offline_status(console: Console, config: CLIConfig, docker_ctl: DockerController) -> None:
    containers = docker_ctl.get_running_containers()

    panel_text = Text()
    panel_text.append("Backend API is currently ", style="bold white")
    panel_text.append("OFFLINE", style="bold red")
    panel_text.append(f" ({config.api_base_url})\n\n")

    if containers:
        panel_text.append(f"Found {len(containers)} Docker container(s) running:\n", style="yellow")
        for c in containers[:8]:
            panel_text.append(f"  • {c['name']} ({c['status']})\n", style="dim")
        if len(containers) > 8:
            panel_text.append(f"  ... and {len(containers) - 8} more.\n", style="dim")
        panel_text.append("\nRun 'pia-proxy start' to bring up the full proxy pool.", style="bold cyan")
    else:
        panel_text.append("No active proxy containers found.\n", style="dim")
        panel_text.append("Run 'pia-proxy start' to start the service.", style="bold green")

    panel = Panel(
        panel_text,
        title="[bold red]PIA SOCKS5 Gateway - Service Offline[/bold red]",
        border_style="red",
    )
    console.print(panel)


@click.command("status", help="Display real-time proxy pool status, worker health, and exit IPs.")
@click.option("--watch", "-w", is_flag=True, help="Continuously monitor status with live refresh.")
@click.option("--all", "-a", "show_all", is_flag=True, help="Show all configured worker slots including inactive.")
@click.option("--interval", "-i", default=3, help="Refresh interval in seconds when using --watch.", show_default=True)
@click.option("--refresh", "-r", is_flag=True, help="Force immediate refresh of all worker states.")
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON data.")
@click.pass_obj
def status_cmd(obj: dict[str, Any], watch: bool, show_all: bool, interval: int, refresh: bool, as_json: bool) -> None:
    config: CLIConfig = obj["config"]
    client: APIClient = obj["client"]
    docker_ctl: DockerController = obj["docker_ctl"]

    if as_json:
        try:
            data = client.get_status(refresh=refresh)
            click.echo(json.dumps(data, indent=2))
        except APIClientError as exc:
            click.echo(json.dumps({"ok": False, "error": str(exc)}), err=True)
        return

    if watch:
        console = Console()
        try:
            while True:
                console.clear()
                render_status_view(config, client, docker_ctl, refresh=refresh, show_all=show_all)
                time.sleep(interval)
        except KeyboardInterrupt:
            pass
    else:
        render_status_view(config, client, docker_ctl, refresh=refresh, show_all=show_all)
