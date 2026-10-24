# evidence · PR#20 Windows retest @ 36729775

- pin: `367297751a9bc0add008c6b92a6e30a5c6d41ac9`
- native conclusions: **r2 supersedes r1** (see `r2/`). r1 remains as the multi-instance SessionOwnershipError baseline.
- r2: owned-launch PASS; still fail (plate/bracket type mismatch; shaft COM disconnect; two_bend not_run)
- r2 recommendation: PR17 SAFEARRAY rebase
- r1 dual-source: Qoder `blocked` + WorkBuddy `fail`
- r1 root cause: SessionOwnershipError (multi-instance COM)
- offline: 7/8 (external `/secret` path filter defect)
- native_acceptance: `pending_windows_validation`
- product source unchanged
