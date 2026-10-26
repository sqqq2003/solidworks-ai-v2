"""未来 Windows 实机测试包：一张收拢各批验收矩阵的总表。

来源口径（不另造一套对不上的号）：
- A1–A8：csharp-bridge/INTEGRATION.md（#26）。
- B1–B5：PR #27 描述（#31 替代合并后仍以此为准）。
- B6–B10：PR #32 描述。
- D1–D5：模块 ③ dxf_extract/README.md 的 Gork 增补。
- C1–C5：模块 ④ feature_tree/README.md 的 Gork 增补。
- G1–G4：模块 ⑤ dependency_engine/README.md 的 Gork 增补。
- W1–W10：#23 / #29 / #30 各批的实机项与桥接编译项（A2 已覆盖
  p248 全流程时，W2 只引用 A2，不重复执行）。

每项字段：id、group、title、steps、precondition、pass_bar、
evidence、rollback。所有项均为 pending_windows_validation；
“全流程稳定”四项齐全才写，缺任何一项只能写“部分通过 + 待定项”。
"""

PACK_TITLE = "Gork 一次性实机验收包（Issue #25 扩展模块 ⑥统一版）"

PACK_PRINCIPLES = [
    "合并 ≠ 验证通过：本包所有项均为 pending_windows_validation，"
    "离线 mock/回归通过绝不写成实机通过。",
    "“全流程稳定”四项齐全才写（p248 全流程的折弯、读回、DXF、"
    "退出码），缺任何一项只能写“部分通过 + 待定项”。",
    "每次验收必须记录：SW 版本、会话归属（独占 spawn / warm-reuse）、"
    "进程 PID、退出码。",
    "accept JSON 必须由 runner 正常写出，事后重建的 accept 须注明"
    "证据等级，不得冒充正常写出。",
    "回滚总原则：本包的离线部分只读被测代码、只写 out-dir，删 "
    "out-dir 即回滚；实机端只写 run 的 staging 工作副本路径，"
    "绝不写客户原件；删 staging 副本即回滚实机产物。",
]

