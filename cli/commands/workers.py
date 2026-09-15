from __future__ import annotations

from typing import Any

import click
from rich.console import Console
from rich.panel import Panel

from cli.api_client import APIClient, APIClientError
from cli.config import CLIConfig
from cli.docker_ctl import DockerController


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


@click.command("workers", help="View or scale the number of VPN workers (e.g. 'pia-proxy workers 32').")
@click.argument("count", type=int, required=False, default=None)
@click.pass_obj
def workers_cmd(obj: dict[str, Any], count: int | None) -> None:
    config: CLIConfig = obj["config"]
    client: APIClient = obj["client"]
    docker_ctl: DockerController = obj["docker_ctl"]
    console = Console()

    # If count is omitted, show current status
    if count is None:
        mode_info = "Offline"
        active_count = config.worker_count
        ready_count = "—"

        if client.is_alive():
            try:
                st = client.get_status()
                gw = st.get("gateway", {})
                active_count = len(gw.get("active_workers", [])) or config.worker_count
                ready_count = str(gw.get("ready_workers", 0))
                mode_info = "Online (Active)"
            except Exception:
                pass

        msg = (
            f"• Số Worker đã cấu hình: [bold cyan]{config.worker_count}[/bold cyan]\n"
            f"• Số Worker đang chạy:    [bold green]{active_count}[/bold green] (Ready: {ready_count})\n"
            f"• Trạng thái Backend:      [bold white]{mode_info}[/bold white]\n\n"
            f"[dim]Để đổi số lượng worker, gõ: pia-proxy workers <số_lượng> (Ví dụ: pia-proxy workers 20)[/dim]"
        )
        console.print(Panel(msg, title="[bold yellow]Thông Tin Worker Pool[/bold yellow]", border_style="cyan"))
        return

    # Scaling to new count
    if count < 1 or count > 48:
        console.print("[bold red]Lỗi: Số lượng worker phải từ 1 đến 48.[/bold red]")
        raise SystemExit(1)

    console.print(f"[bold cyan]Đang điều chỉnh số lượng worker thành {count}...[/bold cyan]")
    config.update_env_value("WORKER_COUNT", count)

    if docker_ctl.is_docker_running():
        with console.status(f"[cyan]Đang đồng bộ container Docker ({count} workers)...[/cyan]"):
            docker_ctl.scale_workers(count)

    if client.is_alive():
        try:
            with console.status(f"[green]Đang scale động sang {count} workers (Zero-Downtime)...[/green]"):
                res = client.set_mode(count)

            if res.get("ok"):
                console.print(f"[bold green]✔ Đã scale thành công sang {count} workers hoạt động![/bold green]")
                return
        except APIClientError as exc:
            detail = _extract_error_detail(exc)
            console.print(f"[yellow]Cảnh báo API: {detail}[/yellow]")
            return

    console.print(f"[bold green]✔ Đã lưu WORKER_COUNT={count} vào cấu hình.[/bold green]")
    console.print("[dim]Số lượng mới sẽ áp dụng khi chạy 'pia-proxy start'.[/dim]")
