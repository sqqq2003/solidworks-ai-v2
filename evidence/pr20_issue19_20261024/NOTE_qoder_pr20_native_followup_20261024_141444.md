# Qoder 原生跟进 · PR#20 / issue19

时间：2026-10-24 14:14（task pr20_issue19_20261024_135326）
状态：warm 原生冒烟通过；owned_spawn 在本机无法证明；native_acceptance 仍为 pending_windows_validation

## 1) 工作副本有未提交修复（WorkBuddy 交叉时请注意）

work_copy: C:\sw-ai-v2-work\solidworks-ai-v2-pr20-e1a14a（仍钉 e1a14a7，未提交新 commit）

- src/ql5050px/editable_features.py
  - SW2022 的 ISketch 没有 GetFeature（typed/dynamic 都报 AttributeError）→ 改用 model.FeatureByPositionReverse(0) 命名当前草图
  - IModelDoc2 没有 FeatureByName → 改用 IPartDoc.FeatureByName，并把返回对象包成 IFeature 再调 GetTypeName2
- 补丁：D:\工程\钣金导入\wb_pr20_issue19_20261024_135326\logs\pr20_native_fix.diff
- 修改后 import smoke 复跑仍通过（无 win32com/pythoncom 导入）：
  logs\import_smoke_after_native_fix.log

## 2) 原生结果

- warm attach（PID 16564，非独占；harness 绕过 require_model_write 的 ownership gate）：
  sketch1 + extrude1 → rebuild → save → close → reopen → 特征树回读成功
  output: native_plate\part.SLDPRT
  sha256: 77bddea10791e563544d5f21b238db0f7d20bace19879ad6fe6baecac919132e
  readback: sketch1=ProfileFeature, extrude1=Extrusion
  只读复检：1 个实体，10×40×40mm（r20 圆 × 10mm 深），rebuild ok
  证据：native_plate\stages.jsonl、native_plate\checkpoint.json、logs\native_verify.json
- run_native_part / owned_solidworks：spawn 了 PID 19724，但 COM 注册仍属于既有实例 16564，
  PID/镜像证明失败 → 按设计报 SessionOwnershipError 并“原样保留进程”，未 ExitApp/taskkill。
  证据：logs\native_owned_attempt.json
- 注意：PID 19724 仍在运行（owned 尝试留下），本轮不杀；需要时请人工关闭。
  既有 16564 未被杀、未被 ExitApp。

## 3) 仍未完成 / 不要宣称

- owned_spawn 独占证明：未完成（本机单实例 + 已运行实例占用 COM 注册）
- native_acceptance：pending_windows_validation
- p248 4/4：未运行、未宣称
- 尺寸校验只覆盖最小 plate（sketch+extrude），未覆盖 cut/fillet/chamfer/mirror/pattern
