# Native batch recovery and evidence handoff

This change extends the existing Issue 19 / PR 20 implementation, based on
2ab51aa66051bfe064b0df54d2fb767e048e4f20. It does not establish a Windows native pass.
The earlier PR 21 warm-harness result bypassed the write gate and remains diagnostic evidence only.

## Callable additions

From the repository root:

```powershell
python work/project.py native-doctor --sw-exe "C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe"
python work/project.py export-acceptance path/to/batch --out path/to/new-handoff
```

Python interfaces:

```python
from ql5050px.native_environment import inspect_environment
from ql5050px.acceptance_report import collect_acceptance, export_acceptance
from ql5050px.modeling_supervisor import supervise

report = inspect_environment()  # observations only; grants no write authority
summary = supervise(jobs, new_batch_directory)
package = export_acceptance(new_batch_directory, new_handoff_directory)
```

`native-doctor` reads active COM registration, revision, PID and document count.
It never launches CAD, writes documents, closes them or authorizes writes. An active
registration can belong to a pre-existing single-instance process; the owned-launch
proof and `require_model_write` remain mandatory.

The supervisor now acquires an exclusive batch-directory lock. A second supervisor
cannot launch into that directory. A normal return releases the lock; a forcibly
terminated supervisor can leave it behind. Do not automatically steal a stale lock:
inspect its PID and worker/session evidence before an operator removes it. This lock
covers one batch directory, not all CAD activity on the machine.

Unknown, failed or review-required cleanup stops the batch. The summary includes
all remaining jobs as `not_run`. Reusing such an attempt requires existing
`recover-parts` review, after worker liveness is resolved. A worker error with
confirmed owned-document cleanup can continue to the next job. No unknown CAD
process is killed. Body-count-only verification contracts now inspect solid bodies
even when no envelope dimensions were requested.

`source-manifest.json` records code hashes and the existing request/code signature.
The exporter rehashes artifacts, checks completed-phase consistency and packages
`acceptance.json` plus `SHA256.json` in `gork-acceptance.zip`. It omits CAD binaries,
raw logs and absolute artifact paths. Missing fingerprints, missing artifacts,
changed hashes, external artifacts and contradictory completed states cannot yield
consistent evidence. Consistent evidence is not independent model inspection or
manufacturing approval. Preserve the original batch privately for diagnosis.

## Focused verification and Gork handoff

```bash
PYTHONPATH=src python -m unittest discover -s tests -p test_acceptance_recovery.py -v
```

Eight offline contracts cover reuse, lock refusal, safe-error continuation,
uncertain-cleanup stop/retry refusal, evidence rehash/package contents, external
artifact/source-path filtering, empty evidence rejection and non-Windows diagnosis.
These use fake workers and fixture bytes, not real CAD files. No broad regression
suite or ordinary bug cleanup was performed.

On Windows, pin the new PR 20 head and record `git rev-parse HEAD`. Run the existing
four reviewed recipes through the guarded owned launcher, retaining checkpoint,
worker return code, close/reopen results, geometry readback and sheet flat export.
Run native-doctor before the batch if binding is unclear; never bypass the write
gate to obtain a pass. Return the exported evidence package and commit pin. Confirm
clean process exit separately from successful save/reopen. Native COM teardown,
real feature geometry and manufacturing output remain pending Windows validation.
