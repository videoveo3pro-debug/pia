from __future__ import annotations

import json
from typing import Any

import click
from rich.console import Console

from cli.config import CLIConfig


@click.command("export", help="Export proxy connection strings formatted for bots, antidetect browsers, or crawlers.")
@click.option(
    "--format",
    "-f",
    type=click.Choice(["url", "standard", "curl", "json", "env"]),
    default="standard",
    help="Output format (standard = IP:PORT:USER:PASS).",
    show_default=True,
)
@click.option("--host", "-H", default=None, help="Custom server IP or hostname override.")
@click.pass_obj
def export_cmd(obj: dict[str, Any], format: str, host: str | None) -> None:
    config: CLIConfig = obj["config"]
    console = Console()

    server_ip = host or config.get_public_ip()
    port = config.proxy_port
    user = config.socks5_user
    pwd = config.socks5_pass

    if format == "standard":
        # IP:PORT:USER:PASS format commonly accepted by antidetect tools
        click.echo(f"{server_ip}:{port}:{user}:{pwd}")
    elif format == "url":
        click.echo(f"socks5h://{user}:{pwd}@{server_ip}:{port}")
    elif format == "curl":
        click.echo(f"curl -x socks5h://{user}:{pwd}@{server_ip}:{port} https://api.ipify.org")
    elif format == "json":
        data = {
            "type": "socks5",
            "host": server_ip,
            "port": port,
            "username": user,
            "password": pwd,
            "url": f"socks5h://{user}:{pwd}@{server_ip}:{port}",
            "standard": f"{server_ip}:{port}:{user}:{pwd}",
        }
        click.echo(json.dumps(data, indent=2))
    elif format == "env":
        click.echo(f'export ALL_PROXY="socks5h://{user}:{pwd}@{server_ip}:{port}"')
        click.echo(f'export HTTP_PROXY="socks5h://{user}:{pwd}@{server_ip}:{port}"')
        click.echo(f'export HTTPS_PROXY="socks5h://{user}:{pwd}@{server_ip}:{port}"')
