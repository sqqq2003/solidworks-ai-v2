# PR 22 r2 clean-host evidence

Evidence head: a46874ea8c1acf07f65fe931a85ded5b78c0e366.
Tested product: 367297751a9bc0add008c6b92a6e30a5c6d41ac9.
This review supersedes the earlier r1-only launch conclusion, not the retained r1
record or its valid path/export defect findings (already addressed in c1794a0).

Uploaded r2 stage logs show plate/bracket document creation followed by
DISP_E_TYPEMISMATCH (-2147352571) and successful owned document close. The shaft
log shows save then CO_E_OBJNOTCONNECTED (-2147220995). The fourth sheet recipe
was not_run. Structured acceptance reports 3/3 owned-launch/write-gate success
on a clean host, and claims the shaft artifact exists. The artifact and raw
stderr tracebacks are not uploaded; the logs do not identify the exact failed
feature COM call or prove the cause of server disappearance. No full native
recipe passed. Do not equate worker exit with clean SolidWorks teardown.

## Source comparison and changes

PR 17 sw_math_arrays.py is already present in the tested pin's ancestry. Its
CreatePoint/CreateTransform bridge cannot by itself explain the first feature
failure: the plate/bracket sketch path uses SelectByID2, then scalar line calls;
it does not invoke that math bridge. Do not merge PR 17 again or change p248
geometry based on the suggested symptom analogy.

SelectByID2's Callout argument is an IDispatch pointer. The feature IR builder
was passing bare None. A shared lazy helper now passes VARIANT(VT_DISPATCH,None),
with explicit float coordinates, in sketch plane/sketch/reference selections.
It performs one call and preserves the exception cause with the method/reference
name. This corrects the argument contract and is a targeted candidate for the
reported mismatch; r2 lacks the traceback required to prove it was the failing
call. Native verification is still pending.

Each feature now checkpoints its active ID/kind before calling COM, logs started,
and records a traceback plus active feature on failure. Local diagnostic logs
can contain CAD names/paths and should be reviewed before sharing. The shaft
backend now checkpoints output SHA256, size and saved_pending_reopen immediately
after generator return, before the separate reopen verifier. It logs verification
start and a failure traceback/last phase, using atomic checkpoint writes. A
saved file is not a completed model; disconnect still requires recovery review.
No speculative COM shutdown, guard relaxation or auto process kill is added.

## Focused checks and next unified native run

Three fake-COM/host tests pass: typed null dispatch/one call, method/cause retained,
and durable failing-feature context/traceback. Python compilation passes. No broad
regression or Windows test was performed.

Pin the new PR20 head from its delivery comment, including c1794a0's portable
path/export/prelaunch changes and the later whole-machine code. Use an
operator-prepared clean environment and preserve the ownership gate. Run the
four reviewed recipes serially in a new batch directory. Return the active
feature, full chained traceback, shaft generator/verification/cleanup phases and
separate SW process-exit evidence. If cleanup becomes uncertain, preserve the
stop/recovery policy. The two-bend job is not assumed to pass or silently retried.
The native full-chain verdict remains pending_windows_validation. The prelaunch
check guards registered existing instances, not all possible processes/races.
