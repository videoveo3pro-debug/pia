from __future__ import annotations

from typing import Any

import click

from cli.docker_ctl import DockerController


@click.command("logs", help="Tail or follow real-time logs from proxy containers or workers.")
@click.option("--service", "-s", default=None, help="Target container or service (e.g. 'gateway', 'backend', 'vpn-worker-1').")
@click.option("--tail", "-n", default=100, help="Number of historical lines to show.", show_default=True)
@click.option("--follow", "-f", is_flag=True, help="Follow log output continuously.")
@click.pass_obj
def logs_cmd(obj: dict[str, Any], service: str | None, tail: int, follow: bool) -> None:
    docker_ctl: DockerController = obj["docker_ctl"]

    svc_name = service
    if svc_name:
        if svc_name in {"gateway", "proxy-gateway", "haproxy"}:
            svc_name = "proxy-gateway"
        elif svc_name in {"api", "backend"}:
            svc_name = "backend"
        elif svc_name.isdigit():
            svc_name = f"vpn-worker-{svc_name}"
        elif svc_name.startswith("worker"):
            svc_name = f"vpn-{svc_name}"

    try:
        for line in docker_ctl.stream_logs(service=svc_name, tail=tail, follow=follow):
            click.echo(line)
    except KeyboardInterrupt:
        pass
