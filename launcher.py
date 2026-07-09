from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from streamlit.web import cli as stcli

APP_TITLE = "账单合并分析器"
HOST = "127.0.0.1"
BROWSER_DELAY_SECONDS = 2.0


def resource_path(filename: str) -> Path:
    """Return the path to bundled files both in source and PyInstaller modes."""
    if getattr(sys, "frozen", False):
        bundle_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates = [
            bundle_dir / filename,
            Path(sys.executable).resolve().parent / filename,
        ]
    else:
        candidates = [Path(__file__).resolve().parent / filename]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    checked = "、".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"找不到应用文件 {filename}。已检查：{checked}")


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def open_browser_later(url: str) -> None:
    time.sleep(BROWSER_DELAY_SECONDS)
    webbrowser.open(url)


def configure_streamlit_environment() -> None:
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    os.environ.setdefault("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "false")
    os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
    os.environ.setdefault("STREAMLIT_SERVER_FILE_WATCHER_TYPE", "none")
    os.environ.setdefault("STREAMLIT_SERVER_RUN_ON_SAVE", "false")
    os.environ.setdefault("STREAMLIT_CLIENT_TOOLBAR_MODE", "minimal")


def run() -> None:
    configure_streamlit_environment()

    app_path = resource_path("app.py")
    port = find_free_port()
    url = f"http://{HOST}:{port}"

    threading.Thread(target=open_browser_later, args=(url,), daemon=True).start()

    sys.argv = [
        "streamlit",
        "run",
        str(app_path),
        "--server.address",
        HOST,
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
        "--global.developmentMode",
        "false",
        "--server.fileWatcherType",
        "none",
        "--client.toolbarMode",
        "minimal",
    ]
    stcli.main()


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"{APP_TITLE} 启动失败：{exc}")
        input("按回车键退出...")