# (id, group, title, steps, precondition, pass_bar, evidence, rollback)
ITEMS = [
    # ---- A：桥接（#26）----
    ("A1", "桥接", "最小收尾复现",
     "C# 桥接 spawn → 零文档 → ExitApp → 退出，连跑 3 次",
     "Windows + .NET SDK；桥接服务可启动",
     "3 次退出码均为 0，无 AV",
     "teardown 5 步日志 + 退出码",
     "删 staging 副本；不碰客户原件"),
    ("A2", "桥接", "p248 全流程",
     "Step0：4/4 折弯 + 重开读回（thickness/radius/k 与计划一致）+ DXF 非空 + 退出码",
     "p248 计划已确认；独占会话",
     "四项齐全；缺退出码只能写“折弯通过、收尾待定”",
     "accept JSON（必须由 runner 正常写出，不再事后重建）+ 5 步日志",
     "删 staging 副本；不碰客户原件"),
    ("A3", "桥接", "oracle 验证",
     "PR #20 sw_math_arrays.oracle 在 SW2022 上跑用例",
     "SW2022；oracle 用例齐全",
     "max_dev ≤ 1e-10，且往返后进程能干净退出",
     "oracle 结果 JSON + 退出码",
     "删用例输出；不碰客户原件"),
    ("A4", "桥接", "桥接往返",
     "C# 侧 echo：3 点数组与 16 变换数组往返",
     "桥接服务可启动",
     "与输入精确一致（容差 1e-12）",
     "往返记录",
     "无产物，无需回滚"),
    ("A5", "桥接", "死锁与续跑",
     "人为留旧 lock + 孤儿 staging，跑新版",
     "旧 lock 与孤儿 staging 已人为留置",
     "识别并归档旧 lock，续跑不丢已完成的 S1/S2 产物",
     "归档记录 + 续跑 checkpoint 链",
     "恢复归档前的 lock 快照（如有）"),
    ("A6", "桥接", "桥接定性",
     "确认 #17 与 #20 两套桥接的关系；确认 PR #22 dual-source 失败的性质",
     "PR #17/#20/#22 正文可读",
     "在 PR 描述中明确写出取代/并存/分工结论",
     "文字结论 + 链接",
     "文字结论可修订，无代码回滚"),
    ("A7", "桥接", "缺省保护",
     "故意不传 K（或 t）调桥接",
     "桥接服务可启动",
     "桥接返回 pending_confirmation，不用任何默认值顶替",
     "错误响应记录",
     "无产物，无需回滚"),
    ("A8", "桥接", "证据交付",
     "全套验收跑完后检查证据完整性",
     "A1–A7 已跑",
     "accept JSON 由 runner 正常写出；SW 保持运行供复查时注明“SW left running”，不得写成已干净退出",
     "accept JSON + 日志",
     "删 staging 副本；不碰客户原件"),
    # ---- B：接线与 build/reopen（#27/#31、#32）----
    ("B1", "接线", "桥接接线冒烟",
     "Windows 上跑 run_plan + 真实桥接，检查 ckpt-S1/S2/S5 均含 bridge 块",
     "真实桥接可用；run_plan 可跑",
     "grade 为 bridge，S5 exit_code 与进程实际退出码一致",
     "ckpt-S1/S2/S5",
     "删 staging 副本"),
    ("B2", "接线", "回落",
     "故意停掉桥接服务跑 run_plan",
     "桥接服务可停",
     "流程正常完成，全部 bridge 块为 grade mock + fallback_reason，且无 crash 包",
     "ckpt-S1/S2/S5 + 无 crash 包",
     "删 staging 副本"),
    ("B3", "接线", "teardown 失败",
     "人为让 teardown 失败一次",
     "可注入 teardown 失败",
     "产物仍在、ckpt-S5 记失败、crash 包已写，且结果不被说成“全流程稳定”",
     "ckpt-S5 + crash 包",
     "删 staging 副本与 crash 包"),
    ("B4", "接线", "退出码",
     "人为制造一次非零退出",
     "可注入非零退出",
     "ckpt-S5 原样记录该退出码、ok=false",
     "ckpt-S5",
     "删 staging 副本"),
    ("B5", "接线", "合并顺序（已执行，备查）",
     "核对 #23 → #26 → #31 → #29 → #30 的合并顺序与 INTEGRATION.md 合并版",
     "各 PR merge commit 可查",
     "顺序与 merge commit 一致，INTEGRATION.md 两节均保留",
     "merge commit 清单",
     "已合并项不回滚；备查即可"),
    ("B6", "build/reopen", "build 冒烟",
     "桥接 build 跑一个 p248 计划（单件钣金）",
     "桥接 build 可用；p248 计划已确认",
     "零件落在 staging 路径，bend_count 与计划一致，auto_bent 为 true",
     "ckpt-S1（bridge 块 executed_via=bridge）+ 零件文件",
     "删 staging 零件"),
    ("B7", "build/reopen", "reopen 读回",
     "对刚 build 的零件跑桥接 reopen",
     "B6 已产出零件",
     "thickness / radius / k 与计划一致（容差 1e-6），feature_types 含 SheetMetal / FlatPattern / SMBaseFlange，editable 为 true",
     "ckpt-S2（bridge 块含 readback）",
     "删 staging 零件"),
    ("B8", "build/reopen", "读回不一致拒绝",
     "改计划参数后不重建、重跑 reopen",
     "可改计划参数",
     "validate_native 失败，run 不通过",
     "失败报告",
     "恢复原计划参数"),
    ("B9", "build/reopen", "幂等重放",
     "同一 plan_id + 同一幂等键，build 两次",
     "桥接 build 可用",
     "第二次不重建模，返回第一次结果",
     "两次调用记录",
     "删 staging 零件"),
    ("B10", "build/reopen", "方法失败回落",
     "停掉桥接服务，跑全流程",
     "桥接服务可停",
     "S1/S2 回落到 port，流程继续，证据块 executed_via=port + fallback_reason，无 crash 包",
     "ckpt-S1/S2 + 无 crash 包",
     "删 staging 副本"),
    # ---- D：模块 ③ DXF ----
    ("D1", "DXF ③", "提取对照",
     "取同一张 DXF，先用模块 ③ 出 geometry.json，再用 SolidWorks 打开同一文件读实体清单",
     "同一张 DXF；SolidWorks 可读 DXF",
     "逐项对照实体数量、类型、圆心/半径、轮廓点，差值 ≤ 1e-3 mm",
     "对照记录",
     "删 out-dir"),
    ("D2", "DXF ③", "孔对照",
     "plan.json 里的每个 hole，与 SolidWorks 重建后的孔位置/直径对照",
     "D1 已通过；重建可用",
     "圆心偏差 ≤ 1e-3 mm",
     "对照记录",
     "删 out-dir 与重建产物"),
    ("D3", "DXF ③", "折弯线对照",
     "plan.json 里的 bend_line_candidate，与 SolidWorks 展开图上的折弯线位置对照",
     "D1 已通过；展开图可用",
     "多一条、少一条都算不一致，须查层名规则还是直线判定规则",
     "对照记录",
     "删 out-dir 与展开产物"),
    ("D4", "DXF ③", "标注对照",
     "plan.json 里的 dimension_check 与 SolidWorks 标注读数对照",
     "D1 已通过",
     "读数一致；text_override_mismatch_pending 的项须人工定",
     "对照记录 + 人工定论",
     "删 out-dir"),
    ("D5", "DXF ③", "回滚",
     "验收失败时删除 out-dir",
     "出过 out-dir",
     "CAD 原件与工作副本未动，仓库与 SolidWorks 状态未动",
     "删除记录",
     "无"),
    # ---- C：模块 ④ 特征树 ----
    ("C1", "特征树 ④", "执行对照",
     "同一棵特征树，先用 mock 出执行记录，再用实机后端执行",
     "特征树已确认；实机后端可用",
     "逐项对照步骤顺序、特征类型、孔位/直径、折弯 BA/BD，差值 ≤ 1e-6",
     "执行记录对照",
     "删 out-dir 与 staging 产物"),
    ("C2", "特征树 ④", "读回对照",
     "实机 reopen 后读回特征树、钣金定义、CustomBendAllowance，与计划参数比对",
     "C1 已通过",
     "容差 1e-6，不一致即失败",
     "读回对照记录",
     "删 out-dir 与 staging 产物"),
    ("C3", "特征树 ④", "成环 / 缺依赖拒绝",
     "在实机端提交成环或缺依赖的树",
     "可构造环/缺依赖树",
     "实机端同样拒绝执行，不许“猜顺序”把环跑通",
     "拒绝记录",
     "无产物"),
    ("C4", "特征树 ④", "失败隔离",
     "执行中途失败一次",
     "可注入中途失败",
     "后续特征无产物、无文档写入；收尾仍按 #23/#31 纪律（失败记证据 + crash 包、产物不反发布、退出码原样记录）",
     "ckpt + crash 包",
     "删 staging 产物与 crash 包"),
    ("C5", "特征树 ④", "回滚",
     "mock 产物只写 out-dir，实机端只写 staging 工作副本路径",
     "出过产物",
     "删 out-dir 即清 mock 产物；删 staging 副本即清实机产物；客户原件未动",
     "删除记录",
     "无"),
    # ---- G：模块 ⑤ 依赖引擎 ----
    ("G1", "依赖引擎 ⑤", "门禁对照",
     "取一台已知的整机参数表，先用模块 ⑤ 出预检报告，再与 SolidWorks 装配体的实际配合状态逐项对照",
     "已知整机参数表；装配体可读",
     "本模块报 contradiction 的对子在实机上也应是过约束或干涉，报 under_constrained 的零件在实机上也应是可拖动的",
     "对照记录",
     "删 out-dir"),
    ("G2", "依赖引擎 ⑤", "改宽联动对照",
     "按 ok 示例改整机宽度，实机上核对横梁 / 辊筒 / 导向杆间距 / 防护罩的联动清单",
     "ok 示例参数表；装配体可改",
     "联动清单与报告的 impact 一致，少一项、多一项都算不一致",
     "对照记录",
     "恢复原参数"),
    ("G3", "依赖引擎 ⑤", "pending 门禁",
     "用一份 status 非 ok 的报告调 build",
     "可构造 pending/conflict 报告",
     "调用方先补齐 pending 项或处理 conflict，实机端同样拒绝执行",
     "拒绝记录",
     "无产物"),
    ("G4", "依赖引擎 ⑤", "回滚",
     "本模块是纯静态检查，不写 CAD、不改仓库现有文件",
     "出过预检报告",
     "删 out-dir 即清干净；仓库与 SolidWorks 状态未动",
     "删除记录",
     "无"),
    # ---- W：#23/#29/#30 与桥接编译 ----
    ("W1", "收尾 #23/#30", "checkpoint 与收尾实机",
     "S0–S5 checkpoint 与收尾在真实 SolidWorks 上跑；最小收尾复现 ×3",
     "真实 SolidWorks；独占会话",
     "3 次收尾退出码均为 0，无 AV；checkpoint 链完整",
     "ckpt-S0–S5 + 5 步日志 + 退出码",
     "删 staging 副本"),
    ("W2", "收尾 #23/#30", "p248 全流程（引用 A2）",
     "与 A2 同项，此处不重复执行，只引用结论",
     "A2 已跑",
     "与 A2 通过标准一致",
     "A2 的 accept JSON",
     "同 A2"),
    ("W3", "收尾 #23/#30", "死锁续跑（#30 纪律）",
     "留一个旧 lock，跑新版；分别试“已确认死亡”与“活/无法探测”两种旧所有者",
     "可留旧 lock",
     "仅确认死亡才自愈恢复；活或无法探测一律拒绝接管（须人工检查，不自动偷锁）",
     "续跑记录 + 归档记录",
     "恢复 lock 快照（如有）"),
    ("W4", "收尾 #23/#30", "accept JSON 正常写出",
     "跑一次全流程，检查 accept JSON 的产生方式",
     "全流程可跑",
     "accept JSON 由 runner 正常写出；事后重建的须注明证据等级",
     "accept JSON + 生成日志",
     "删 staging 副本"),
    ("W5", "去默认值 #29", "CustomBendAllowance 写入与读回",
     "在实机上写 CustomBendAllowance 并重开读回",
     "真实 SolidWorks；钣金件可用",
     "写入值与读回值一致；缺 K 时调用方报错 pending，不用默认值顶替",
     "写入/读回记录",
     "删 staging 零件"),
    ("W6", "去默认值 #29", "工作台空字段弹窗流程",
     "在 Windows 工作台上空字段提交一次",
     "Windows 工作台可跑",
     "弹窗报错，不用旧数生成",
     "弹窗记录",
     "无产物"),
    ("W7", "守卫 #30", "三项守卫实机行为",
     "实机上分别触发：活锁接管拒绝、非零退出值记录、非法检查点路径",
     "真实 SolidWorks；可注入三类情形",
     "接管被拒绝且不杀进程；退出值原样记录不记 OK；非法路径被拒绝且无法续跑",
     "三项记录",
     "删 staging 副本"),
    ("W8", "桥接编译", "C# 编译与命名管道实测",
     "Windows + .NET SDK 上编译 SwBridge，启动命名管道服务器并往返",
     "Windows + .NET SDK",
     "编译通过；管道启动/连接/消息往返正常；RealSwApp 行为与 mock 形状一致",
     "编译日志 + 往返记录",
     "停管道服务"),
    ("W9", "双版本", "SW2022 / SW2025 行为",
     "同一验收项在 SW2022 与 SW2025 上各跑一次",
     "两个版本均可用",
     "两版本结论分别记录；一版本过、另一版本不过时不得写成“已通过”，须注明版本差异",
     "双版本记录",
     "删各版本 staging 副本"),
    ("W10", "复审", "生成器全文逐行审计与 0.44 残留统一",
     "逐行审计 src/solidworks_generator.py；处理头部 DEFAULT_BEND_K_FACTOR = 0.44 残留",
     "生成器全文可读",
     "审计结论写入文档；残留常量或被删除、或被证明无调用方且标注废止，不得继续作默认值使用",
     "审计记录 + 统一 PR",
     "文档修订可回退"),
]


