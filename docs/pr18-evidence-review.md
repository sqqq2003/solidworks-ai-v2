# PR #18 evidence review

Actual uploaded evidence reviewed, head 6fe5a9f. Gork reports p248 4/4 and first-run reopen/unfold r3 success; retest saved and inline-unfolded but explicitly skipped its own reopen/DXF. Process teardown still crashes. Local patched source is not included in the evidence-only PR, so the results cannot be attributed to unmodified repository source.

Fix native_machine typed wrapper registration once at guard connection; preserve exact app instance for teardown. Do not weaken lease identity checks or authorize arbitrary warm sessions. Do not turn EXIT=139/0xC0000005 into unconditional success: artifact verification and process outcome remain separate. Existing accepts remain untouched. Windows retest of this repository patch is pending.
