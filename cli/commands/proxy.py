from __future__ import annotations

from typing import Any

import click
from rich.console import Console
from rich.panel import Panel

from cli.config import CLIConfig


@click.command("proxy", help="View or update SOCKS5 proxy port and authentication credentials.")
@click.argument("port", type=int, required=False, default=None)
@click.argument("username", required=False, default=None)
@click.argument("password", required=False, default=None)
@click.pass_obj
def proxy_cmd(
    obj: dict[str, Any],
    port: int | None,
    username: str | None,
    password: str | None,
) -> None:
    config: CLIConfig = obj["config"]
    console = Console()

    # If no arguments provided, view current proxy info
    if port is None and username is None and password is None:
        ip = config.get_public_ip()
        msg = (
            f"• Cổng SOCKS5 (Port):     [bold cyan]{config.proxy_port}[/bold cyan]\n"
            f"• Tài khoản đăng nhập:    [bold white]{config.socks5_user}[/bold white]\n"
            f"• Mật khẩu:               [bold white]{'***' + config.socks5_pass[-4:] if len(config.socks5_pass) > 4 else '***'}[/bold white]\n"
            f"• URL kết nối nội bộ:     [bold green]socks5h://{config.socks5_user}:{config.socks5_pass}@127.0.0.1:{config.proxy_port}[/bold green]\n"
            f"• Chuỗi Proxy công khai:  [bold green]{ip}:{config.proxy_port}:{config.socks5_user}:{config.socks5_pass}[/bold green]\n\n"
            f"[dim]Cú pháp đổi cấu hình: pia-proxy proxy <cổng> [username] [password][/dim]\n"
            f"[dim]Ví dụ: pia-proxy proxy 1087 myuser mypass[/dim]"
        )
        console.print(Panel(msg, title="[bold yellow]Cấu Hình Cổng SOCKS5 Proxy[/bold yellow]", border_style="cyan"))
        return

    # Update port
    if port:
        if port < 1024 or port > 65535:
            console.print("[bold red]Lỗi: Cổng phải nằm trong khoảng từ 1024 đến 65535.[/bold red]")
            raise SystemExit(1)
        config.update_env_value("PROXY_PORT", port)

    # Update username
    if username:
        config.update_env_value("SOCKS5_USERNAME", username.strip())

    # Update password
    if password:
        config.update_env_value("SOCKS5_PASSWORD", password.strip())

    console.print("[bold green]✔ Đã cập nhật cấu hình SOCKS5 Gateway thành công:[/bold green]")
    if port:
        console.print(f"  • Cổng mới: [bold cyan]{port}[/bold cyan]")
    if username:
        console.print(f"  • Username mới: [bold cyan]{username}[/bold cyan]")
    if password:
        console.print(f"  • Mật khẩu mới: [bold cyan]******[/bold cyan]")
    console.print("[dim]Chạy 'pia-proxy restart' để áp dụng cấu hình mới vào container.[/dim]")
