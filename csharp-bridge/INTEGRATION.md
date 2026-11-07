# 集成建议、风险清单与 Gork 验收矩阵（Issue #25）

> 集成原则：桥接只新增，不改动现有引擎文件；与 Codex 的 #24 滚筒改型零文件重叠；
> 与 PR #23 的 checkpoint/收尾机制衔接，不重复、不冲突。

## 1. 桥接如何接入现有 Python 引擎

`run_plan` 的 S1 / S2 / S5 三个阶段是桥接的接入点；S0（计划锁定）、S3（导出）、S4（验收落盘）保持现有逻辑不动。

```
run_plan (Python, 编排层)
  S0 计划锁定            [不变：plan 哈希、code_sha256、pending 检查]
  S1 生成               [桥接执行] Python 发 build 请求 -> C# 建原生特征
                         -> C# 回传 bend_count / auto_bent / part 路径
                         -> Python 写 ckpt-S1.json（PR #23 格式）
  S2 重开检查            [桥接执行] Python 发 reopen 请求 -> C# 重开读回
                         -> 读回 thickness / radius / k_factor / feature_types
                         -> Python 跑 validate_native，不一致即失败
  S3 导出               [不变：现有 export_flat；DXF 非空校验保留]
  S4 验收落盘            [不变：result.json 原子 rename]
  S5 收尾               [桥接执行] Python 发 teardown 请求 -> C# 按 5 步
                         收尾 -> 回传步骤记录 + 进程退出码
                         -> Python 并入 TeardownRecorder 报告
```

- **Linux CI 模式**：S1/S2/S5 走 Python mock（`MockSheetMetalPort` / `MockTransport`），只验证契约与流程，不产生任何"原生通过"结论。
- **Windows 实机模式**：S1/S2/S5 走 C# 桥接；Python 侧的 mock 代码在实机路径上**一行都不执行**，避免 mock 结果混入实机证据。
- **checkpoint 互通**：桥接输出的证据字段与 PR #23 的 `ckpt-<阶段>.json` 同形（plan_id、时间戳、产物路径 + SHA256、证据摘要），Python 侧直接收录，不做二次转换。
- **锁与 staging**：`RunLock` 与孤儿 staging 隔离仍归 `run_plan` 所有，桥接不碰 lock 目录、不碰 staging 目录、不删任何文件。
- **数组桥接分工**：数学数组编组继续走 PR #20 `sw_math_arrays.py` 的约定；本桥接只负责传输与执行，不另起一套编组规则。两者组合关系见 CONTRACT.md §6。

## 2. 风险清单

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | C# 侧 COM 线程模型错误（非 STA 调用） | 调用失败或随机崩溃 | 全部 COM 调用固定在单一 STA 线程；非 STA 调用直接拒绝 |
| R2 | 释放顺序错误重现 #19 崩溃 | 进程退出 AV，前功尽弃 | 5 步固定顺序 + 逆序释放 + GC 后才退出；先跑最小收尾复现再跑全流程 |
| R3 | 命名管道权限（目标 Windows 普通用户能否创建/连接） | 桥接无法启动 | 首批只跑单机同用户场景；权限问题实测后写进 CONTRACT 附录 |
| R4 | SW2022 vs SW2025 API 行为差异 | 桥接在一版本过、另一版本不过 | 验收注明实测版本；API 适配层隔离版本差异 |
| R5 | #17 与 #20 两套数组桥接关系未定性 | 重复建设或错误取代 | Gork 定性前，两套桥接都保留，本桥接不替任何一方表态（见 REVIEW.md §6.4） |
| R6 | PR #22 标题提示的 dual-source 复测失败 | #20 桥接可能有未暴露问题 | 正文未读：Gork 确认失败性质前，不许写 #20 桥接"已验证" |
| R7 | 超时后会话状态未知 | 误把半截产物当完成 | 超时即判会话不可信，必须重建会话后从 checkpoint 续跑 |
| R8 | 大装配消息体积 | 管道阻塞或截断 | 首批只跑单件钣金；大装配上限待实测后定 |
| R9 | 默认 K 值误用（`BendAllowanceSpec` 的 0.44） | 用通用值冒充某单制造依据 | 桥接客户端缺 K 即报错 pending；调用方必须显式传每单 K |
| R10 | 与 Codex #24 同文件写入冲突 | 互相覆盖 | 本批只写 `csharp-bridge/` 新目录，零改动现有文件 |

## 3. 给 Gork 的 Windows 验收测试矩阵（一次性）

> 验收口径：四项齐全才写"全流程稳定"，缺任何一项只能写"部分通过 + 待定项"。
> 每次验收必须记录：SW 版本、会话归属（独占 spawn / warm-reuse）、进程 PID、退出码。

