"""一键全部导出前的确认窗。点「开始导出」才返回参数。"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Sequence

# 清单里最多一次显示多少行；再多就只给全选/全不选（真有一张图几十件也够用）。
MAX_LISTED_PARTS = 400


@dataclass(frozen=True)
class ExportAllOptions:
    output_dir: Path
    thickness_mm: float
    radius_mm: float
    angle_degrees: float
    # 勾选要导出的零件编号（SheetPartJob.label）。空元组表示一件都不导。
    selected_labels: tuple[str, ...] = ()
    # 清单里没显示出来的件（超过 MAX_LISTED_PARTS）默认也要。
    select_hidden: bool = False


@dataclass(frozen=True)
class PartRow:
    """确认窗清单里的一行。"""

    label: str
    size_text: str
    thickness_text: str
    bend_count: int
    quantity: int
    default_checked: bool = True


def list_part_rows(
    jobs: Sequence[object],
    *,
    default_thickness: float | None = None,
) -> list[PartRow]:
    """把识别出的件转成清单行。job 需要有 label / bend_indices / quantity / thickness_mm。

    尺寸没法从 job 直接拿（只有轮廓编号），这里留空由调用方补；调用方传进来
    的 job 若带 ``size_hint`` 就用它。
    """

    rows: list[PartRow] = []
    for job in jobs:
        label = str(getattr(job, "label", "") or "")
        bend_count = len(getattr(job, "bend_indices", ()) or ())
        quantity = int(getattr(job, "quantity", 1) or 1)
        thickness = getattr(job, "thickness_mm", None)
        source = str(getattr(job, "thickness_source", "") or "")
        if thickness is None:
            text = f"{default_thickness:g}（默认）" if default_thickness else "默认"
        else:
            text = f"{float(thickness):g}  {source}" if source else f"{float(thickness):g}"
        rows.append(
            PartRow(
                label=label,
                size_text=str(getattr(job, "size_hint", "") or ""),
                thickness_text=text.strip(),
                bend_count=bend_count,
                quantity=quantity,
            )
        )
    return rows


def _parse_positive(value: str, label: str, *, upper: float | None = None) -> float:
    try:
        number = float(value.strip())
    except ValueError as error:
        raise ValueError(f"{label}必须填写为数值。") from error
    if number <= 0:
        raise ValueError(f"{label}必须大于 0。")
    if upper is not None and number >= upper:
        raise ValueError(f"{label}必须小于 {upper:g}。")
    return number


def ask_export_all_options(
    parent: tk.Misc,
    *,
    part_count: int,
    bent_count: int,
    labeled_count: int,
    initial_dir: str,
    thickness: str,
    radius: str,
    angle: str,
    parts: Sequence[PartRow] = (),
) -> ExportAllOptions | None:
    """弹出导出确认窗。取消或关闭窗口时返回 None。

    ``parts`` 给出时，窗口里会列出逐件清单，可以勾掉不要的件。
    """

    dialog = tk.Toplevel(parent)
    dialog.title("一键全部导出")
    dialog.transient(parent)
    dialog.resizable(True, True)
    dialog.grab_set()

    result: dict[str, ExportAllOptions | None] = {"value": None}

    body = ttk.Frame(dialog, padding=(18, 16, 18, 8))
    body.grid(row=0, column=0, sticky="nsew")
    dialog.columnconfigure(0, weight=1)
    dialog.rowconfigure(0, weight=1)
    body.columnconfigure(1, weight=1)

    selected_var = tk.StringVar(value="")
    summary_label = ttk.Label(body, justify=tk.LEFT, wraplength=440)
    summary_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

    # ---- 零件清单 -------------------------------------------------------
    checked: dict[str, tk.BooleanVar] = {}
    listed = list(parts)[:MAX_LISTED_PARTS]
    hidden = list(parts)[MAX_LISTED_PARTS:]

    def refresh_summary() -> None:
        picked = sum(1 for row in listed if checked[row.label].get())
        total = part_count
        extra = ""
        if hidden:
            extra = f"（另有 {len(hidden)} 件超出可显示行数，按全选处理）"
        summary_label.configure(
            text=(
                f"识别到 {total} 块钣金件，其中 {bent_count} 块带折弯线{extra}。\n"
                f"厚度按图顶分区大字分列换算（已对上 {labeled_count} 块）；"
                f"没有大字的件用下面的默认板厚。\n"
                f"已勾选 {picked if not hidden else picked + len(hidden)} 件，"
                f"没勾的不会导出。"
            )
        )

    list_frame: ttk.Frame | None = None
    if listed:
        tools = ttk.Frame(body)
        tools.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        ttk.Label(tools, text="要导出的件（取消勾选就不要）").pack(side=tk.LEFT)

        list_frame = ttk.Frame(body)
        list_frame.grid(row=2, column=0, columnspan=3, sticky="nsew")
        body.rowconfigure(2, weight=1)

        canvas = tk.Canvas(
            list_frame, height=min(320, 24 + 22 * len(listed)), highlightthickness=0
        )
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window_id, width=event.width),
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        list_frame.columnconfigure(0, weight=1)

        header = ttk.Frame(inner)
        header.grid(row=0, column=0, sticky="ew")
        for text, width in (
            ("导出", 6),
            ("编号", 16),
            ("尺寸 mm", 22),
            ("板厚", 16),
            ("折弯", 6),
            ("件数", 6),
        ):
            ttk.Label(header, text=text, width=width).pack(side=tk.LEFT, padx=(0, 4))

        for position, row in enumerate(listed, start=1):
            variable = tk.BooleanVar(value=row.default_checked)
            checked[row.label] = variable
            line = ttk.Frame(inner)
            line.grid(row=position, column=0, sticky="ew")
            ttk.Checkbutton(
                line, variable=variable, command=refresh_summary, width=4
            ).pack(side=tk.LEFT)
            for text, width in (
                (row.label, 16),
                (row.size_text, 22),
                (row.thickness_text, 16),
                (str(row.bend_count), 6),
                (str(max(row.quantity, 1)), 6),
            ):
                ttk.Label(line, text=text, width=width).pack(side=tk.LEFT, padx=(0, 4))

        def set_all(value: bool) -> None:
            for variable in checked.values():
                variable.set(value)
            refresh_summary()

        def keep_bent_only() -> None:
            bent = {row.label for row in listed if row.bend_count}
            for label, variable in checked.items():
                variable.set(label in bent)
            refresh_summary()

        ttk.Button(tools, text="全选", command=lambda: set_all(True)).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(tools, text="全不选", command=lambda: set_all(False)).pack(
            side=tk.RIGHT, padx=(6, 0)
        )
        ttk.Button(tools, text="只留带折弯的", command=keep_bent_only).pack(
            side=tk.RIGHT, padx=(6, 0)
        )

    next_row = 3 if listed else 1

    ttk.Label(body, text="输出目录").grid(row=next_row, column=0, sticky="w", pady=4)
    directory = tk.StringVar(value=initial_dir)
    directory_entry = ttk.Entry(body, textvariable=directory, width=42)
    directory_entry.grid(row=next_row, column=1, sticky="ew", padx=(8, 8), pady=4)

    def browse() -> None:
        chosen = filedialog.askdirectory(
            parent=dialog,
            title="选择导出目录",
            initialdir=directory.get().strip() or None,
        )
        if chosen:
            directory.set(chosen)

    ttk.Button(body, text="浏览…", command=browse).grid(row=next_row, column=2, pady=4)

    def add_number(row: int, caption: str, variable: tk.StringVar, unit: str) -> None:
        ttk.Label(body, text=caption).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(body, textvariable=variable, width=12).grid(
            row=row, column=1, sticky="w", padx=(8, 8), pady=4
        )
        ttk.Label(body, text=unit).grid(row=row, column=2, sticky="w", pady=4)

    thickness_var = tk.StringVar(value=thickness)
    radius_var = tk.StringVar(value=radius)
    angle_var = tk.StringVar(value=angle)
    add_number(next_row + 1, "默认板厚", thickness_var, "mm")
    add_number(next_row + 2, "折弯半径", radius_var, "mm")
    add_number(next_row + 3, "折弯角度", angle_var, "°")

    hint = ttk.Label(
        body,
        text="文件名按从上到下、从左到右编号，例如 01×2 2mm.SLDPRT；勾掉的件不占编号。",
        foreground="#555555",
        wraplength=440,
    )
    hint.grid(row=next_row + 4, column=0, columnspan=3, sticky="w", pady=(10, 0))
    refresh_summary()

    buttons = ttk.Frame(dialog, padding=(18, 8, 18, 16))
    buttons.grid(row=1, column=0, sticky="e")

    def close_with(value: ExportAllOptions | None) -> None:
        result["value"] = value
        dialog.grab_release()
        dialog.destroy()

    def confirm() -> None:
        folder = directory.get().strip()
        if not folder:
            messagebox.showwarning("缺少目录", "请填写输出目录。", parent=dialog)
            return
        try:
            options = ExportAllOptions(
                output_dir=Path(folder),
                thickness_mm=_parse_positive(thickness_var.get(), "默认板厚"),
                radius_mm=_parse_positive(radius_var.get(), "折弯半径"),
                angle_degrees=_parse_positive(angle_var.get(), "折弯角度", upper=180),
                selected_labels=tuple(
                    label for label, variable in checked.items() if variable.get()
                ),
                select_hidden=bool(hidden),
            )
        except ValueError as error:
            messagebox.showwarning("参数无效", str(error), parent=dialog)
            return
        if listed and not options.selected_labels:
            answer = messagebox.askyesno(
                "一件都没勾",
                "所有零件都被取消了，确定不导出任何件？",
                parent=dialog,
            )
            if not answer:
                return
        close_with(options)

    ttk.Button(buttons, text="取消", command=lambda: close_with(None)).pack(
        side=tk.RIGHT, padx=(8, 0)
    )
    start = ttk.Button(buttons, text="开始导出", command=confirm)
    start.pack(side=tk.RIGHT)

    dialog.protocol("WM_DELETE_WINDOW", lambda: close_with(None))
    dialog.bind("<Escape>", lambda _event: close_with(None))
    directory_entry.focus_set()
    directory_entry.selection_range(0, tk.END)
    dialog.update_idletasks()
    dialog.wait_window()
    return result["value"]
