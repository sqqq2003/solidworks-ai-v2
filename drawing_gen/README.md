# 工程图自动生成 · 云端部分（#49 第一阶段 F1）

离线模块，纯 Python 标准库。只做图纸**模板文档**：幅面、比例、三视图
布局、标题栏、尺寸规则，外加一份 mock 渲染（drawing JSON）。
**不生成真正的 SolidWorks 工程图**——那一步必须在用户 Windows 本机
独占会话里做，归 Gork，见下文验收清单。

## 调用

```bash
python -m drawing_gen.cli drawing_gen/examples/drawing_sample.json --out-dir out
```

退出码（与模块 ③④ 同款约定）：

* 0 = 模板通过（无 pending）；
* 1 = 报告已写出，但模板处于 pending；
* 2 = 输入错误（文件缺失、JSON 坏、形状不对、幅面/比例非法）。

输入文件永不被修改；输出只写进 `--out-dir`（drawing.json）。

## 输入格式（drawing-gen 输入，普通 JSON）

* `part_name`：零件名（字符串）。
* `bounding_box_mm`：`{length, width, height}`，必须全是 > 0 的数。
* `sheet_size`：`A4`（297×210）或 `A3`（420×297），横放，单位 mm。
* `scale`：`"1:2"`、`"1:1"`、`"2:1"` 这类字符串。
* `title_block`：8 个字段全必填——drawing_no、part_name、material、
  scale、sheet_size、designer、date、revision；缺失即 pending。
  其中 scale、sheet_size 必须与顶层一致，否则 pending。
* `dimensions`：`[{name, value_mm, source}]`；值缺失或来源缺失
  即该条 pending，不编数。

## 布局规则

* 四边留白 20 mm；正视图左下，俯视图在上（间隔 10 mm），
  侧视图在右（间隔 10 mm）。
* 排不下即 pending，**绝不自动改比例**——比例是显式输入，
  改了就是编造。

## 未测清单（全部 pending_windows_validation）

* 真实 SolidWorks 出图（视图生成、标题栏渲染、打印）；
* SW2022 / SW2025 行为差异。

## 给 Gork 的实机验收清单

1. 标题栏 8 个字段在实机图纸上完整渲染，无缺失错位；
2. 三视图位置与本模块布局规则一致（留白、间隔、比例）；
3. 尺寸齐全且数值与输入一致，无多标、无漏标；
4. 幅面与打印设置与 sheet_size 一致。