| # | 测试 | 步骤 | 通过标准 | 证据 |
|---|---|---|---|---|
| A1 | 最小收尾复现 | C# 桥接 spawn → 零文档 → ExitApp → 退出，连跑 3 次 | 3 次退出码均为 0，无 AV | teardown 5 步日志 + 退出码 |
| A2 | p248 全流程 | Step0：4/4 折弯 + 重开读回（thickness/radius/k 与计划一致）+ DXF 非空 + 退出码 | 四项齐全；缺退出码只能写"折弯通过、收尾待定" | accept JSON（必须由 runner 正常写出，**不再事后重建**）+ 5 步日志 |
| A3 | oracle 验证 | PR #20 `sw_math_arrays.oracle` 在 SW2022 上跑用例 | max_dev ≤ 1e-10，且往返后进程能干净退出 | oracle 结果 JSON + 退出码 |
| A4 | 桥接往返 | C# 侧 echo：3 点数组与 16 变换数组往返 | 与输入精确一致（容差 1e-12） | 往返记录 |
| A5 | 死锁与续跑 | 人为留旧 lock + 孤儿 staging，跑新版 | 识别并归档旧 lock，续跑不丢已完成的 S1/S2 产物 | 归档记录 + 续跑 checkpoint 链 |
| A6 | 桥接定性 | 确认 #17 与 #20 两套桥接的关系；确认 PR #22 dual-source 失败的性质 | 在 PR 描述中明确写出取代/并存/分工结论 | 文字结论 + 链接 |
| A7 | 缺省保护 | 故意不传 K（或 t）调桥接 | 桥接返回 pending_confirmation，不用任何默认值顶替 | 错误响应记录 |
| A8 | 证据交付 | 全套验收跑完后 | accept JSON 由 runner 正常写出；SW 保持运行供复查时注明"SW left running"，不得写成已干净退出 | accept JSON + 日志 |

## 4. 未测清单（本批交付时全部未测，待 Windows）

- C# 代码编译（本机无 .NET SDK；Windows + .NET SDK 上编译待验）。
- C# 命名管道服务器的实际启动、连接与消息往返。
- RealSwApp 的全部内容（`SOLIDWORKS_INTEROP` 分支，含 PID 绑定、建空文档、ExitApp）。
- 桥接在 SW2022 与 SW2025 上的行为。
- 桥接与 `run_plan` 的真实接线（本批只给出了接线设计与 mock 客户端，未改 `run_plan` 代码——改 `run_plan` 属于下一批，需单独评审，避免与 #23 的合并冲突）。
- 以上全部标 pending_windows_validation。

---

<!-- 以下一节为 PR #27 的接线实施记录单，原 PR #27 因与本文件 add/add 冲突未直接合并，改由本合并分支原样重建；内容未改动，仅追加于此。 -->

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

---

# build/reopen 接线实施记录（Issue #25 batch 2）

> 本节记录桥接 build / reopen 方法接入 run_plan 的实施。契约见
> CONTRACT.md §12；Python 客户端见 python/bridge_client.py；
> C# 侧见 src/SwBridge.cs；接线适配器见 src/bridge_wiring.py。

## 接了哪两个方法（只接 S1/S2，不动 S0/S3/S4/S5）

- S1（生成）：bridge 供 bridge 时，`run_plan` 先调桥接 `build`
  方法（plan 参数 + staging part 路径 + 确定性幂等键）；方法成功
  时 `executed_via="bridge"`，生成结果即桥接返回（auto_bent /
  auto_bend_failed_count 检查与 port 路径相同）；方法失败、
  桥接不可用、或客户端尚不支持 build 时 `executed_via="port"`，
  回落到 `port.generate`，流程继续。桥接 build 成功必须已把零件
  写到 staging 路径，否则是硬失败（不是回落）。
- S2（重开检查）：bridge 供 bridge 时，`run_plan` 先调桥接
  `reopen` 方法（先 list_titles 验活）；方法成功时
  `executed_via="bridge"`，读回值（reopened / rebuilt /
  feature_types / editable / thickness / radius / k_factor）直接
  走 `validate_native` 与计划比对；失败时回落到
  `port.reopen_inspect`。读回值嵌在证据块的 `readback` 子字典
  里，顶层证据块仍不出现 thickness / radius / angle / k_factor
  键（读回是实测，不是接线捏造的参数）。
- 旧客户端兼容：不支持 build / reopen 的客户端（call 抛
  unknown method）仍走原有会话证明路径：S1 保留 grade + session
  pid，S2 保留 open_titles；只有执行本身回落到 port。旧接线测试
  （tests/test_bridge_wiring.py）不改动，继续全过。
