# HANDOFF · PR#20 Issue19 Windows 复测 @ 36729775 → Codex

- task_id: `pr20_win_36729775_20261024_145041`
- pin: `367297751a9bc0add008c6b92a6e30a5c6d41ac9`
- PR: https://github.com/sqqq2003/solidworks-ai-v2/pull/20
- 时区：Asia/Shanghai · 2026-10-24 ~15:40
- 产品源码：**未改**

## 结论（诚实）
**Windows 正式 native 验收未通过。** `native_acceptance=pending_windows_validation`。  
双源同因：单实例 SW 上 owned-launch `SessionOwnershipError`（spawn PID 对不上 COM），write gate 未绕过；四配方完整链 unverified。

| 源 | status | plate | 备注 |
|---|---|---|---|
| Qoder | blocked | SessionOwnershipError PID **21828** | pin 核对 OK；7/8 离线；export ZIP 有但勿当 pass |
| WorkBuddy (role=codex) | **fail** | SessionOwnershipError PID **21804** | 同；before PIDs 21772/20016/21828；spawn 留置不杀 |

## 离线
- 契约单测 **7/8**：`test_external_artifact_and_source_paths_removed` 失败 — `source_fingerprint` 未过滤外部路径 `/secret`（本 SHA 真实缺陷）
- review-parts 绑定 4 配方 OK（模板 `gb_part.prtdot`）

## export-acceptance
- 产出 `handoff/gork-acceptance.zip`（acceptance.json + SHA256.json）
- `evidence_consistent=true` **仅记录内部一致**（plate=needs_review 0 artifacts，3×not_run），**不是 native pass**

## git 本机
- HEAD rev-parse = pin ✓；worktree clean
- `git fetch` 曾报 pack 损坏 / 父提交 `2ab51aa` 本地缺失（按指令未强重拉，仅记录）

## 建议上游
1. **干净单实例**环境重试正式验收（关多余 SLDWORKS 后只留一台；仍只 CloseDoc、禁 ExitApp）
2. 修 export **source-path 过滤**（`/secret`）
3. 工作副本 **重克隆**解 pack 损坏
4. 勿把旧 `e1a14a7` offline-pass 或本轮 `evidence_consistent` 写成 native pass

## 本机路径
- WB out: `D:\工程\钣金导入\wb_pr20_wb_win_36729775_20261024_151500\`
- Qoder out: `D:\工程\钣金导入\wb_pr20_win_36729775_20261024_145041\`
- RESULT_codex / RESULT_qoder 在 `p0_wb_dispatch\`
