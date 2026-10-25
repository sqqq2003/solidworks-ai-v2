# BOM 明细表一键生成（#49 第一阶段 F3）

离线模块，纯 Python 标准库。输入装配体零件清单，输出明细表
文档（bom.json）+ CSV（Excel 可读）+ 可贴进工程图备注的
明细表文本。

## 调用

```bash
python -m bom.cli bom/examples/assembly_sample.json --out-dir out
python -m bom.cli bom/examples/assembly_sample.json --out-dir out \
    --dependency-report bom/examples/dependency_report_sample.json
```

退出码（与模块 ③④ 同款约定）：

* 0 = BOM 通过（无 pending）；
* 1 = 报告已写出，但 BOM 处于 pending；
* 2 = 输入错误（文件缺失、JSON 坏、零件号重复、依赖成环、
  数量非法）。

输入文件永不被修改；输出只写进 `--out-dir`（bom.json +
bom.csv + bom_table.txt）。CSV 写为 UTF-8-SIG，Excel 直接打开
不乱码。

## 输入格式（bom/1，普通 JSON）

* `assembly_name`：装配体名（非空字符串）。
* `parts`：非空列表，每项含 `id`（唯一）、`name`、`material`、
  `quantity`（> 0 的整数）；可选 `mass_kg`（>= 0 的数）、
  `depends_on`（零件号列表）。

## 规则

* 装配顺序 = `depends_on` 边的拓扑顺序（与 dependency_engine
  的 depends_on 词汇一致）；成环即输入错误。
* `depends_on` 指向 BOM 之外的号：该行保留，记一条
  unresolved_dependency pending，不丢件。
* 重量纪律：只有调用方给了 `mass_kg` 的行才算重量；缺失
  的行记 mass_pending，总重保持未知，**绝不按密度或目录
  编一个数**。
* 依赖交叉检查（可选）：传入 dependency_engine 预检报告时，
  按零件号比对；BOM 有而报告没有的号记
  not_in_dependency_graph pending；装配体名不一致记
  assembly_name_mismatch pending。报告可能只描述子系统，
  所以不一致只 pending，不报错。

## 未测清单（全部 pending_windows_validation）

* 实机装配体 BOM 读数（SolidWorks 明细表对照）；
* 采购件 / 外购件质量与价格字段（本批不做价格）。
