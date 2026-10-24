# A01 原生改型、配合与工程图试运行入口

本批增加执行代码，未在真实 A01 模型上验收。沿用现有任务与单写者会话，不覆盖正在跑的测试目录。

## 一次流程

`work/run_a01_production.py request.json` 默认仅校验；显式 `--live --sw-exe <安装路径> --out <全新工作目录>` 才启动独占 SolidWorks。源装配按 SHA256 绑定；Pack and Go 隔离全部依赖；只修改副本。确认的尺寸按配置写入，重建、保存、重开读回。任一未解析尺寸、映射哈希不符或越界即拒绝。

请求 schema_version=1，字段：

- source_assembly、source_sha256、configuration：实际母装配及其身份。
- document_sha256：键为映射文档的绝对规范路径，值为其 SHA256。
- mapping：既有 sw_api.mapping schema（parameters 数组）。每项必须 confirmed、editable，有 parameter/document/configuration/feature/dimension/unit/source/allowed_range。dimension 如 D1@Sketch1，必须指向指定 feature。
- values：与映射 parameter 完全一致的数值表，使用映射声明的 mm/m/deg 单位；不自动填默认尺寸。
- mates（可选）：id、type（coincident/concentric/parallel/distance/angle）、alignment（0/1/2）、references（两个语义引用ID）；距离/角度必须明确 distance_mm/angle_deg。
- references：既有稳定引用 registry。token 必须在 source_assembly 和相同 configuration 上捕获。组件路径留作追溯；运行时通过原生持久引用解析，不按面序号选择。已存在同名配合拒绝覆盖，新增配合经原生重建及特征错误码检查，保存后再次检查。
- drawing_plan（可选）：既有 manufacturing_drawings 结构，status=ready_for_native、tasks 中 node=A01、exports=[SLDDRW]，明确 standard=GB_T、projection=first_angle。必须有确认的尺寸引用、基准/公差/工艺信息、视图、关联 BOM、工程图模板和 BOM 模板。输出 filename 必须安全、唯一。模板不是第一角时原生读回拒绝继续。

工程图复用 ManufacturingDriver 的模型视图、投影视图、尺寸、注释、关联 BOM 和气泡；新增保存重开后的 PDF 导出及 SHA256。尺寸来自模型实体，不覆盖显示数字。PDF 版面、尺寸完整性和工程审签仍 pending，不自动放行制造。

## 运行与测试

```powershell
python -X utf8 work/run_a01_production.py request.json
python -X utf8 work/run_a01_production.py request.json --live --sw-exe '<实际SLDWORKS.exe>' --out '<全新工作副本目录>'
python -X utf8 -m unittest discover -s tests -p test_a01_production.py -q
```

请求中的实际模型路径、哈希、参数依据、模板和原生引用需要来自真实工程资料，不能用本单元测试的任意字节替代。仅依赖文件存在无法证明它是有效 SW 文件，原生打开错误会进一步阻断。

## 安全与能力边界

不附着未知 SW、不终止未知进程、不回写母工程。失败时保留新工作目录诊断，不将部分副本发布为成品；映射修改可能部分保存在副本里，当前不自动回滚这些新副本。输出始终 cad_release_approved=false，工程师仍需检查机构和图纸。连续运动/动力学与 PDF 文字碰撞审查不在本批实现范围。

原生 API 路线依据官方说明：[持久引用](https://help.solidworks.com/2025/English/api/sldworksapiprogguide/overview/Persistent_Reference_IDs.htm)、[AddMate5 返回 IMate2](https://help.solidworks.com/2025/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IAssemblyDoc~AddMate5.html)、[GetErrorCode2](https://help.solidworks.com/2021/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IFeature~GetErrorCode2.html)。AddMate5 在新版本已废弃但兼容路线仍可用；跨版本 COM 签名与重开稳定性需本机测试，不能把模拟通过写成实机通过。
