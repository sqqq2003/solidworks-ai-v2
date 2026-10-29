"""SolidWorks 类型库（typelib）主版本探测与加载。

SolidWorks 的类型库 GUID 跨版本稳定，变的是 ``HKCR\\TypeLib\\{GUID}`` 下的
版本子键（形如 ``"33.0"``）。但注册表子键并不可靠（实测本机枚举出 21、1，
而实际装的是 33），所以探测逻辑是：

1. 从注册表读出已装的主版本号（仅作候选来源之一）；
2. 合并一张兜底版本表（新→旧）；
3. 按版本号从高到低逐个 ``EnsureModule`` 试加载，取第一个能加载的。

「能加载」说明该版本的类型库确实注册了，取最高即最新安装的那版。
"""

from __future__ import annotations

from typing import Any

SOLIDWORKS_TYPELIB_ID = "{83A33D31-27C5-11CE-BFD4-00400513BB57}"
# 33 对应 SW2025。以前这个数是写死的，换一台装了别的版本 SolidWorks 的机器，
# EnsureModule 就会失败、整个生成功能直接不可用。现在只在探测不到时当兜底。
SOLIDWORKS_TYPELIB_MAJOR = 33
# 装了多个版本时按新到旧试；探测不到已装版本就按这张表回退。
_TRY_TYPELIB_MAJORS = (33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23)
_TYPELIB_MAJOR_CACHE: int | None = None


def _installed_typelib_majors() -> tuple[int, ...]:
    """从注册表读出本机已注册的 SolidWorks 类型库主版本号。"""

    try:
        import winreg
    except ImportError:  # 非 Windows 上根本连不了 SolidWorks
        return ()
    try:
        with winreg.OpenKey(
            winreg.HKEY_CLASSES_ROOT,
            f"TypeLib\\{SOLIDWORKS_TYPELIB_ID}",
        ) as key:
            count = winreg.QueryInfoKey(key)[0]
            names = [winreg.EnumKey(key, index) for index in range(count)]
    except OSError:
        return ()
    majors: list[int] = []
    for name in names:
        head = name.split(".", 1)[0]
        if head.isdigit():
            majors.append(int(head))
    return tuple(sorted(set(majors), reverse=True))


def typelib_major() -> int:
    """挑一个本机真能加载的类型库主版本号，结果缓存下来。

    顺序：注册表里已装的（新→旧）→ 兜底表里逐个试（新→旧）→ 写死的 33。
    """

    global _TYPELIB_MAJOR_CACHE
    if _TYPELIB_MAJOR_CACHE is not None:
        return _TYPELIB_MAJOR_CACHE

    candidates = set(_installed_typelib_majors())
    candidates.update(_TRY_TYPELIB_MAJORS)
    candidates.add(SOLIDWORKS_TYPELIB_MAJOR)

    try:
        import win32com.client
    except ImportError:
        _TYPELIB_MAJOR_CACHE = SOLIDWORKS_TYPELIB_MAJOR
        return _TYPELIB_MAJOR_CACHE

    for major in sorted(candidates, reverse=True):
        try:
            win32com.client.gencache.EnsureModule(
                SOLIDWORKS_TYPELIB_ID, 0, major, 0
            )
        except Exception:  # noqa: BLE001 - EnsureModule 失败就换下一个版本
            continue
        _TYPELIB_MAJOR_CACHE = major
        return major

    # 一个都加载不了时仍返回兜底值，让调用方拿到原本的报错，而不是这里静默吞掉。
    _TYPELIB_MAJOR_CACHE = SOLIDWORKS_TYPELIB_MAJOR
    return _TYPELIB_MAJOR_CACHE


def ensure_solidworks_typelib() -> Any:
    """拿到 SolidWorks 强类型模块，自动适配当前装的版本。"""

    import win32com.client

    return win32com.client.gencache.EnsureModule(
        SOLIDWORKS_TYPELIB_ID, 0, typelib_major(), 0
    )
