from __future__ import annotations

from typing import Any

import click
from rich.console import Console
from rich.table import Table

from cli.config import CLIConfig


@click.group("config", help="Manage proxy gateway credentials, environment settings, and ports.")
def config_group() -> None:
    pass


@config_group.command("show", help="Display all active configuration parameters.")
@click.pass_obj
def config_show(obj: dict[str, Any]) -> None:
    config: CLIConfig = obj["config"]
    console = Console()

    table = Table(title="[bold cyan]PIA Proxy Configuration Summary[/bold cyan]", expand=True)
    table.add_column("Parameter", style="bold white", width=24)
    table.add_column("Value", style="yellow")
    table.add_column("Location / Source", style="dim")

    table.add_row("Project Root", str(config.project_root), "Detected")
    table.add_row("Compose Dir", str(config.compose_dir), "Detected")
    table.add_row(".env File", str(config.env_file), "Detected")
    table.add_row("Credentials Dir", str(config.credentials_dir), "Detected")
    table.add_row("SOCKS5 Proxy Port", str(config.proxy_port), ".env (PROXY_PORT)")
    table.add_row("SOCKS5 Username", config.socks5_user, ".env (SOCKS5_USERNAME)")
    table.add_row("SOCKS5 Password", "***" + config.socks5_pass[-4:] if len(config.socks5_pass) > 4 else "***", ".env (SOCKS5_PASSWORD)")
    table.add_row("Backend API Port", str(config.api_port), ".env (API_PORT)")
    table.add_row("Active Worker Count", str(config.worker_count), ".env (WORKER_COUNT)")
    table.add_row("Max Worker Count", str(config.max_worker_count), ".env (MAX_WORKER_COUNT)")

    u, p = config.get_pia_account()
    if u and p:
        table.add_row("PIA Account", f"{u} / {'*' * len(p)}", "credentials/pia_account_1")
    else:
        table.add_row("PIA Account", "[bold red]Not Configured![/bold red]", "credentials/pia_account_1")

    session_file = config.credentials_dir / "pia_session_slot_1.json"
    table.add_row("PIA Session Cache", "Present" if session_file.exists() else "Missing", "credentials/pia_session_slot_1.json")

    console.print(table)


@config_group.command("set-credentials", help="Configure PIA account username and password.")
@click.option("--username", "-u", prompt=True, help="PIA Username (e.g. p1234567)")
@click.option("--password", "-p", prompt=True, hide_input=True, confirmation_prompt=True, help="PIA Password")
@click.pass_obj
def config_set_credentials(obj: dict[str, Any], username: str, password: str) -> None:
    config: CLIConfig = obj["config"]
    console = Console()

    if not username.strip() or not password.strip():
        console.print("[bold red]Username and password cannot be empty.[/bold red]")
        raise SystemExit(1)

    config.set_pia_account(username.strip(), password.strip())
    console.print(f"[bold green]✔ Saved PIA account credentials to {config.credentials_dir / 'pia_account_1'}.[/bold green]")


@config_group.command("set-proxy-auth", help="Set username and password required for SOCKS5 proxy clients.")
@click.option("--username", "-u", prompt=True, help="Proxy username")
@click.option("--password", "-p", prompt=True, hide_input=True, confirmation_prompt=True, help="Proxy password")
@click.pass_obj
def config_set_proxy_auth(obj: dict[str, Any], username: str, password: str) -> None:
    config: CLIConfig = obj["config"]
    console = Console()

    config.update_env_value("SOCKS5_USERNAME", username.strip())
    config.update_env_value("SOCKS5_PASSWORD", password.strip())
    console.print("[bold green]✔ Updated SOCKS5 credentials in .env.[/bold green]")
    console.print("[dim]Note: Restart proxy pool with 'pia-proxy restart' to apply new proxy credentials.[/dim]")


@config_group.command("set-port", help="Set the external port for SOCKS5 gateway or backend API.")
@click.option("--proxy-port", type=int, default=None, help="New SOCKS5 gateway port (e.g. 1087, 1080)")
@click.option("--api-port", type=int, default=None, help="New Backend API port (e.g. 8007)")
@click.pass_obj
def config_set_port(obj: dict[str, Any], proxy_port: int | None, api_port: int | None) -> None:
    config: CLIConfig = obj["config"]
    console = Console()

    if proxy_port:
        config.update_env_value("PROXY_PORT", proxy_port)
        console.print(f"[bold green]✔ Set PROXY_PORT={proxy_port} in .env.[/bold green]")
    if api_port:
        config.update_env_value("API_PORT", api_port)
        console.print(f"[bold green]✔ Set API_PORT={api_port} in .env.[/bold green]")

    console.print("[dim]Note: Restart proxy pool with 'pia-proxy restart' to apply port changes.[/dim]")
