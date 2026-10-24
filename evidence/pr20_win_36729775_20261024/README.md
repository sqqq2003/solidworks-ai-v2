# evidence · PR#20 Windows retest @ 36729775

- pin: `367297751a9bc0add008c6b92a6e30a5c6d41ac9`
- dual-source: Qoder `blocked` + WorkBuddy `fail`
- root cause: SessionOwnershipError (multi-instance COM)
- offline: 7/8 (external `/secret` path filter defect)
- native_acceptance: `pending_windows_validation`
- product source unchanged
