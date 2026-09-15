from __future__ import annotations

from typing import Any

import click
from rich.console import Console

from cli.api_client import APIClient, APIClientError
from cli.config import CLIConfig


@click.command("scale", help="Scale active worker count dynamically (e.g. 8, 16, 20, 32, 48) with Zero Downtime.")
@click.argument("count", type=int)
@click.pass_obj
def scale_cmd(obj: dict[str, Any], count: int) -> None:
    config: CLIConfig = obj["config"]
    client: APIClient = obj["client"]
    console = Console()

    if count < 1 or count > 50:
        console.print("[bold red]Worker count must be between 1 and 50.[/bold red]")
        raise SystemExit(1)

    console.print(f"[bold cyan]Scaling proxy worker pool to {count} workers...[/bold cyan]")

    # Persist in .env
    config.update_env_value("WORKER_COUNT", count)

    # Check if backend API is online for live hot-reload
    if client.is_alive():
        try:
            with console.status(f"[green]Applying dynamic scaling to {count} workers via API...[/green]"):
                res = client.set_mode(count)

            if res.get("ok"):
                worker_count = res.get("worker_count", count)
                min_ready = res.get("min_ready_workers")
                actions = res.get("docker_actions", [])
                stopped = sum(1 for a in actions if a.get("action") == "stop_inactive")
                started = sum(1 for a in actions if a.get("action") == "start_active")

                console.print(f"[bold green]✔ Successfully scaled active pool to {worker_count} workers![/bold green]")
                if min_ready:
                    console.print(f"[dim]Effective minimum ready workers: {min_ready}[/dim]")
                if stopped > 0:
                    console.print(f"[dim]Deactivated & detached {stopped} inactive worker(s).[/dim]")
                if started > 0:
                    console.print(f"[dim]Spawned & enabled {started} worker(s).[/dim]")
                return
        except APIClientError as exc:
            console.print(f"[yellow]API returned error: {exc}[/yellow]")
            console.print("[yellow]Saved configuration to .env. Please run 'pia-proxy restart' to apply.[/yellow]")
            return

    console.print(f"[bold green]✔ Saved WORKER_COUNT={count} in {config.env_file.name}.[/bold green]")
    console.print("[dim]Service is currently offline. Start the pool with 'pia-proxy start' to apply.[/dim]")
