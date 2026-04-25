"""
项目日志：控制台 + 滚动文件（UTF-8），进程内只初始化一次。

环境变量：
  LOG_LEVEL   默认 INFO，可设为 DEBUG / WARNING / ERROR
  LOG_DIR     日志目录，未设置时使用项目根目录下 logs/
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_APP_LOGGER_NAME = "fff_dianshang"


def _parse_level(name: str) -> int:
    return getattr(logging, name.upper(), logging.INFO)


def setup_logging(
    *,
    level: int | None = None,
    log_dir: Path | None = None,
    console: bool = True,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """
    配置根日志记录器（幂等）。返回应用级 logger。
    """
    root = logging.getLogger()
    if root.handlers:
        return logging.getLogger(_APP_LOGGER_NAME)

    if level is None:
        level = _parse_level(os.environ.get("LOG_LEVEL", "INFO"))

    if log_dir is None:
        raw = os.environ.get("LOG_DIR", "").strip()
        if raw:
            log_dir = Path(raw)
        else:
            log_dir = Path(__file__).resolve().parent.parent / "logs"

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        sys.stderr.write(f"[logging] 无法创建日志目录 {log_dir}: {e}\n")

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root.setLevel(level)

    log_file = log_dir / "app.log"
    try:
        fh = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        fh.setLevel(level)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError as e:
        sys.stderr.write(f"[logging] 无法写入日志文件 {log_file}: {e}\n")

    if console:
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(level)
        ch.setFormatter(fmt)
        root.addHandler(ch)

    log = logging.getLogger(_APP_LOGGER_NAME)
    log.info("日志已初始化，级别=%s，目录=%s", logging.getLevelName(level), log_dir)
    return log


def get_logger(name: str | None = None) -> logging.Logger:
    """子模块建议使用：get_logger(__name__)。"""
    if name:
        return logging.getLogger(name)
    return logging.getLogger(_APP_LOGGER_NAME)
