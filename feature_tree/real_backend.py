"""Real SolidWorks backend adapter: STUB ONLY, pending_windows_validation.

This file exists so the executor's backend boundary is explicit and the
real implementation has exactly one place to land. Nothing here is
implemented: calling execute() raises NotImplementedError, and no COM
object is created, no document is opened, and no process is spawned.

When the real adapter is written (Windows + SolidWorks only), it MUST
follow the disciplines already established on dev/cloud-ai:

* Exclusive session: spawn a fresh SolidWorks process for the run and
  bind it by PID. Never attach to an existing process by name, never
  close a document or process whose ownership is unknown.
* STA: all COM calls on one single-threaded-apartment thread.
* Release order (from #23): release COM wrappers in reverse order of
  acquisition, then gc.collect(), and only then CoUninitialize(). A
  teardown failure records the exit value as-is and never rewrites it
  to 0; S5 teardown discipline from #31 still applies (failure evidence
  + crash package, product not unpublished).
* Write scope: only the run's staging working-copy path (the same rule
  as the #32 build contract's part_path). Never write a customer
  original, never write outside the staging directory.
* Readback: after reopen, read back feature types, sheet-metal
  definition and CustomBendAllowance, and compare against the plan with
  validate_native-style tolerance (1e-6 per the #32 reopen contract).
  A mismatch is a failure, not a rounding note.
* Parameter discipline: thickness, radius, angle and K factor are
  required per-job inputs; a missing value is pending_confirmation,
  never a default number.

Until all of the above exists and passes Gork's Windows acceptance
matrix, this backend must stay a stub. Mock results from mock_backend.py
are never a substitute for it.
"""

from __future__ import annotations


class RealSwAppAdapter:
    """Placeholder for the future Windows SolidWorks adapter."""

    BACKEND_NAME = "real-stub"

    def __init__(self, sw_exe: str | None = None):
        # Stored, never used, until the real implementation lands.
        # sw_exe is the path to SLDWORKS.exe for a future owned spawn.
        self.sw_exe = sw_exe

    def execute(self, node) -> dict:
        raise NotImplementedError(
            "RealSwAppAdapter is a stub (pending_windows_validation): "
            "node %s of type %s has no Windows implementation yet; "
            "use MockSwApp for offline runs." % (node.id, node.type)
        )
