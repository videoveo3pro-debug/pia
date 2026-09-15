from __future__ import annotations

import time
from typing import Any

import click
from rich.console import Console

from cli.api_client import APIClient
from cli.config import CLIConfig
from cli.docker_ctl import DockerController


@click.command("start", help="Start the PIA SOCKS5 proxy pool with intelligent staggered boot.")
@click.option("--workers", "-w", type=int, default=None, help="Number of workers to launch (default: from .env).")
@click.option("--delay", type=float, default=0.3, help="Delay in seconds between starting workers.", show_default=True)
@click.pass_obj
def start_cmd(obj: dict[str, Any], workers: int | None, delay: float) -> None:
    config: CLIConfig = obj["config"]
    client: APIClient = obj["client"]
    docker_ctl: DockerController = obj["docker_ctl"]
    console = Console()

    acc_file = config.credentials_dir / "pia_account_1"
    if not acc_file.exists() or not acc_file.read_text().strip():
        console.print("[bold red]Lỗi: Chưa cấu hình tài khoản PIA![/bold red]")
        console.print("[yellow]Vui lòng chạy lệnh thiết lập trước khi bắt đầu:[/yellow]")
        console.print("  [bold green]pia-proxy setup[/bold green]\n")
        raise SystemExit(1)

    worker_count = workers or config.worker_count
    if workers:
        config.update_env_value("WORKER_COUNT", workers)
    console.print(f"[bold cyan]Initiating PIA SOCKS5 Gateway startup ({worker_count} workers)...[/bold cyan]")

    def log_cb(msg: str, level: str) -> None:
        style_map = {
            "info": "bold blue",
            "success": "bold green",
            "warn": "bold yellow",
            "error": "bold red",
        }
        tag_map = {
            "info": "[INFO]",
            "success": "[SUCCESS]",
            "warn": "[WARN]",
            "error": "[ERROR]",
        }
        style = style_map.get(level, "white")
        tag = tag_map.get(level, "[INFO]")
        console.print(f"[{style}]{tag}[/{style}] {msg}")

    with console.status("[bold green]Starting containers...[/bold green]", spinner="dots"):
        success = docker_ctl.staggered_start(
            worker_count=worker_count,
            log_callback=log_cb,
            delay=delay,
        )

    if not success:
        console.print("[bold red]Failed to start services. Check logs for details: 'pia-proxy logs'[/bold red]")
        raise SystemExit(1)

    # Wait briefly for Backend API healthz
    console.print("[dim]Waiting for Backend API to report healthy...[/dim]")
    healthy = False
    for _ in range(15):
        if client.is_alive():
            healthy = True
            break
        time.sleep(1)

    if healthy:
        console.print("[bold green]✔ Backend API is alive and orchestrating workers![/bold green]")
    else:
        console.print("[yellow]⚠ Backend is still starting up. Run 'pia-proxy status' in a few seconds to monitor.[/yellow]")

    server_ip = config.get_public_ip()
    console.print(f"\n[bold green]Gateway URL:[/bold green] socks5h://{config.socks5_user}:{config.socks5_pass}@{server_ip}:{config.proxy_port}")
    console.print("Run [bold cyan]pia-proxy status[/bold cyan] to view worker connections.")


@click.command("stop", help="Stop proxy services safely.")
@click.option("--worker", "-W", default=None, help="Stop a specific worker container only (e.g. 'worker-5' or '5').")
@click.pass_obj
def stop_cmd(obj: dict[str, Any], worker: str | None) -> None:
    docker_ctl: DockerController = obj["docker_ctl"]
    console = Console()

    if worker:
        digits = "".join(c for c in worker if c.isdigit())
        worker_id = digits if digits else worker
        console.print(f"[yellow]Stopping worker {worker_id}...[/yellow]")
        if docker_ctl.stop_worker(worker_id):
            console.print(f"[bold green]✔ Worker {worker_id} stopped.[/bold green]")
        else:
            console.print(f"[bold red]Failed to stop worker {worker_id}.[/bold red]")
            raise SystemExit(1)
        return

    console.print("[yellow]Stopping all proxy containers...[/yellow]")
    with console.status("[bold yellow]Shutting down...[/bold yellow]", spinner="dots"):
        if docker_ctl.stop_all():
            console.print("[bold green]✔ All proxy services have been stopped.[/bold green]")
        else:
            console.print("[bold red]Error stopping some services.[/bold red]")
            raise SystemExit(1)


@click.command("restart", help="Restart proxy services or an individual worker.")
@click.option("--worker", "-W", default=None, help="Restart a specific worker (e.g. 'worker-3' or '3').")
@click.pass_obj
def restart_cmd(obj: dict[str, Any], worker: str | None) -> None:
    client: APIClient = obj["client"]
    docker_ctl: DockerController = obj["docker_ctl"]
    console = Console()

    if worker:
        digits = "".join(c for c in worker if c.isdigit())
        wid_clean = f"worker{digits}" if digits else worker
        service_name = f"vpn-worker-{digits}" if digits else worker

        console.print(f"[cyan]Attempting recovery for node '{wid_clean}'...[/cyan]")
        try:
            res = client.recover_node(wid_clean, force=True)
            if res.get("ok"):
                console.print(f"[bold green]✔ Recovery initiated for {wid_clean}.[/bold green]")
                return
        except Exception:
            pass

        # Fallback to Docker restart
        console.print(f"[yellow]Triggering Docker restart for '{service_name}'...[/yellow]")
        docker_ctl.restart_service(service_name)
        console.print(f"[bold green]✔ Service '{service_name}' restarted.[/bold green]")
        return

    console.print("[yellow]Restarting entire proxy stack...[/yellow]")
    docker_ctl.stop_all()
    time.sleep(1)
    ctx = click.get_current_context()
    ctx.invoke(start_cmd)
