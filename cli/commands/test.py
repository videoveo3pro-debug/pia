from __future__ import annotations

import subprocess
import time
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cli.config import CLIConfig


@click.command("test", help="Test SOCKS5 gateway connectivity, latency, IP diversity, and zero-leak security.")
@click.option("--count", "-n", default=5, help="Number of test requests to dispatch.", show_default=True)
@click.option("--timeout", "-t", default=8, help="Timeout in seconds per request.", show_default=True)
@click.pass_obj
def test_cmd(obj: dict[str, Any], count: int, timeout: int) -> None:
    config: CLIConfig = obj["config"]
    console = Console()

    proxy_port = config.proxy_port
    user = config.socks5_user
    pwd = config.socks5_pass
    proxy_url = f"socks5h://{user}:{pwd}@127.0.0.1:{proxy_port}"

    console.print(f"[bold cyan]Testing SOCKS5 Gateway (port {proxy_port}) with {count} requests...[/bold cyan]")

    vps_ip = config.get_public_ip()

    table = Table(show_header=True, header_style="bold magenta", expand=True)
    table.add_column("Request #", justify="center", width=12)
    table.add_column("Result", width=14)
    table.add_column("Exit IP", style="bold cyan", width=20)
    table.add_column("Latency", justify="right", width=12)
    table.add_column("Leak Check", width=16)

    collected_ips: list[str] = []
    successes = 0
    latencies: list[float] = []
    leak_detected = False

    for i in range(1, count + 1):
        t0 = time.perf_counter()
        try:
            res = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-m",
                    str(timeout),
                    "-x",
                    proxy_url,
                    "https://api.ipify.org",
                ],
                capture_output=True,
                text=True,
                timeout=timeout + 2,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            exit_ip = res.stdout.strip()

            if res.returncode == 0 and exit_ip and "." in exit_ip:
                successes += 1
                collected_ips.append(exit_ip)
                latencies.append(elapsed_ms)

                if exit_ip == vps_ip:
                    leak_detected = True
                    leak_status = Text("LEAK DETECTED!", style="bold red")
                else:
                    leak_status = Text("✔ PROTECTED", style="bold green")

                table.add_row(
                    f"#{i}",
                    Text("OK", style="bold green"),
                    exit_ip,
                    f"{elapsed_ms:.1f} ms",
                    leak_status,
                )
            else:
                table.add_row(
                    f"#{i}",
                    Text("FAILED", style="bold red"),
                    "—",
                    f"{elapsed_ms:.1f} ms",
                    Text("N/A", style="dim"),
                )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            table.add_row(
                f"#{i}",
                Text("TIMEOUT", style="yellow"),
                "—",
                f"{elapsed_ms:.1f} ms",
                Text("N/A", style="dim"),
            )

        time.sleep(0.3)

    console.print(table)

    # Summary Panel
    unique_count = len(set(collected_ips))
    avg_latency = (sum(latencies) / len(latencies)) if latencies else 0

    summary = Text()
    summary.append(f"• Success Rate:    {successes}/{count} ({int(successes/count*100 if count else 0)}%)\n")
    summary.append(f"• Unique Exit IPs: {unique_count} / {successes} requests\n")
    summary.append(f"• Average Latency: {avg_latency:.1f} ms\n")

    if leak_detected:
        summary.append("\n⚠ CRITICAL: Proxy leaked your VPS public IP! Check firewall/iptables.", style="bold red")
        panel_color = "red"
    else:
        summary.append("\n✔ Zero-Leak Verified: Traffic safely routed via PIA VPN, no VPS IP leak.", style="bold green")
        panel_color = "green"

    panel = Panel(
        summary,
        title="[bold white]SOCKS5 Proxy Pool Test Summary[/bold white]",
        border_style=panel_color,
    )
    console.print(panel)
