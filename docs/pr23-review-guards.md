# Independent assistance review of PR 23

Based on PR23 head 140768d485f735e05f31df66d15f37cf7acc1ae9. This is a
companion change, not a merge into dev/cloud-ai and not a native validation.

Confirmed defects corrected in run_recovery.py:

- A live PID with an expired heartbeat was deliberately archived by the old
  implementation and its test. A long blocking native operation can stop heartbeats
  while remaining alive; elapsed heartbeat time does not prove death. Live or
  unprobeable owners now refuse acquisition regardless of age. Only explicit
  ProcessLookupError establishes dead-owner recovery. Permission denied remains
  live; malformed IDs and other probe failures are unknown and refuse recovery.
  No processes are killed. Heartbeat age remains diagnostic. An unprobeable old
  owner requires operator inspection, not automatic lock stealing.
- run_teardown_sequence previously marked any returned exit code as an OK step,
  including 139 and None; failed release dictionaries were also recorded as OK.
  Nonzero/bool/unknown exit values and negative release reports cannot produce
  ok=true now. The original exit value is retained. Failed document close or a
  nonempty/unavailable title inventory skips ExitApp; remaining evidence steps
  are still recorded. Callers must continue supplying ownership-guarded callbacks:
  an empty title inventory alone is not proof a process belongs to this task.
- Checkpoint product names previously allowed absolute/traversal paths and external
  symlinks when their bytes matched. Both path syntaxes and resolved containment
  are now checked before product hashing; invalid products cannot resume a stage.

Seven new focused review contracts plus the fourteen original PR23 tests pass
(21 total, all offline/fake). The two pipeline tests were run with the exact PR23
pipeline/native dependency files materialized locally and existing support modules.
An initial incomplete local staging attempt lacked those files; it was corrected
before reporting results. Python syntax checks pass. No broad regression or
Windows/SolidWorks test was performed.

This patch does not prove COM teardown stability, solve OS PID reuse, redesign
all lock recovery races, certify geometry, or upgrade artifacts to native acceptance.
Original p248 algorithm and per-job bend inputs are untouched. PR27 is stacked
on PR23 and should carry these corrections when rebased, with its focused tests
rerun. Preserve the existing requirement to inspect normal process exit separately.

Related review observations (outside this patch): PR26's C# Program always
constructs MockSwApp and emits a hardcoded exit_code=0. PR27's channel='bridge'
is a transport label; it does not prove native SolidWorks execution. Its existing
documentation already notes that build/reopen remain on the Python port. Any
future native implementation needs explicit backend identity and a real observed
exit code; do not treat C# transport success as resolved COM ownership/teardown.
