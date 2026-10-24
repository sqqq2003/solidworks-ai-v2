# Issue #13 集成交接

启动（仓库根目录，Python 3.10+；此离线示例仅使用标准库）：

```
python work/project.py ql --action integrated --config examples/ql5050px_integrated.json --output-dir runtime/issue13-new
python work/check_issue13.py
```

退出码 3 表示计划生成但仍待映射/审核，1 表示失败，0 表示完成。每次使用新目录。桌面选择 ql5050px / integrated 并加载同一配置；批处理 job 使用 kind=ql5050px、action=integrated、config 与 output_dir 字段。桌面 GUI 本身未在云端点击验证。

入口复用 #12 的扫描、分类、候选映射、审批、决策和机械初算，以及 #10 的装配、传动、工程图/BOM 计划。target 是统一包络；manufacturing.envelope 如不同会被拒绝。manufacturing 包含原 #9 配置，无需重复实现规划器。未知 OEM 数据仍保留 pending。智能候选不会自动变成 OEM measurements 或装配/传动绑定；审核后须由工程师提供 manufacturing 的真实绑定、来源和配置。任意整机到原生操作的自动转换仍未验证，Windows 任务包是审核计划，不是可直接执行的通用脚本。

离线最小检查：端到端及校验和、已有目录拒绝、目标冲突拒绝、桌面/批处理共享命令，共 4 项通过；QL 模块及入口 compileall 通过。未进行全面回归、GUI 实测、原生 COM、运动/干涉或机械正确性验收。test-matrix.json 的 not_run 表示待 Gork 实机检查。

输出 integrated-result.json、oem-mapping-required.json、windows-tasks.json、bom.csv、test-matrix.json、HANDOFF.json 和 gork-integrated.zip。源码 commit 由 HANDOFF.json 记录；交付目录另附 source.zip 和 validation.json。示例为合成数据，不包含客户 CAD。

Gork 先完成旧 p248/GT-ZX，再统一接测：
1. 运行上述命令，核对 pending 与输出校验和；检查分类、歧义、采购件保护和单位。
2. 提供 QL-5050PX 真实只读快照，审核映射及决策；补齐参数、装配源路径/配置/基准/配合/变换、传动绑定/行程、材料/板厚和图纸模板。缺项清单见 oem-mapping-required.json。
3. 核对 windows-tasks.json 与原始证据，完成 #9/#11 矩阵。Windows 必须安装 SolidWorks、pywin32，使用已证明独占的会话和全新工作根目录，Pack and Go 隔离依赖；调用 docs/issue9-handoff.md 的 run_owned_native，不覆盖原件、不关闭未知会话。
4. 逐步检查只读扫描、装配/传动写入、重建读回、保存重开、配合/运动/干涉、SLDDRW/DXF/BOM，记录实机通过/失败/未测与证据。

回滚：离线仅删除新输出目录即可；原生失败仅丢弃独立工作副本。源码回到 HANDOFF.json 的版本或集成前 dev/cloud-ai 提交，不重写共享分支历史。合并前基线及两个 PR 的 SHA 记录在 delivery/issue13/validation.json。
