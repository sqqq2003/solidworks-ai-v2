# PR 22 evidence review and corrections

Reviewed evidence PR 22 at `5e6805bd20010f7cbec5ec0eeca2316949c30655`.
It tested product `367297751a9bc0add008c6b92a6e30a5c6d41ac9`, not the later
whole-machine transaction at `544702fa9abe8dd82bacc88b60497d9e899018a0`.

Both Qoder and WorkBuddy report owned-launch PID/COM mismatch. The first plate
job failed before writing CAD; bracket, shaft and two_bend_sheet were not_run.
Save/reopen, feature geometry, flattening and cleanup remain unverified. The
write gate correctly remained enforced. Test processes were left untouched.
The repository contains structured results and summaries; raw traceback logs,
full batch directories and binary ZIP files listed under local Windows paths
were not uploaded in PR 22 and have not been independently inspected here.
The reported local git parent/pack issue cannot be repaired from this workspace.
Use a separate intact checkout for the next pinned run; preserve existing work.

## Product corrections

- Source hash keys use both PurePosixPath and PureWindowsPath semantics regardless
  of host OS, rejecting rooted POSIX paths, drive paths, UNC paths and traversal.
  This fixes the Windows `/secret` regression; the earlier Linux-only test result
  did not establish portability.
- Acceptance schema 2 explicitly separates record_consistent (honest coherent
  records) from execution_complete (all jobs reported completed). evidence_consistent
  now requires every job completed with consistent phases/artifact hashes. Failed
  and not_run rows receive job_not_completed. None of these grants native acceptance
  or manufacturing approval. Export command output includes counts and all flags.
- The owned launcher checks active COM registration read-only before creating a
  new CAD process. An existing registration or unexpected probe error refuses
  before spawn. No automatic CloseDoc/ExitApp/taskkill is added. An absent active
  registration alone proves no ownership; retained handle, matching PID, document
  inventory and write gate remain mandatory after spawn. Unregistered instances
  and races can still cause later refusal; this is not a multi-instance fix.
- The CLI's raw RuntimeError traceback on resume was already addressed by the
  later 544702f change; it remains in this branch.

`pr22-export-recheck.json` is a re-evaluation of the uploaded WorkBuddy batch
summary and uploaded acceptance source fingerprint, with local attempt path and
worker PID omitted. It uses no invented artifacts or new native run. Result:
record_consistent=true, execution_complete=false, evidence_consistent=false,
counts needs_review=1/not_run=3, native_acceptance=pending_windows_validation.

## Focused verification / unified next run

13 offline contracts pass (10 acceptance/recovery, 3 fake-COM launch-preflight).
Python syntax checks pass. No Windows execution or broad regression was performed.

On Windows, pin the new PR 20 head from its delivery comment. First rerun:

```powershell
python -m unittest discover -s tests -p test_acceptance_recovery.py -v
python -m unittest discover -s tests -p test_owned_launch_preflight.py -v
python work/project.py native-doctor --sw-exe <installed-SLDWORKS.exe>
```

If an existing registration is present, verify native launch refuses without
adding another SLDWORKS PID. Prepare a dedicated environment through the operator,
preserving work and closing only sessions they identify; agents must not kill
unknown sessions. A clean environment is a prerequisite, not proof launch will
succeed. Repeat the four reviewed recipes only after owned binding succeeds.
Retain save/reopen, geometry, sheet flat export and separate process-exit evidence.
Re-export the prior failed batch to confirm the new non-completion flags, then
return one unified result pinned to the new SHA. Do not infer native acceptance
from a ZIP or record consistency. Whole-machine OEM mappings remain pending and
PR 22 provides no evidence for that later flow.
