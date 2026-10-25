# Consolidated feedback patch — Issues 39 / PR22 / recovery and exit evidence

Base: dev/cloud-ai aca899b2d7daf2d0b9a2edabda48a56a477b1711.
Native-part additions are imported from PR20 092eb0bbeffc03b46502945095c76a64d7c22545,
then adapted to this current session layer. One candidate checkout now contains
the previously separate path/selection/feature-readback fixes and new lifecycle
candidate. No wholesale overwrite of old engine, no merge into dev/main, no
customer CAD or original test binaries.

## Corrections and evidence boundary

| Feedback | Code action | Validation remaining |
| --- | --- | --- |
| S1 last-document close then CO_E_OBJNOTCONNECTED | A task-owned unsaved blank part anchors the session across intermediate close/reopen; UserControl alone is no longer the policy | Windows SW2022/2025 retest required; underlying native cause not independently established |
| Disconnect misclassification | Add -2147220995 to both session/generator HRESULT classifiers | Real traceback/process observation |
| Per-stage COM release timing | Helpers borrow the already initialized task STA; only extra initialization they actually own is uninitialized locally | Native wrapper/apartment lifetime |
| Teardown false pass | Wait briefly for actual retained-process exit; nonzero/unknown exits remain review failures; propagate cleanup errors and preserve worker/model evidence | Real clean exit |
| End-of-session COM references | Drop lease/binding app references on STA only after clean session completion; failure references are retained for recovery | Native unloading |
| Repetition uses stale lease | Minimal probe repeats use separate CLI processes; failed/timeout worker stops further native attempts without kill | Three independent Windows exits |
| PR22 type mismatch | Imported typed null IDispatch Callout, SW2022 feature/part interface fixes; typed application registered once in the current host | Candidate fix still needs native confirmation |
| PR22 path and acceptance flags | Imported portable POSIX/Windows path filtering and separate record consistency/completion, incomplete rows never evidence-consistent | Windows exporter rerun |
| Existing registered instance | Before spawn, a read-only registration probe refuses existing/unknown instances | Registered refusal/no extra PID |
| Windows PID and test path issues | Current dev's Win32 non-signalling probe and Path.as_posix test fix retained; regression contracts included | Real Windows probe |
| Lost S1 artifact on native failure | Preserve native staging/checkpoints; mark RECOVERY_REQUIRED and refuse silent resume. Simulated rollback behavior retained | Recovery review workflow |

The anchor uses only the existing installed part template (or explicit reviewed
part-host template), never a user document. It is registered as owned, unsaved and
not part of the deliverable. If ownership/template/inventory cannot be established,
closing is refused; it never attaches to a warm session or closes foreign files.
Intermediate bulk-close becomes individual owned closes while preserving the anchor.
Final cleanup first proves only the anchor remains, then closes it. A clean
automatic process exit at this point does not trigger another COM call. A nonzero
or unobserved exit is never converted to success. Only this proven sole-anchor
close can tolerate a disconnection paired with an independently observed exit 0.
A modelling error or an earlier disconnect is not masked by that condition.

The observed symptom is addressed by a new candidate lifetime policy, not a claim
that the actual SolidWorks crash is fixed. No Windows run occurred here. Geometry,
p248 transforms/bends/relief algorithms and per-job t/R/K/angle defaults are unchanged.

## Targeted checks

118 targeted offline cases run: 117 passed, 1 skipped, 0 failures/errors.
The skip is the original local-only baseline source hash fixture absent in cloud.
Cases cover real serialized STA/lease gates with fake COM/processes, last-document
auto-exit despite UserControl, anchor preservation, foreign-document refusal,
clean/nonzero/unknown final exit, borrowed COM scope, independent repeat workers,
worker cleanup persistence, retention/review of failed native staging and the
imported prior patch contracts. No full repository regression or native CAD pass.
See delivery/issue39-unified/offline-checks.json for exact suite files.

## Unified Windows retest — one candidate SHA

