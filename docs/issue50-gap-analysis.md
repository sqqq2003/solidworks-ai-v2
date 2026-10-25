# Issue50 复用与缺口分析

开发基线：dev/cloud-ai aca899b2d7daf2d0b9a2edabda48a56a477b1711。
复用快照：PR45 758b1e533a11958784508736f3c05fc83abe0295。独立候选保留其文件，新增 engineering_intelligence；不移动PR45或其他原生测试分支。不覆盖用户原程序，不执行COM。

| 优先级/需求 | 开发前状态 | 已有代码与复用方式 | 本批新增/边界 |
|---|---|---|---|
| P0 尺寸链 | partial | ql5050px依赖计划、PR28滚筒保护设计、PR45意图审核 | 显式mm/基准/方向DAG、单叶反解、冲突/循环/缺参、前后差异；不是通用几何约束求解器 |
| P0 配合诊断 | partial | ql5050px.assembly.inspect_assembly | 包装原预检，新增运动副行程、重复配合候选、原生证据绑定；标量DOF不宣称求解器秩 |
| P0 变更追踪 | partial | PR45 design_review.impact及review_digest | 新增跨零件/装配/图纸/BOM/采购项的依赖图、删除引用和重生成次序 |
| P0 公差 | missing | 已有尺寸与单位契约 | 有符号极值法、非对称制造公差、轴孔和轴向间隙；不补公差等级或做RSS |
| P0 工程审查 | partial | PR45 rules.evaluate_rules、design_review | 增加规则适用范围/置信度/输入来源，复用原比较引擎；建议只读 |
| P1 传动 | partial | mechanical_selection.calculate、PR45 catalogue.select_parts | 复用电机/线速公式与目录筛选，联查转速/速比/效率/安全系数；无动力方案不套电机公式 |
| P1 焊接机架 | missing | 现有原生host归属协议 | 直杆切割/材料质量/余料/接头/结构构件计划；不执行焊接件COM，不计算焊缝强度 |
| P1 成本采购 | missing | 已有BOM/标准件来源契约 | 三类费用、损耗、日期/币种/单价单位；缺报价不合计为完整总价 |
| P1 重复件 | partial | 扫描快照和版本/哈希工具 | 声明几何/特征/材料/接口及文件哈希候选，输出差异；不替换模型 |
| P1 自动报告 | partial | PR45审核摘要/版本/证据；PR48文件核验契约 | 基线/提案摘要、参数差异、影响图、声明证据、验证状态和新目录回退计划 |
| P2 方案比较 | missing | 既有计算结果作为输入 | 无动力/链/带的显式指标与权重比较；缺指标不评分，不断言最佳 |
| P2 中文审核请求 | existing | PR45 assistant.parse_request | 直接调用受限解析，加请求摘要/待绑定信息；不另写自然语言引擎 |

其他PR审查：PR20 092eb0b有逐特征/监督及制造执行，PR28 e865b3d有真实滚筒改型链，PR43 d422f69含特征合约/sw_compat且base不同，PR48 1ab7e8e有跨版本证据文件核验。本批不复制其几何/COM/滚筒算法；现有验收继续使用各自pin。PR47 9229517生命周期候选不混入本批。

新代码只产出离线结果和原生审核任务。native_review.prepare_native_review将已解决链的可调叶尺寸和全部保护尺寸映射到现有审核协议；execute_native_review复用PR45 execute_reviewed_transaction，调用者必须供应已有已归属隔离port及当前审核摘要，未添加新的COM附着/创建/退出入口。派生总长必须另外读回，不同时写总长和筒体导致过约束。

风险：真实OEM/制造公差/目录报价须用户明确来源；同基准是输入契约，不自动解析几何基准变换；重复/相关公差项可能保守高估；目录数值筛选不等于安装兼容/采购批准；所有native均待Windows验证。未进行全库回归。
