"""Failures always name the size set, the stage, and a mate class."""

from __future__ import annotations


class RollerFrameError(Exception):
    """Base error. ``mate_class`` is a logical class, never a guessed feature id."""

    def __init__(
        self,
        message: str,
        *,
        size_name: str = "",
        stage: str = "",
        mate_class: str = "",
    ) -> None:
        super().__init__(message)
        self.size_name = size_name
        self.stage = stage
        self.mate_class = mate_class


class GeometryError(RollerFrameError):
    pass


class ConfigError(RollerFrameError):
    pass


class CopyError(RollerFrameError):
    pass


class SolidWorksError(RollerFrameError):
    pass


def format_failure(exc: RollerFrameError) -> str:
    lines = ["滚筒机架改参失败"]
    if exc.size_name:
        lines.append(f"尺寸: {exc.size_name}")
    if exc.stage:
        lines.append(f"阶段: {exc.stage}")
    if exc.mate_class:
        lines.append(f"配合类: {exc.mate_class}")
    lines.append(f"说明: {exc}")
    lines.append("已停止。不会把未完成的结果当作成功输出。")
    return "\n".join(lines) + "\n"


def exit_code(exc: RollerFrameError) -> int:
    if isinstance(exc, ConfigError):
        return 2
    if isinstance(exc, GeometryError):
        return 3
    if isinstance(exc, CopyError):
        return 4
    return 5
