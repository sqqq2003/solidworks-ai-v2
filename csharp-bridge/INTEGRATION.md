# 接线实施记录：csharp-bridge 接入 run_plan（Issue #25，下一批）

> 合并注意（stacked 分支文件）：本分支以 PR #23 的分支
> feat/issue19-ckpt-teardown 为基线，该基线尚无 csharp-bridge/ 树。
> 本文件是接线记录单，与 PR #26 的 csharp-bridge/INTEGRATION.md（契约、
> 集成设计、验收矩阵）是互补关系，不是替代关系。两 PR 合并时请将本节
> 并入 #26 的 INTEGRATION.md（直接粘贴），不要用任一版本覆盖另一版本。

## 接了哪几个点（只接 S1/S2/S5，不动 S0/S3/S4）

- S1（生成）：桥接契约目前没有 build 方法，所以生成本身仍走 port；接线
  只记录桥接会话证明（spawn 的 pid/owned）+ grade，写进 ckpt-S1
  evidence.bridge。桥接失败 → fallback 证据，绝不中断原有流程。
- S2（重开检查）：复用 S1 会话，list_titles 验活；重开检查本身仍走
  port；会话丢失 → fallback 证据。证据写进 ckpt-S2 evidence.bridge。
- S5（收尾）：桥接 5 步 teardown 报告（steps + exit_code）写进 ckpt-S5
  evidence.bridge；退出码原样记录，0 与非零都不改写。桥接 teardown
  失败不反发布已落盘产物：失败记进 ckpt-S5 + 一个 crash 包，验收方
  必须先看 ckpt-S5 再谈"全流程稳定"。桥接单纯不可用（probe 失败、
  本 run 未建会话）是 fallback，不写 crash 包。
- 锁与 staging 所有权仍归 run_plan：桥接不碰 lock 目录、不碰 staging
  目录、不删任何文件。checkpoint 语义沿用 PR #23（原子写、链校验、
  指纹变化全部作废重跑），只在 evidence 里加 bridge 块；code_hash
  新增 bridge_wiring.py 一项（旧 plan 按"modified or stale plan"纪律
  自然失效重建）。

## 回落规则

| 情况 | 处理 | crash 包 |
|---|---|---|
| 无 bridge 参数 | 行为与接线前完全一致，不写 bridge 块 | 无 |
| probe 失败（hello 不通） | 全部阶段 fallback，grade mock + fallback_reason | 无 |
| spawn / list_titles 失败 | 当阶段 fallback，流程继续 | 无 |
| teardown 调用失败（已有会话） | S5 记失败证据 + crash 包，产物不反发布 | 有 |
| 桥接返回非零退出码 | 原样记录 exit_code，ok=false，不改写成 0 | 无（非零退出码本身不是调用失败）|

## 证据等级

- grade "bridge" 仅当 channel == "bridge" 且调用成功；mock 通道
  （MockTransport / 测试 fake）即使调用成功也只能是 grade "mock"。
- bridge 证据绝不升级运行结论：simulated run 仍是 simulated，
  sw_live_verified 不变；"bridge 回答了" ≠ "原生 SolidWorks 跑了"。
- 接线不产生、不传递任何每单参数：evidence 里不出现 thickness_mm /
  radius_mm / angle_degrees / k_factor；缺输入仍由 build_plan 标
  pending_confirmation，t=2.5/K=0.36 只是本厂一次实测用例，不是默认值。

## 未接什么（下一批 / 待实机）

- 桥接 build / reopen 方法：契约里尚无此方法，生成与重开检查本身仍
  走 port；未来加方法时再扩展 S1/S2 证据块，不 reinterpret 现有块。
- owned_titles：本批 S5 teardown 传空元组（port 的文档标题不在接线
  视野内）；未来 port 本身走桥接执行时再传真实 owned titles。
- C# 编译、命名管道实测、RealSwApp、SW2022/SW2025 行为：全部
  pending_windows_validation（见 PR #26 未测清单）。
- 与 #26 的 INTEGRATION.md 合并 chore：见文件头合并注意。

## 测试（mock，Linux 可跑）

tests/test_bridge_wiring.py，8 项：桥接可用时 S1/S2/S5 证据记录、
非零退出码原样记录、桥接不可用回落且无 crash 包、超时回落、
teardown 失败保产物 + crash 包、证据形状与无默认参数、续跑保留
桥接证据、无 bridge 时行为与旧版一致。另回归：#23 的 14 项
checkpoint/teardown 测试 + 现有 pipeline 测试 14 项，合计 36 项全过。