def render_windows_pack():
    """渲染统一 Windows 实机测试包 Markdown。"""
    lines = []
    lines.append("# %s" % PACK_TITLE)
    lines.append("")
    lines.append("> 来源：A1–A8（#26）、B1–B5（#27/#31）、B6–B10（#32）、"
                 "D1–D5（模块 ③）、C1–C5（模块 ④）、G1–G4（模块 ⑤）、"
                 "W1–W10（#23/#29/#30 与桥接编译）。")
    lines.append("")
    lines.append("## 总原则")
    lines.append("")
    for principle in PACK_PRINCIPLES:
        lines.append("- %s" % principle)
    lines.append("")
    lines.append("## 总表（%d 项，全部 pending_windows_validation）" % len(ITEMS))
    lines.append("")
    lines.append("| 编号 | 组 | 验收项 | 步骤 | 前置条件 | 通过标准 | 证据产物 | 回滚方案 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for item in ITEMS:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % item)
    lines.append("")
    lines.append("## 待确认（不在本表执行项内，标待确认）")
    lines.append("")
    lines.append("- #17 与 #20 两套数组桥接的取代/并存关系（见 A6）。")
    lines.append("- PR #22 dual-source 复测失败的性质（见 A6）。")
    lines.append("- 材料 K 工艺表（缺制造工艺依据，标待确认）。")
    lines.append("- 桥接 build 的完整几何 IR 传输设计（#32 §12.1 未定稿项）。")
    lines.append("- 生成器全文逐行审计结论（见 W10）。")
    lines.append("")
    return "\n".join(lines)
