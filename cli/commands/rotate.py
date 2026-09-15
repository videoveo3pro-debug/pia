from __future__ import annotations

import time
from typing import Any

import click
from rich.console import Console

from cli.api_client import APIClient, APIClientError


def _extract_error_detail(exc: APIClientError) -> str:
    if isinstance(exc.response_body, dict):
        detail = exc.response_body.get("detail")
        if isinstance(detail, dict):
            return detail.get("error") or str(detail)
        elif detail:
            return str(detail)
        elif exc.response_body.get("error"):
            return str(exc.response_body["error"])
    elif isinstance(exc.response_body, str) and exc.response_body:
        return exc.response_body
    return str(exc)


@click.command("rotate", help="Trigger immediate IP rotation for a worker or across the pool.")
@click.argument("worker", required=False, default=None)
@click.option("--all", "rotate_all", is_flag=True, help="Sequentially trigger IP rotation for all active workers.")
@click.option("--country", "-c", default=None, help="Target country code or region name for new IP.")
@click.option("--server", "-s", default=None, help="Target specific server hostname.")
@click.option("--wait", is_flag=True, help="Wait for new IP verification before returning.")
@click.pass_obj
def rotate_cmd(
    obj: dict[str, Any],
    worker: str | None,
    rotate_all: bool,
    country: str | None,
    server: str | None,
    wait: bool,
) -> None:
    client: APIClient = obj["client"]
    console = Console()

    if not client.is_alive():
        console.print("[bold red]Proxy service is offline. Please start it with 'pia-proxy start' first.[/bold red]")
        raise SystemExit(1)

    if rotate_all:
        console.print("[bold cyan]Rotating all active workers...[/bold cyan]")
        try:
            nodes = client.get_nodes()
            active_nodes = [n for n in nodes if n.get("active")]
            for n in active_nodes:
                wid = n.get("id")
                try:
                    res = client.rotate_node(wid, country=country, server=server, wait_for_ready=wait)
                    console.print(f"  • Worker {wid}: [green]Rotation triggered[/green]")
                except APIClientError as e:
                    console.print(f"  • Worker {wid}: [yellow]{_extract_error_detail(e)}[/yellow]")
                except Exception as e:
                    console.print(f"  • Worker {wid}: [red]{e}[/red]")
                time.sleep(0.5)
            console.print("[bold green]✔ Completed rotation triggers for all active workers.[/bold green]")
        except Exception as exc:
            console.print(f"[bold red]Failed to rotate all: {exc}[/bold red]")
        return

    if worker:
        wid = f"worker{worker}" if worker.isdigit() else worker
        wid_clean = wid.replace("vpn-", "").replace("pia-", "")
        console.print(f"[bold cyan]Rotating worker '{wid_clean}'...[/bold cyan]")
        try:
            with console.status(f"[yellow]Rotating {wid_clean}...[/yellow]"):
                res = client.rotate_node(wid_clean, country=country, server=server, wait_for_ready=wait)

            if res.get("ok"):
                new_ip = res.get("new_ip") or res.get("current_ip")
                if new_ip:
                    console.print(f"[bold green]✔ Worker '{wid_clean}' rotated! New Exit IP: {new_ip}[/bold green]")
                else:
                    console.print(f"[bold green]✔ Worker '{wid_clean}' rotation initiated in background.[/bold green]")
            else:
                err = res.get("error") or res.get("last_error") or "IP did not change."
                console.print(f"[yellow]Notice for '{wid_clean}': {err}[/yellow]")
        except APIClientError as exc:
            detail = _extract_error_detail(exc)
            if exc.status_code == 409:
                console.print(f"[yellow]ℹ Worker '{wid_clean}' đang trong chu kỳ xoay/cooldown: {detail}[/yellow]")
            else:
                console.print(f"[bold red]Failed to rotate worker: {detail}[/bold red]")
            raise SystemExit(1)
        return

    # Default: rotate any ready worker
    console.print("[bold cyan]Rotating an active worker behind the gateway...[/bold cyan]")
    try:
        with console.status("[yellow]Rotating...[/yellow]"):
            res = client.rotate_any(country=country, server=server, wait_for_ready=wait)

        node_id = res.get("selected_node") or res.get("node_id") or "worker"
        if res.get("ok"):
            new_ip = res.get("new_ip") or res.get("current_ip")
            if new_ip:
                console.print(f"[bold green]✔ Worker '{node_id}' rotated! New Exit IP: {new_ip}[/bold green]")
            else:
                console.print(f"[bold green]✔ Worker '{node_id}' detached and rotating in background.[/bold green]")
        else:
            err = res.get("error") or res.get("last_error") or "IP did not change."
            console.print(f"[yellow]Notice for '{node_id}': {err}[/yellow]")
    except APIClientError as exc:
        detail = _extract_error_detail(exc)
        if exc.status_code == 409:
            console.print(f"[yellow]ℹ Không thể xoay worker lúc này: {detail}[/yellow]")
        else:
            console.print(f"[bold red]Failed to rotate: {detail}[/bold red]")
        raise SystemExit(1)
