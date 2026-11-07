"""应用日志：写入轮转文件，便于在生成失败后回看细节。"""

from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

APP_FOLDER_NAME = "CadSheetMetalTool"
LOG_FOLDER_NAME = "logs"
LOG_FILE_NAME = "app.log"
MAX_LOG_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"

_configured_path: Path | None = None


def log_directory() -> Path:
    """返回日志目录；优先使用 Windows 的 LOCALAPPDATA。"""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        root = Path(base)
    else:
        try:
            root = Path.home() / ".cache"
        except RuntimeError:
            # 极少数环境（服务账号、被清空的环境变量）取不到用户目录。
            root = Path.cwd()
    return root / APP_FOLDER_NAME / LOG_FOLDER_NAME


def log_file_path() -> Path:
    return log_directory() / LOG_FILE_NAME


def _candidate_log_paths() -> tuple[Path, ...]:
    """日志候选位置：优先用户目录，其次程序所在目录。"""
    candidates = [log_file_path()]
    beside_program = Path(__file__).resolve().parent / LOG_FOLDER_NAME / LOG_FILE_NAME
    if beside_program not in candidates:
        candidates.append(beside_program)
    return tuple(candidates)


def configure_logging(level: int = logging.INFO) -> Path | None:
    """配置根日志。

    返回日志文件路径；如果日志文件无法创建（例如目录权限不足），
    则返回 None 并且只保留控制台输出，程序仍可正常使用。
    """
    global _configured_path
    candidates = _candidate_log_paths()
    path = candidates[0]
    if _configured_path == path:
        return path
    shutdown_logging()
    root = logging.getLogger()
    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT)

    stream = sys.stderr
    if stream is not None:
        stream_handler = logging.StreamHandler(stream)
        stream_handler.setFormatter(formatter)
        stream_handler._cad_sheet_metal_handler = True  # type: ignore[attr-defined]
        root.addHandler(stream_handler)

    failure: OSError | None = None
    for candidate in candidates:
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                candidate,
                maxBytes=MAX_LOG_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        except OSError as error:
            if failure is None:
                failure = error
            continue
        file_handler.setFormatter(formatter)
        file_handler._cad_sheet_metal_handler = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)
        _configured_path = candidate
        return candidate

    logging.getLogger(__name__).warning(
        "无法创建日志文件 %s：%s",
        "、".join(str(candidate) for candidate in candidates),
        failure,
    )
    return None


def shutdown_logging() -> None:
    """移除本模块安装的日志处理器并关闭文件，便于测试或干净退出。"""
    global _configured_path
    _configured_path = None
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_cad_sheet_metal_handler", False):
            root.removeHandler(handler)
            handler.close()


def install_exception_hooks() -> None:
    """登记全局异常钩子，避免后台线程异常被静默吞掉。"""
    previous_hook = sys.excepthook
    uncaught_logger = logging.getLogger("uncaught")

    def handle_exception(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_traceback: TracebackType | None,
    ) -> None:
        uncaught_logger.critical(
            "未捕获异常",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        previous_hook(exc_type, exc_value, exc_traceback)

    def handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        uncaught_logger.critical(
            "后台线程 %s 未捕获异常",
            args.thread.name if args.thread is not None else "未知线程",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception
