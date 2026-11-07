# A01 持续开发：装配预检与稳定引用

沿用 GORK-A01-004 及现有任务依赖，不新增重复执行者。本批不等待 S2 原生回执，继续推进不依赖 SolidWorks 的整机功能。

已实现：A01 命令行接入已有 QL 装配算法；组件唯一性、固定件与配合连接、自由度估算、传动关系、静态 AABB 间隙和线性运动采样检查；引用记录绑定文件 SHA256、配置、组件路径、实体类别及持久引用 token，拒绝序号代替持久引用和重复物理目标。

修复 QL 图算法：抑制配合不再删除相同两组件间已有的有效边；不支持或无效配合不再产生虚假的固定路径。

实际运行入口（示例全部为合成尺寸，不是生产参数）：

```powershell
python -X utf8 -m src.a01_parametric.cli --assembly-check examples/a01_assembly_preflight.json --out runtime/a01-assembly-review.json
```

A01 的未映射尺寸仍使整体返回 review_required（退出码3）；输出里的 assembly_preflight 可单独为 offline_consistent。此行为不是运行崩溃。现有 dry-run/live 参数流程保留；本批不会自动进行 CAD 写入。

引用入口：`--reference-check registry.json`。schema_version=1，references 数组中每条包含 id、document_sha256、configuration、component_path、entity_type、persistent_reference_base64。实体类型允许 face/edge/vertex/plane/axis/point。所有结构有效记录仍返回 pending_native_resolution；必须在独占工作副本上实际解析、核对几何特征和重建后稳定性，才能用于原生配合。

尚未完成的工程能力：

- 真实 A01 模型尺寸、组件与接口映射仍需图纸/模型依据；不得自动补成 OEM 数值。
- A01 mate_check 和 drawing_export 原生入口仍有占位，未声称实现原生配合求解或生产工程图。
- 本批运动仅为平移离散 AABB；旋转、连续碰撞、配合雅可比、机构动力学仍未实现。
- S2 独占会话重开、原生钣金完整发布和正常退出仍需既有 WB/Qoder 实机回执；C# 原生构建仍未验证。
- 后续优先将已确认映射接入工作副本的原生装配/工程图执行器，再按现有串行会话安全门槛测试。

测试方统一沿用 batch-intake-20261024.md 的交接方式；当前 S2 测试若已启动，先完成，不中途更新工作目录。新增纯离线预检可在另一 Python 进程测试，无需启动 SolidWorks。原生结论和机械工程验收单独记录。