Use the new PR's full SHA, a fresh independent checkout and Python environment.
Do not overlay the old ZIP or use old compiled plans: session/pipeline code hashes
changed and stale plans must be regenerated. Preserve operator work and prepare a
dedicated environment. Do not terminate unknown SLDWORKS processes.

Prepare an explicit synthetic reproduction matching the reported sizes (not a
byte-identical copy of the unuploaded original fixture):

```powershell
$SwExe = 'D:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\SLDWORKS.exe'
$Run = 'D:\工程\钣金导入\issue39-unified-new'
python work/prepare_issue39_retest.py --out $Run --sw-exe $SwExe --length 100 --width 80 --bend-x 50 --thickness 2.5 --radius 1 --angle 90 --k-factor 0.4 --direction normal
```

Those dimensions and bend values are explicit example inputs, never defaults.
commands.json contains exact argument vectors bound to the Python executable and
checkout that prepared them: minimal exit (three fresh workers), offline fixture,
and native S1/S2/flat export. Run each vector without shell string evaluation:

```powershell
$Steps = Get-Content -LiteralPath (Join-Path $Run 'commands.json') -Raw | ConvertFrom-Json
foreach ($Step in $Steps) {
  $Exe = $Step.command[0]
  $ArgVector = @($Step.command | Select-Object -Skip 1)
  $Err = Join-Path $Run ($Step.id + '.stderr.txt')
  $Text = & $Exe @ArgVector 2> $Err
  $Code = $LASTEXITCODE
  $Text | Out-File -LiteralPath (Join-Path $Run ($Step.id + '.stdout.json')) -Encoding utf8 -NoClobber
  if ($Step.id -eq 'minimal-exit' -and $Code -ne 0) { throw 'Native lifetime unresolved; inspect before further SW runs' }
  if ($Step.id -eq 'native-S1-S2' -and $Code -ne 0) { throw 'Preserve native checkpoints/diagnostics and review lifetime' }
}
```

Record git rev-parse HEAD before running. Verify anchor_created/anchor_closed,
cleanup_error, cleanup_exit_code, S0/S1/S2/S3 evidence, reopened geometry and flat
DXF. Saved bytes alone or keepalive_verified alone do not satisfy native acceptance.
Existing retained-handle PID/STA/document/write proofs remain mandatory.

The four reviewed recipes are now callable in this checkout:

```powershell
python work/run_reviewed_parts.py doctor --sw-exe $SwExe
python work/run_reviewed_parts.py package examples/production_recipes.json --out (Join-Path $Run 'recipes-offline')
python work/run_reviewed_parts.py review examples/production_recipes.json --sw-exe $SwExe --template '<actual reviewed part.prtdot>' --sketch-plane '<actual plane>' --out (Join-Path $Run 'reviewed-jobs.json')
python work/run_reviewed_parts.py run (Join-Path $Run 'reviewed-jobs.json') --out (Join-Path $Run 'recipe-native')
python work/run_reviewed_parts.py evidence (Join-Path $Run 'recipe-native') --out (Join-Path $Run 'recipe-evidence')
```

If cleanup becomes unknown, stop that native queue. Failed native staging is kept
with RECOVERY_REQUIRED.json; do not delete its marker to force a pass or resume.
Review ownership/process state, preserve evidence and use a new output root for
retest. Continue independent offline tests. p248 golden input stays local/read-only;
repeat its exact previously reviewed parameters after the synthetic case passes.

## Handoff and rollback

Return one evidence/fix PR to Issue46 and Issue39 with candidate SHA, actual inputs,
SW/Python/template versions, complete chained traceback, checkpoints, anchor/session
metadata, output hashes, feature/dimension/bend/flat results and independent worker
and SLDWORKS exit codes. Keep customer CAD/binaries local. No historical PR22 pass
is inferred. Other feature batches in Issue46 retain their own pins until explicitly
integrated and recorded; this patch does not merge unrelated platform/C# work.

Rollback code by reverting this patch or checking out the recorded parent. Preserve
failed output directories and use fresh destinations. Never use reset_for_tests,
unknown-process kill, source overwrite or relaxed ownership as runtime recovery.
