"""Wire the csharp-bridge client into run_plan stages S1/S2/S5.

Issue #25, next batch (stacked on PR #23). Pure standard library, so this
module is unit-testable on Linux without SolidWorks or pywin32.

The bridge client itself lives in ``csharp-bridge/python/bridge_client.py``
(PR #26). This module deliberately does NOT import it, so src/ stays free
of cross-directory imports and this branch (stacked on PR #23) does not
need the csharp-bridge/ tree to exist. Callers inject a client object with
the same interface::

    call(method, params=None) -> result dict
    teardown(owned_titles=()) -> {"steps": [...], "exit_code": int}

Evidence discipline (hard):
- ``channel`` says which transport answered: "bridge" (real C# bridge) or
  "mock" (MockTransport / test fake). A mock answer is NEVER graded as
  bridge success: grade is "bridge" only when channel == "bridge" and the
  call succeeded; every other outcome is grade "mock" with a
  fallback_reason.
- The wiring never invents per-job parameters: it records no thickness,
  radius, angle or K factor of its own. Those are plan inputs (build_plan
  already pendings them when missing); the wiring only passes evidence
  through. Missing inputs stay pending_confirmation, never defaulted.
- Bridge evidence never upgrades a run: a simulated run stays simulated,
  and a bridge grade says only "the bridge channel answered", never
  "native SolidWorks ran".
- Every Windows behaviour here is pending_windows_validation. Mock
  success is never native acceptance.

Fallback semantics:
- Bridge unavailable (no client, or hello handshake fails) is ordinary
  fallback, not a failure: the run continues on the port-only path and
  no crash package is written.
- A bridge call that fails mid-run (spawn / list_titles) also falls back
  for that stage; the run continues.
- A bridge teardown failure at S5 is different: the artifact already
  landed, so the run is NOT unpublished. The failure is recorded in the
  S5 checkpoint evidence plus a crash package (written by run_plan), and
  acceptance readers must check ckpt-S5 before claiming "full-process
  stable".
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Teardown step order, mirrored from bridge_client.TEARDOWN_STEPS.
TEARDOWN_STEPS = (
    "close_documents",
    "enumerate_titles",
    "exit_app",
    "release_wrappers",
    "process_exit",
)

_FORBIDDEN_EVIDENCE_KEYS = ("thickness_mm", "radius_mm", "angle_degrees", "k_factor")


def validate_bridge_evidence(evidence) -> bool:
    """Assert the shape of one bridge evidence block recorded into ckpt JSON.

    Raises ValueError on any violation. Used by tests and by reviewers;
    run_plan itself does not call it in the hot path, so a wiring bug can
    never turn a successful run into a spurious failure.
    """
    if not isinstance(evidence, dict):
        raise ValueError("bridge evidence must be a dict")
    if evidence.get("grade") not in ("bridge", "mock"):
        raise ValueError("bridge evidence grade must be 'bridge' or 'mock'")
    if evidence.get("stage") not in ("S1", "S2", "S5"):
        raise ValueError("bridge evidence stage must be S1, S2 or S5")
    if evidence.get("channel") not in ("bridge", "mock"):
        raise ValueError("bridge evidence channel must be 'bridge' or 'mock'")
    if evidence["grade"] == "bridge" and evidence["channel"] == "mock":
        raise ValueError("mock channel must never be graded 'bridge'")
    if evidence["grade"] == "bridge" and evidence["stage"] == "S5":
        if not isinstance(evidence.get("exit_code"), int) or "teardown_steps" not in evidence:
            raise ValueError("bridge S5 evidence needs exit_code and teardown_steps")
    for key in _FORBIDDEN_EVIDENCE_KEYS:
        if key in evidence:
            raise ValueError("bridge evidence must not invent per-job parameters: " + key)
    return True


class BridgeWiring:
    """Bridge session + evidence adapter for run_plan.

    ``client`` is a bridge client object (see module docstring). ``channel``
    is required and explicit: pass "bridge" for the real C# named-pipe
    transport, "mock" for MockTransport / test fakes. There is no
    auto-detection: guessing the channel is exactly how mock results end
    up mislabelled as native evidence.
    """

    def __init__(self, client, *, channel):
        if channel not in ("bridge", "mock"):
            raise ValueError("channel must be 'bridge' or 'mock'")
        self.client = client
        self.channel = channel
        self.available = False
        self.probe_error = None
        self.session = None

    def probe(self) -> bool:
        """Hello handshake. Cheap, retried per stage; never raises.

        A failed probe is ordinary unavailability (fallback), not a run
        failure. Only the session (spawn result) is cached, never the
        probe outcome, so a bridge that comes up mid-run is picked up
        again at S5.
        """
        if self.client is None:
            self.available = False
            self.probe_error = "no bridge client supplied"
            return False
        try:
            self.client.call("hello")
            self.available = True
            self.probe_error = None
            return True
        except Exception as exc:  # noqa: BLE001 - probe failure is fallback data
            self.available = False
            self.probe_error = str(exc)
            logger.warning("bridge probe failed, falling back to port-only path: %s", exc)
            return False

    def ensure_session(self) -> dict:
        """Spawn once per run; returns the S1/S2 session evidence block.

        Never raises: a spawn failure is fallback evidence, and the run
        continues on the port-only path.
        """
        if not self.probe():
            return {"grade": "mock", "channel": self.channel, "available": False,
                    "fallback_reason": self.probe_error}
        if self.session is None:
            try:
                result = self.client.call("spawn", {})
                self.session = {"pid": result.get("pid"), "owned": result.get("owned")}
            except Exception as exc:  # noqa: BLE001 - spawn failure is fallback data
                logger.warning("bridge spawn failed, falling back to port-only path: %s", exc)
                return {"grade": "mock", "channel": self.channel, "available": False,
                        "fallback_reason": "spawn failed: " + str(exc)}
        return {"grade": "bridge" if self.channel == "bridge" else "mock",
                "channel": self.channel, "available": True,
                "session": dict(self.session)}

    def s1_evidence(self) -> dict:
        """Evidence block merged into the ckpt-S1 evidence.

        NOTE: the bridge contract (PR #26) has no build method yet, so
        generation itself still runs through the port. This block records
        only the bridge session proof + grade for S1; a future batch that
        adds a bridge build method will extend it, not reinterpret it.
        """
        evidence = self.ensure_session()
        evidence["stage"] = "S1"
        return evidence

    def s2_evidence(self) -> dict:
        """Evidence block merged into the ckpt-S2 evidence.

        Reuses the S1 session and verifies liveness cheaply via
        list_titles. A lost session is fallback evidence, not a run
        failure: reopen inspection itself already ran through the port.
        """
        if not self.probe():
            return {"grade": "mock", "channel": self.channel, "available": False,
                    "fallback_reason": self.probe_error, "stage": "S2"}
        if self.session is None:
            evidence = self.ensure_session()
            evidence["stage"] = "S2"
            return evidence
        try:
            titles = self.client.call("list_titles")
            return {"grade": "bridge" if self.channel == "bridge" else "mock",
                    "channel": self.channel, "available": True,
                    "session": dict(self.session),
                    "open_titles": titles.get("titles", []), "stage": "S2"}
        except Exception as exc:  # noqa: BLE001 - session loss is fallback data
            logger.warning("bridge list_titles failed at S2, falling back: %s", exc)
            return {"grade": "mock", "channel": self.channel, "available": False,
                    "fallback_reason": "list_titles failed: " + str(exc), "stage": "S2"}

    def teardown_evidence(self, owned_titles=()):
        """Run the bridge 5-step teardown; returns ``(evidence, error)``.

        ``error`` is None on every path except a genuine teardown call
        failure on an established session. Plain unavailability (probe
        failed, or no session was ever established this run) returns
        fallback evidence with error None: it is not a failure and gets
        no crash package. A genuine teardown failure is returned so
        run_plan can record it in ckpt-S5 plus a crash package WITHOUT
        unpublishing the already-landed artifact.
        """
        if not self.probe():
            return ({"grade": "mock", "channel": self.channel, "available": False,
                     "fallback_reason": self.probe_error, "stage": "S5",
                     "teardown": "bridge_unavailable_run_plan_teardown_only"}, None)
        if self.session is None:
            # No session was established this run (S1/S2 fell back or this
            # is a resumed run): there is nothing to tear down. This is
            # fallback, not failure.
            return ({"grade": "mock", "channel": self.channel, "available": False,
                     "fallback_reason": "no bridge session established; teardown skipped",
                     "stage": "S5",
                     "teardown": "bridge_no_session_teardown_skipped"}, None)
        try:
            report = self.client.teardown(owned_titles=owned_titles)
            steps = report["steps"]
            order = [step.get("event") for step in steps]
            if order != list(TEARDOWN_STEPS):
                raise ValueError("teardown step order violated: %r" % (order,))
            exit_code = report["exit_code"]
            return ({"grade": "bridge" if self.channel == "bridge" else "mock",
                     "channel": self.channel, "available": True,
                     "session": dict(self.session) if self.session else None,
                     "stage": "S5", "teardown_steps": steps,
                     "exit_code": exit_code,
                     "ok": exit_code == 0}, None)
        except Exception as exc:  # noqa: BLE001 - teardown failure is evidence
            return ({"grade": "mock", "channel": self.channel, "available": False,
                     "fallback_reason": "teardown failed: " + str(exc), "stage": "S5",
                     "teardown": "bridge_teardown_failed_fell_back"}, exc)