- 锁、staging、checkpoint 所有权仍归 run_plan；桥接不碰 lock
  目录、不碰 staging 目录（除 build 写入给定的 part 路径外）、
  不删任何文件。#30 的守卫（接管拒绝、退出值原样记录、检查点
  路径边界校验）原样保留，新方法不绕过。

## 回落规则（在 #31 规则上扩展）

| 情况 | 处理 | crash 包 |
|---|---|---|
| 无 bridge 参数 | 行为与接线前完全一致，不写 bridge 块 | 无 |
| probe / spawn 失败 | 全部阶段 fallback，grade mock + fallback_reason | 无 |
| build / reopen 方法失败（含超时、老客户端不支持） | 当阶段 fallback 到 port，`executed_via="port"` + fallback_reason，流程继续 | 无（port 回落即恢复手段） |
| 桥接 build 成功但零件文件缺失 | 硬失败，run 失败（不是回落） | 按 run_plan 通用失败路径 |
| 桥接 reopen 读回与计划不一致 | `validate_native` 抛错，run 失败（与 port 路径相同） | 按 run_plan 通用失败路径 |
| S5 teardown 失败（已有会话） | 记失败证据 + crash 包，产物不反发布（#31 纪律不变） | 有 |
| 桥接返回非零退出码（S5） | 原样记录 exit_code，ok=false，不改写成 0 | 无 |

## 证据等级与证据块形状

- `executed_via="bridge"` 仅当桥接方法调用成功；grade 规则不变：
  channel == "bridge" 且调用成功才是 grade "bridge"，mock 通道
  即使调用成功也只能是 grade "mock"。
- S1 桥接块：`{grade, channel, stage: "S1", available, session,
  executed_via: "bridge", result: {title, owned, bend_count,
  auto_bent, auto_bend_failed_count, part}}`。
- S2 桥接块：`{grade, channel, stage: "S2", available, session,
  open_titles（回落路径保留）, executed_via: "bridge",
  readback: {reopened, rebuilt, feature_types, editable,
  bend_feature_count, completed_bend_count, thickness_mm, radius_mm,
  k_factor}}`。
- `validate_bridge_evidence` 已扩展：executed_via 非法、
  port 执行缺 fallback_reason、bridge 执行缺 result / readback
  均判 ValueError；顶层禁键检查不变。

## 未接什么（下一批 / 待实机）

- 完整几何 IR 传输：build 目前只用 plan_id 引用已验证计划，
  轮廓 / 孔 / 折弯线几何的传输方式未定稿；RealSwApp build
  在此定稿前不得宣称完成（见 CONTRACT.md §12.1）。
- C# 编译、命名管道实测、RealSwApp、SW2022/SW2025 行为：
  全部 pending_windows_validation（见 PR #26 未测清单）。
- S3 导出仍走 port；S5 收尾纪律不变。

## 测试（mock，Linux 可跑）

tests/test_bridge_build_reopen.py，见 PR 描述。另回归：
tests/test_bridge_wiring.py（8 项，老客户端兼容）、
csharp-bridge/tests/test_bridge_contract.py（17 项）、
pipeline / bend_allowance / no-default-k / p0_gork /
issue19 checkpoint-teardown 等回归合计见 PR 描述。

## 给 Gork 的验收矩阵增补（build / reopen）

| # | 测试 | 步骤 | 通过标准 | 证据 |
|---|---|---|---|---|
| B6 | build 冒烟 | 桥接 build 跑 p248 计划（单件钣金） | 零件落盘到 staging 路径、bend_count 与计划一致、auto_bent 真 | ckpt-S1（含 executed_via="bridge" 的 bridge 块）+ 零件文件 |
| B7 | reopen 读回 | 桥接 reopen 刚建的零件 | thickness / radius / k 与计划一致（容差 1e-6）、feature_types 含 SheetMetal / FlatPattern / SMBaseFlange、editable 真 | ckpt-S2（含 readback 的 bridge 块） |
| B8 | 读回不一致拒绝 | 改计划参数后重跑 reopen（不重建） | validate_native 失败、run 不通过 | 失败报告 |
| B9 | 幂等重放 | 同一 plan_id + 同一幂等键连调两次 build | 第二次不重复建模、返回首次结果 | 两次调用记录 |
| B10 | 方法失败回落 | 停掉桥接服务后跑全流程 | S1/S2 回落到 port、流程继续、证据块 executed_via="port" + fallback_reason、无 crash 包 | ckpt-S1/S2 + 无 crash 包 |
