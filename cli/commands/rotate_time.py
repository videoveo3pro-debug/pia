from __future__ import annotations

from typing import Any

import click
from rich.console import Console
from rich.panel import Panel

from cli.config import CLIConfig


@click.command("rotate-time", help="View or set auto-rotation intervals & max uptime (e.g. 'pia-proxy rotate-time 36 69 70').")
@click.argument("min_sec", type=int, required=False, default=None)
@click.argument("max_sec", type=int, required=False, default=None)
@click.argument("max_uptime", type=int, required=False, default=None)
@click.pass_obj
def rotate_time_cmd(
    obj: dict[str, Any],
    min_sec: int | None,
    max_sec: int | None,
    max_uptime: int | None,
) -> None:
    config: CLIConfig = obj["config"]
    console = Console()

    # Read current values from .env
    cur_min = 36
    cur_max = 69
    cur_uptime = 70
    if config.env_file.exists():
        for line in config.env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("AUTO_ROTATE_INTERVAL_MIN_SECONDS="):
                try: cur_min = int(line.split("=", 1)[1].strip())
                except: pass
            elif line.startswith("AUTO_ROTATE_INTERVAL_MAX_SECONDS="):
                try: cur_max = int(line.split("=", 1)[1].strip())
                except: pass
            elif line.startswith("AUTO_ROTATE_MAX_UPTIME_SECONDS="):
                try: cur_uptime = int(line.split("=", 1)[1].strip())
                except: pass

    # If no arguments provided, display current settings
    if min_sec is None:
        msg = (
            f"• Thời gian xoay tối thiểu: [bold cyan]{cur_min}s[/bold cyan]\n"
            f"• Thời gian xoay tối đa:     [bold cyan]{cur_max}s[/bold cyan]\n"
            f"• Giới hạn cứng Uptime:      [bold yellow]{cur_uptime}s[/bold yellow] (Bất kỳ IP nào quá thời gian này sẽ bị ép xoay ngay)\n\n"
            f"[dim]Cú pháp cài đặt: pia-proxy rotate-time <min_giây> <max_giây> [max_uptime_giây][/dim]\n"
            f"[dim]Ví dụ cấu hình chuẩn: pia-proxy rotate-time 36 69 70[/dim]"
        )
        console.print(Panel(msg, title="[bold yellow]Cấu Hình Chu Kỳ Xoay IP (Auto-Rotate Rules)[/bold yellow]", border_style="cyan"))
        return

    # Update values
    val_min = min_sec
    val_max = max_sec or (val_min + 30)
    val_uptime = max_uptime or (val_max + 1)

    if val_min < 5 or val_max <= val_min:
        console.print("[bold red]Lỗi: Thời gian tối đa phải lớn hơn thời gian tối thiểu (min >= 5s)![/bold red]")
        raise SystemExit(1)

    config.update_env_value("AUTO_ROTATE_INTERVAL_MIN_SECONDS", val_min)
    config.update_env_value("AUTO_ROTATE_INTERVAL_MAX_SECONDS", val_max)
    config.update_env_value("AUTO_ROTATE_MAX_UPTIME_SECONDS", val_uptime)

    console.print("[bold green]✔ Đã cập nhật quy tắc xoay IP thành công:[/bold green]")
    console.print(f"  • Chu kỳ xoay tự động: [bold cyan]{val_min}s – {val_max}s[/bold cyan]")
    console.print(f"  • Giới hạn cứng Uptime: [bold yellow]{val_uptime}s[/bold yellow] (Ép xoay)")
    console.print("[dim]Chạy 'pia-proxy restart' để áp dụng chu kỳ mới cho backend.[/dim]")
