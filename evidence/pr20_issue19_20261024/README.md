# PR#20 / Issue#19 local acceptance evidence (2026-10-24)

Docs-only packet. Product source is unchanged. `pr20_native_fix.diff` is the uncommitted SW2022 patch Qoder saved from the work copy; it is stored here as evidence and is not applied.

Existing product PR: https://github.com/sqqq2003/solidworks-ai-v2/pull/20 (draft, `feat/issue19-staged-modeling` → `dev/cloud-ai`).

Same packet already posted on Crosswalk as #a66ubx.

## Verdict

- Pin sha: `e1a14a74210471a09e1c82a8f77a9e8c7904f8aa`
- Offline-pass, dual-source (Qoder + WorkBuddy): 4/4 `mock_only`, resume OK, changed input rejected
- Native still `pending_windows_validation`
  - `owned_spawn` COM registration fails on this single-instance SolidWorks (spawned PID did not own the COM object)
  - Qoder warm plate smoked (sketch + extrude, save / reopen / readback) but the harness bypassed `require_model_write`
  - WorkBuddy write-gate probe was refused by design (`SessionOwnershipError`); no plate was written
- p248 was not run and is not claimed

`RESULT_codex_pr20_issue19_20261024_135326.json` is the WorkBuddy result. In the triad bus that role is recorded as `codex`.

## Files

| File | Source |
| --- | --- |
| `HANDOFF_pr20_issue19_to_codex_20261024.md` | Dual-source verdict for Codex (Qoder + WorkBuddy) |
| `NOTE_qoder_pr20_native_followup_20261024_141444.md` | Qoder native follow-up |
| `RESULT_qoder_pr20_issue19_20261024_135326.json` | Qoder RESULT |
| `RESULT_codex_pr20_issue19_20261024_135326.json` | WorkBuddy RESULT (`role=codex`) |
| `accept_pr20_qoder.json` | Qoder accept record |
| `accept_pr20_wb_20261024_140819.json` | WorkBuddy accept record |
| `pr20_native_fix.diff` | Uncommitted `src/ql5050px/editable_features.py` SW2022 fix (do not apply from this packet) |
| `native_attach_probe.json` | WorkBuddy write-gate probe |
