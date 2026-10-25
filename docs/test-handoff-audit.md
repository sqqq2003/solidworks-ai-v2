# 多版本交测结果核对

复用现有分支测试任务及各自证据导出器，新增只读汇总入口，不执行 COM、不合并功能分支、不替代模型测量验收。

```powershell
python work/audit_test_handoff.py examples/gork46-audit-matrix.json submission.json --evidence-root 'D:\工程\钣金导入\回传证据' > audit.json
```

Python API: `audit_handoff(matrix, submission, evidence_root)`，位于 src/test_handoff_audit.py。
不依赖第三方库，Windows PowerShell BOM JSON 可读。退出码 passed=0、failed=1、degraded=2、review_required=3。

矩阵以完整40位SHA区分测试组；例子是 #46 的首批检查点，不能代替其详细矩阵。整机制造链等后续检查应显式加入矩阵，不因例子覆盖完成就宣布项目验收。

各 runner 原始 schema 不同，调用者需显式整理 submission.json；不猜字段、不把旧记录自动改成新SHA。每条记录格式：

```json
{"schema_version":1,"results":[{
 "lane":"native-patch","id":"sheet-S1-S2-flat",
 "sha":"9229517de6511218fca6ada050872d6f4cef72ea",
 "status":"review_required","scope":"native",
 "environment":{"platform":"Windows","solidworks_version":"2025 SP1.2"},
 "process_exit_code":null,
 "artifacts":[{"path":"native/report.json","sha256":"<实际文件SHA256>"}]
}]}
```

文件必须在 evidence-root 内，使用相对 POSIX 路径；拒绝越界、指向外部的符号链接、Windows绝对路径。大文件流式哈希。只读取文件，不打包 CAD。可用文件副本构建本机证据目录；上传范围由操作者决定，工具不自动上传。

缺项、重复、错版本、离线填原生项、缺环境、未知退出、缺证据均需复核；非零退出、明确失败或文件哈希不符为失败。已声明 degraded 保留，不提升通过。意外记录不会被静默忽略。

**汇总 passed 仅表示申报覆盖和文件完整性一致。** 即使 runner 声称通过，仍须独立复核尺寸、特征树、配合、展开、原件未改及制造要求。输出始终 manufacturing_approved=false、native_acceptance=requires_independent_review。无法检测伪造的环境或日志；哈希不证明日志真实。

本批只执行12项针对性离线单测（全部通过），没有全面回归或实机测试。空回传示例应输出全部 review_required，用于确认缺测不会变绿。#47 保持原 pin，本工具可独立使用，不要求 Gork 切换正在运行的原生任务。
