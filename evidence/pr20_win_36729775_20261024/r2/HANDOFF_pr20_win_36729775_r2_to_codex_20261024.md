# HANDOFF · PR#20 Windows 复测 r2（干净主机）@ 36729775 → Codex

- task_id: `pr20_win_36729775_20261024_145041`
- run: **r2**（operator 关掉全部 SLDWORKS 后重跑；**取代 r1**）
- pin: `367297751a9bc0add008c6b92a6e30a5c6d41ac9`
- PR: https://github.com/sqqq2003/solidworks-ai-v2/pull/20
- 时区：Asia/Shanghai · 2026-10-24 ~15:55
- 产品源码：**未改**

## 结论（诚实）
**仍 fail**；`native_acceptance=pending_windows_validation`。  
相对 r1：**owned-launch / write gate 3/3 PASS**（SessionOwnershipError 消失）、文档创建 3/3、清理 2/3、shaft 已出 `part.SLDPRT`。

| 配方 | modeling | cleanup |
|---|---|---|
| plate | FAIL `com_error -2147352571` 类型不匹配（feature_ir） | PASS owned_document_closed |
| bracket | 同上 | PASS |
| shaft | 建模+保存 OK（72391B），随后 COM 断连 | needs_review |
| two_bend_sheet | not_run（批停止） | — |

进程：spawn 后全部自退，批后 0 实例；零 ExitApp/taskkill。

## 分析线索
1. plate/bracket 类型不匹配 ≈ PR17 math SAFEARRAY 修复族（`8f4f57`）；本 pin 基于 `2ab51aa`，疑未含该修。
2. shaft 保存后 OBJNOTCONNECTED ≈ EXIT=139 teardown 家族。
3. 离线契约仍 7/8（`/secret` 路径过滤缺陷，r1 已记）。
4. `evidence_consistent=true` **不是** native pass。

## 建议上游
1. 将 PR17 SAFEARRAY 修复合入本线后重测 plate/bracket
2. 单独复现 shaft 保存后 COM 断连
3. 修 export source-path 过滤
4. cleanup 解除 review 后再跑 two_bend_sheet

## 本机路径
- out: `D:\工程\钣金导入\wb_pr20_wb_win_36729775_20261024_151500\`
- accept: `accept_pr20_wb_win_36729775_20261024_151500_r2.json`
- batch: `batch_r2/` · handoff: `handoff_r2/gork-acceptance.zip`
- RESULT_codex 已更新为 r2
