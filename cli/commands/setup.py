from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel

from cli.config import CLIConfig


@click.command("setup", help="Quick 1-step setup: Configure PIA account, proxy port, and credentials.")
@click.option("--username", "-u", default=None, help="PIA Username (e.g. p1234567)")
@click.option("--password", "-p", default=None, help="PIA Password")
@click.option("--proxy-port", default=1087, type=int, help="SOCKS5 Gateway Port (default: 1087)")
@click.option("--proxy-user", default="proxy_user", help="SOCKS5 Proxy Username (default: proxy_user)")
@click.option("--proxy-pass", default="proxy_password_secure123", help="SOCKS5 Proxy Password")
@click.pass_obj
def setup_cmd(
    obj: dict[str, Any],
    username: str | None,
    password: str | None,
    proxy_port: int,
    proxy_user: str,
    proxy_pass: str,
) -> None:
    config: CLIConfig = obj["config"]
    console = Console()

    console.print(Panel("[bold cyan]PIA SOCKS5 Proxy Gateway - Quick Setup[/bold cyan]", border_style="cyan"))

    # 1. PIA Account
    if not username:
        curr_u, curr_p = config.get_pia_account()
        default_prompt = f" [{curr_u}]" if curr_u else ""
        username = click.prompt(f"Nhập PIA Username (vd: p1234567){default_prompt}", default=curr_u or "", show_default=False)
    if not password:
        password = click.prompt("Nhập PIA Password", hide_input=True, confirmation_prompt=True)

    if not username.strip() or not password.strip():
        console.print("[bold red]Lỗi: Username và Password của PIA không được để trống![/bold red]")
        raise SystemExit(1)

    config.set_pia_account(username.strip(), password.strip())

    # 2. SOCKS5 Configuration
    config.update_env_value("PROXY_PORT", proxy_port)
    config.update_env_value("SOCKS5_USERNAME", proxy_user)
    config.update_env_value("SOCKS5_PASSWORD", proxy_pass)

    # 3. Ensure TUN device and WireGuard module exist
    tun_path = Path("/dev/net/tun")
    if not tun_path.exists():
        try:
            subprocess.run(["mkdir", "-p", "/dev/net"], check=False)
            subprocess.run(["mknod", "/dev/net/tun", "c", "10", "200"], check=False)
        except Exception:
            pass
    try:
        subprocess.run(["modprobe", "wireguard"], check=False)
    except Exception:
        pass

    console.print(f"[bold green]✔ Đã lưu cấu hình tài khoản PIA vào {config.credentials_dir / 'pia_account_1'}[/bold green]")
    console.print(f"[bold green]✔ Cổng SOCKS5: {proxy_port} | User: {proxy_user}[/bold green]")
    console.print("\n[bold cyan]Hoàn tất cài đặt! Bạn có thể khởi động hệ thống ngay bằng lệnh:[/bold cyan]")
    console.print("  [bold green]pia-proxy start[/bold green]\n")
