"""
在 Windows 上查找 Chrome，并在需要时启动带 --remote-debugging-port 的实例。
供安装部署后的「一键启动」使用（无需用户手敲命令行）。
"""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _port_is_open(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def find_chrome_executable() -> Optional[Path]:
    """尽量自动发现本机 chrome.exe（以 Windows 为主）。"""
    if sys.platform == "win32":
        try:
            import winreg

            for hkey in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(
                        hkey,
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
                    ) as k:
                        path, _ = winreg.QueryValueEx(k, "")
                        p = Path(path)
                        if p.is_file():
                            return p
                except OSError:
                    pass
        except Exception:
            pass

        roots = []
        for ev in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            v = os.environ.get(ev)
            if v:
                roots.append(Path(v))
        for root in roots:
            cand = root / "Google" / "Chrome" / "Application" / "chrome.exe"
            if cand.is_file():
                return cand

    for name in ("google-chrome", "chromium", "chromium-browser"):
        p = shutil_which(name)
        if p:
            return Path(p)
    return None


def shutil_which(cmd: str) -> Optional[str]:
    from shutil import which

    return which(cmd)


def ensure_chrome_remote_debugging(
    port: int = 9222,
    user_data_dir: Optional[Path] = None,
    wait_seconds: float = 8.0,
) -> Tuple[bool, str]:
    """
    若本机 127.0.0.1:port 已有服务则直接成功；
    否则尝试启动 Chrome（独立 user-data-dir，不干扰用户日常 Chrome 配置）。
    返回 (成功, 失败原因或空字符串)。
    """
    if not logging.getLogger().handlers:
        from picker_tool.logging_config import setup_logging

        setup_logging()

    if _port_is_open("127.0.0.1", port):
        logger.info("远程调试端口已可用: %s", port)
        return True, ""

    chrome = find_chrome_executable()
    env_override = os.environ.get("CHROME_EXE", "").strip()
    if env_override:
        ep = Path(env_override)
        if ep.is_file():
            chrome = ep
        else:
            return False, f"环境变量 CHROME_EXE 指向无效路径：{env_override}"

    if not chrome:
        return False, (
            "未找到 Google Chrome（chrome.exe）。\n"
            "请让目标电脑先安装 Chrome，或设置环境变量 CHROME_EXE 为 chrome.exe 的完整路径。"
        )

    if user_data_dir is None:
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or "."
        user_data_dir = Path(base) / "chrome-pw-debug"

    try:
        user_data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, f"无法创建用户数据目录 {user_data_dir}: {e}"

    args = [
        str(chrome),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={str(user_data_dir)}",
    ]

    logger.info("启动 Chrome 远程调试: port=%s user_data=%s", port, user_data_dir)
    try:
        # 独立进程，关闭启动器不会结束 Chrome
        popen_kw: dict = dict(
            args=args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if sys.platform != "win32":
            popen_kw["close_fds"] = True
        subprocess.Popen(**popen_kw)
    except OSError as e:
        return False, f"无法启动 Chrome: {e}"

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if _port_is_open("127.0.0.1", port):
            logger.info("Chrome 调试端口已就绪: %s", port)
            return True, ""
        time.sleep(0.15)

    logger.error("Chrome 启动后端口未就绪: %s", port)
    return (
        False,
        f"Chrome 进程已尝试启动，但在 {wait_seconds:.0f} 秒内 {port} 端口仍未监听。\n"
        "可能被安全软件拦截，或端口被占用。可尝试更换环境变量 PICKER_DEBUG_PORT。",
    )
