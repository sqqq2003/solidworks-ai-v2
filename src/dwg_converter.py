from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


class DwgConversionError(RuntimeError):
    """Raised when a DWG drawing cannot be converted to DXF."""


def _open_document_titles(solidworks: Any) -> set[str]:
    titles: set[str] = set()
    document = solidworks.GetFirstDocument
    while document is not None:
        title = document.GetTitle
        titles.add(title)
        document = document.GetNext
    return titles


def _dwg2dxf_candidates() -> list[Path]:
    found: list[Path] = []
    which = shutil.which("dwg2dxf")
    if which:
        found.append(Path(which))
    for candidate in (
        Path("/tmp/libredwg-prefix/bin/dwg2dxf"),
        Path.home() / "libredwg-prefix" / "bin" / "dwg2dxf",
        Path("C:/Program Files/LibreDWG/bin/dwg2dxf.exe"),
        Path("C:/libredwg/bin/dwg2dxf.exe"),
    ):
        if candidate.is_file() and candidate not in found:
            found.append(candidate)
    return found


def convert_dwg_with_libredwg(source: str | Path, target: str | Path) -> None:
    """用 LibreDWG ``dwg2dxf`` 转换。简略草图在 SolidWorks 导入失败时可用。"""

    source_path = Path(source).resolve()
    target_path = Path(target).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"找不到 DWG 文件：{source_path}")

    converters = _dwg2dxf_candidates()
    if not converters:
        raise DwgConversionError(
            "未找到 LibreDWG（dwg2dxf）。可安装 LibreDWG，或改用 SolidWorks 导入。"
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        target_path.unlink()

    env = os.environ.copy()
    last_error = ""
    for converter in converters:
        lib_dir = converter.parent.parent / "lib"
        if lib_dir.is_dir():
            env["LD_LIBRARY_PATH"] = (
                f"{lib_dir}{os.pathsep}{env.get('LD_LIBRARY_PATH', '')}"
            )
        try:
            completed = subprocess.run(
                [str(converter), "-o", str(target_path), str(source_path)],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
        except OSError as error:
            last_error = str(error)
            continue
        if target_path.is_file() and target_path.stat().st_size > 0:
            return
        last_error = (completed.stderr or completed.stdout or "").strip() or (
            f"exit {completed.returncode}"
        )
    raise DwgConversionError(f"LibreDWG 转换 DWG 失败：{last_error}")


def convert_dwg_with_solidworks(source: str | Path, target: str | Path) -> None:
    import sw_session

    source_path = Path(source).resolve()
    target_path = Path(target).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"找不到 DWG 文件：{source_path}")
    if not sw_session.on_task_sta():
        sw_session.run_on_task_sta(
            lambda: convert_dwg_with_solidworks(source, target),
            timeout=sw_session.SW_SESSION_CALL_TIMEOUT_SEC,
            task_name="convert_dwg_with_solidworks",
        )
        return
    lease = sw_session.current_lease()
    sw_session.require_model_write(lease)

    try:
        import pythoncom
        import win32com.client
    except ImportError as error:
        raise DwgConversionError(
            "DWG 导入需要 pywin32；请运行 python -m pip install -r requirements.txt。"
        ) from error

    class _DispatchOnly(Exception):
        """Sentinel so connect always takes Dispatch and never treats that as proof."""

    initialized = False
    solidworks: Any = None
    imported_document: Any = None
    imported_title: str | None = None
    try:
        pythoncom.CoInitialize()
        initialized = True

        def _dispatch() -> Any:
            return win32com.client.Dispatch("SldWorks.Application")

        solidworks, _created_here = sw_session.connect_application(
            lease,
            get_active=lambda: (_ for _ in ()).throw(_DispatchOnly()),
            dispatch=_dispatch,
            list_titles=lambda app: list(_open_document_titles(app)),
            is_absent=lambda error: isinstance(error, _DispatchOnly),
        )
        if lease is not None:
            lease.note_bound_application(solidworks)
        sw_session.require_model_write(lease)
        existing_titles = _open_document_titles(solidworks)

        import_data = solidworks.GetImportFileData(str(source_path))
        if import_data is None:
            raise DwgConversionError("SolidWorks 未能为此 DWG 创建导入设置。")

        sw_session.require_model_write(lease)
        loaded = solidworks.LoadFile3(str(source_path), "", import_data)
        document = solidworks.ActiveDoc
        if document is not None and document.GetTitle not in existing_titles:
            imported_document = document
        if not loaded:
            raise DwgConversionError("SolidWorks 未能导入此 DWG 文件。")
        if document is None:
            raise DwgConversionError("DWG 已导入，但 SolidWorks 没有返回活动文档。")
        if imported_document is None:
            raise DwgConversionError(
                "此 DWG 已在 SolidWorks 中打开。请先关闭该图纸，再重新导入，"
                "以避免修改当前打开的文档。"
            )
        if document.GetType != 3:
            raise DwgConversionError("SolidWorks 没有将此 DWG 作为工程图导入。")

        target_path.parent.mkdir(parents=True, exist_ok=True)
        sw_session.require_model_write(lease)
        save_errors = document.SaveAs3(str(target_path), 0, 1)
        if save_errors != 0:
            raise DwgConversionError(
                f"SolidWorks 导出 DXF 失败，错误代码：{save_errors}。"
            )
        if not target_path.is_file() or target_path.stat().st_size == 0:
            raise DwgConversionError("SolidWorks 未生成有效的 DXF 导出文件。")
        title = imported_document.GetTitle
        imported_title = str(title() if callable(title) else title)
        if lease is not None and imported_title:
            lease.note_owned_document(imported_title, handle_id=id(imported_document))
    except (DwgConversionError, sw_session.SessionOwnershipError):
        raise
    except Exception as error:
        raise DwgConversionError(f"SolidWorks 处理 DWG 时出错：{error}") from error
    finally:
        try:
            if solidworks is not None:
                sw_session.release_task_documents(
                    lease,
                    solidworks,
                    title=imported_title,
                    close=bool(imported_title),
                )
        finally:
            if initialized:
                pythoncom.CoUninitialize()


def _filename_prefers_libredwg(source: str | Path) -> bool:
    """简略滚筒尺寸草图：LibreDWG 更能保留尺寸覆盖字（700 vs 测量 655）。"""

    name = Path(source).name
    markers = ("滚筒", "斜滚", "动力", "无动力", "尺寸图")
    return any(marker in name for marker in markers)


def has_libredwg() -> bool:
    """本机是否可用 dwg2dxf。"""

    return bool(_dwg2dxf_candidates())


def iter_dwg_converters(
    source: str | Path | None = None,
) -> list[tuple[str, Any]]:
    """返回按优先级排列的 (名称, 转换函数)。

    Drawing1.dwg 等通用名不含「滚筒」关键字时，旧逻辑会优先 SolidWorks；
    SW 常“转成功”却丢掉注记块，导致一张滚筒规格都识别不到。
    有 LibreDWG 时一律先试它（覆盖字/块注记更完整），再回退 SolidWorks。
    """

    _ = source  # 保留参数：调用方可按源文件区分策略；当前统一优先 LibreDWG。
    if has_libredwg():
        return [
            ("libredwg", convert_dwg_with_libredwg),
            ("solidworks", convert_dwg_with_solidworks),
        ]
    return [("solidworks", convert_dwg_with_solidworks)]


def convert_dwg_to_dxf(source: str | Path, target: str | Path) -> None:
    """DWG→DXF：有 LibreDWG 时优先用之，失败再试 SolidWorks。"""

    errors: list[str] = []
    for _name, converter in iter_dwg_converters(source):
        try:
            converter(source, target)
            return
        except DwgConversionError as error:
            errors.append(str(error))
        except ImportError as error:
            errors.append(str(error))

    raise DwgConversionError("；".join(errors) if errors else "DWG 转换失败。")
