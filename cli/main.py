from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click

from cli import __version__
from cli.api_client import APIClient
from cli.commands.doctor import doctor_cmd
from cli.commands.export import export_cmd
from cli.commands.logs import logs_cmd
from cli.commands.proxy import proxy_cmd
from cli.commands.rotate import rotate_cmd
from cli.commands.rotate_time import rotate_time_cmd
from cli.commands.service import restart_cmd, start_cmd, stop_cmd
from cli.commands.setup import setup_cmd
from cli.commands.status import status_cmd
from cli.commands.test import test_cmd
from cli.commands.workers import workers_cmd
from cli.config import CLIConfig
from cli.docker_ctl import DockerController


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    help="""
PIA SOCKS5 Multi-Worker Proxy Gateway - Bộ Công Cụ CLI Quản Trị Proxy
""",
)
@click.version_option(__version__, "-v", "--version", message="pia-proxy version %(version)s")
@click.option("--project-dir", "-d", default=None, help="Đường dẫn thư mục dự án tuỳ chỉnh.")
@click.pass_context
def cli(ctx: click.Context, project_dir: str | None) -> None:
    config = CLIConfig.load(custom_dir=project_dir)
    client = APIClient(base_url=config.api_base_url, token=config.api_token)
    docker_ctl = DockerController(config=config)

    ctx.obj = {
        "config": config,
        "client": client,
        "docker_ctl": docker_ctl,
    }


# Bộ Lệnh Cốt Lõi:
cli.add_command(setup_cmd)        # Cấu hình ban đầu (tài khoản PIA, port)
cli.add_command(proxy_cmd)        # Xem / đổi cổng proxy, username, password
cli.add_command(workers_cmd)      # Xem / đổi số lượng worker (scale 1-50)
cli.add_command(rotate_time_cmd)  # Cấu hình thời gian xoay IP / Uptime
cli.add_command(start_cmd)        # Khởi động (Staggered Boot, Zero-Crash)
cli.add_command(stop_cmd)         # Dừng hệ thống
cli.add_command(restart_cmd)      # Khởi động lại
cli.add_command(status_cmd)       # Xem trạng thái IP, Uptime, Worker
cli.add_command(rotate_cmd)       # Ép xoay IP tức thì
cli.add_command(test_cmd)         # Kiểm thử tốc độ & Zero-leak
cli.add_command(export_cmd)       # Xuất chuỗi proxy (standard, url, json)

# Tiện ích:
cli.add_command(doctor_cmd)       # Kiểm tra môi trường hệ thống
cli.add_command(logs_cmd)         # Xem log thời gian thực


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
