# PR#20 Issue#19 — lxy 审合回传（Qoder + WorkBuddy）

## Verdict
- **offline-pass**（双源独立）：Qoder + WorkBuddy 均 4/4 mock_only，resume OK，改输入拒绝
- **native**：本机 owned_spawn 仍失败（COM 注册在已有实例）；Qoder 用温复用 harness 打通最小 plate（sketch+extrude，存盘/重开/读回），但绕开了 require_model_write，故 **native_acceptance 仍 pending_windows_validation**
- WorkBuddy 只做了写闸探测（SessionOwnershipError），未绕闸建模——与 Qoder 结论一致、非回归
- **未跑 p248**；未 ExitApp/taskkill
- pin sha: e1a14a74210471a09e1c82a8f77a9e8c7904f8aa

## Qoder（更完整）
- 离线/import smoke：pass
- owned_spawn：spawn 19724，COM 仍在 16564 → SessionOwnershipError，进程保留
- warm harness：part.SLDPRT 已写；readback sketch1=ProfileFeature, extrude1=Extrusion；几何约 10×40×40 mm
- **代码修复**（未提交，工作副本）：`src/ql5050px/editable_features.py`
  - ISketch 无 GetFeature → FeatureByPositionReverse(0)
  - IModelDoc2 无 FeatureByName → IPartDoc + IFeature
- diff: logs/pr20_native_fix.diff

## WorkBuddy（交叉）
- 独立目录复现 offline-pass
- native attach 写闸拒绝（按设计）；partial_1_of_2

## Recommended next
1. Issue19 离线契约可标 offline-pass
2. 审合 Qoder 的 editable_features 补丁进 PR
3. Native 正式验收：需 owned_spawn 可用环境，或产品决定是否放宽 warm-reuse 写闸