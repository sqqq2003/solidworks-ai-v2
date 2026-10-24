"""Python-side client for the C# SolidWorks bridge (Issue #25).

Transport contract: JSON messages, one request / one response.
The C# side owns the SolidWorks COM apartment; this module never imports
win32com and never touches SolidWorks directly. On Linux it runs against
MockTransport only. Mock success is never native acceptance.

Units rule (hard): every length in bridge messages is millimetres, every
angle is degrees, and every message carries ``units: "mm"`` explicitly.
Conversion helpers are explicit; no silent unit coercion anywhere.

Parameter rule (hard, user-corrected 2026-10-24): plate thickness ``t``,
inner radius ``R`` and K factor are PER-JOB inputs. They are never
constants and never defaulted. Missing any of them raises
MissingParameterError with status ``pending_confirmation``. The often
quoted t=2.5 / R=1 / K=0.36 / BA=3.0 / BD=4.0 set is ONE factory measured
case (2026-10-22 symmetric U-channel, used to back-verify the formulas),
NOT a default; it appears only in tests/docs labelled as such.

Teardown order (hard, mirrors Issue #19 / PR #23):
    close_documents -> enumerate_titles -> exit_app
    -> release_wrappers -> process_exit
COM wrappers are released in reverse acquisition order, and only after
ExitApp has returned. The process exit code is recorded, never assumed 0.
Windows behaviour of this module is pending_windows_validation.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid

PROTOCOL_VERSION = "sw-bridge/1"
UNITS = "mm"

# Teardown step order. Do not reorder: ExitApp needs a live app wrapper,
# wrappers are released only after ExitApp returns.
TEARDOWN_STEPS = (
    "close_documents",
    "enumerate_titles",
    "exit_app",
    "release_wrappers",
    "process_exit",
)


class BridgeError(Exception):
    """Base bridge error; ``status`` feeds the caller's pending handling."""


class MissingParameterError(BridgeError):
    """A per-job input is missing. Status is pending_confirmation, never a default."""

    status = "pending_confirmation"

    def __init__(self, missing):
        self.missing = list(missing)
        super().__init__(
            "missing per-job parameters (pending_confirmation, no defaults applied): "
            + ", ".join(self.missing)
        )


class BridgeTimeoutError(BridgeError):
    """A bridge request exceeded its timeout."""


class OwnershipError(BridgeError):
    """Refusal to act on a document this task cannot prove it owns."""


def mm_to_m(value_mm):
    """Millimetres -> metres. Explicit conversion; never implicit."""
    if not math.isfinite(value_mm):
        raise ValueError("length must be finite")
    return value_mm / 1000.0


def m_to_mm(value_m):
    """Metres -> millimetres. Explicit conversion; never implicit."""
    if not math.isfinite(value_m):
        raise ValueError("length must be finite")
    return value_m * 1000.0


def validate_double_array(values, length):
    """Validate a finite double array of exact length.

    Mirrors the semantics of ``sw_math_arrays.double_array`` (PR #20) on the
    Python side without importing win32com: VT_ARRAY|VT_R8 marshalling itself
    lives on the C# side / in sw_math_arrays.py for the Python-COM path.
    """
    values = tuple(values)
    if len(values) != length or any(
        type(v) not in (int, float) or not math.isfinite(v) for v in values
    ):
        raise ValueError(f"finite double array of length {length} required")
    return tuple(float(v) for v in values)


class BendParameters:
    """Per-job bend inputs. All four are required; None means 'not provided'.

    There are intentionally NO numeric defaults on this class. A caller that
    forgets thickness, radius, angle or K factor gets MissingParameterError,
    not a shop number silently filled in.
    """

    def __init__(self, *, thickness_mm=None, radius_mm=None,
                 angle_degrees=None, k_factor=None):
        self.thickness_mm = thickness_mm
        self.radius_mm = radius_mm
        self.angle_degrees = angle_degrees
        self.k_factor = k_factor

    def validate(self):
        missing = [
            name for name in
            ("thickness_mm", "radius_mm", "angle_degrees", "k_factor")
            if getattr(self, name) is None
        ]
        if missing:
            raise MissingParameterError(missing)
        if not math.isfinite(self.thickness_mm) or self.thickness_mm <= 0:
            raise ValueError("thickness_mm must be positive")
        if not math.isfinite(self.radius_mm) or self.radius_mm < 0:
            raise ValueError("radius_mm must be non-negative")
        if not math.isfinite(self.angle_degrees) or not 0 < self.angle_degrees < 180:
            raise ValueError("angle_degrees must be between 0 and 180")
        if not math.isfinite(self.k_factor) or not 0 <= self.k_factor <= 1:
            raise ValueError("k_factor must be between 0 and 1")
        return self

    def bend_allowance_mm(self):
        """BA = theta_rad * (R + K*t). Canonical implementation lives in
        src/bend_allowance.py; this local copy keeps the bridge directory
        self-contained for mock tests and must match it."""
        self.validate()
        return math.radians(self.angle_degrees) * (
            self.radius_mm + self.k_factor * self.thickness_mm
        )

    def bend_deduction_mm(self):
        """BD = 2*OSSB - BA, OSSB = (R + t)*tan(theta/2)."""
        self.validate()
        ossb = (self.radius_mm + self.thickness_mm) * math.tan(
            math.radians(self.angle_degrees) / 2.0
        )
        return 2.0 * ossb - self.bend_allowance_mm()

    def flat_length_mm(self, leg1_mm, leg2_mm):
        """Flat length from two outside legs measured to the virtual sharp:
        L = leg1 + leg2 - BD."""
        return leg1_mm + leg2_mm - self.bend_deduction_mm()

    def k_factor_from_bend_deduction(self, bend_deduction_mm):
        """Back-derive K from a measured bend deduction (shop unfold data):
        BD = 2*OSSB - theta*(R + K*t)  =>  K = ((2*OSSB - BD)/theta - R)/t."""
        self.validate()
        theta = math.radians(self.angle_degrees)
        ossb = (self.radius_mm + self.thickness_mm) * math.tan(theta / 2.0)
        return ((2.0 * ossb - bend_deduction_mm) / theta - self.radius_mm) / self.thickness_mm


def make_request(method, params=None):
    """Build a contract request. Every request carries protocol, id, units."""
    return {
        "protocol": PROTOCOL_VERSION,
        "id": uuid.uuid4().hex,
        "method": method,
        "units": UNITS,
        "params": params or {},
    }


def checkpoint_record(stage, plan_id, evidence):
    """Build a PR #23-compatible checkpoint record (not a file write).

    Shape mirrors run_recovery.write_checkpoint: stage, plan_id, timestamp,
    evidence sha256, evidence summary. The caller decides where to persist it.
    """
    blob = json.dumps(evidence, sort_keys=True, default=str).encode()
    return {
        "checkpoint": f"ckpt-{stage}.json",
        "stage": stage,
        "plan_id": plan_id,
        "timestamp": time.time(),
        "evidence_sha256": hashlib.sha256(blob).hexdigest(),
        "evidence": evidence,
    }


class MockTransport:
    """In-process stand-in for the C# bridge. Linux-safe, no SolidWorks.

    Simulates: hello, spawn, create_empty_document, close_document,
    list_titles, echo_point, echo_transform, exit_app, teardown_report.
    Ownership is enforced: closing a title this task does not own fails.
    ``slow_s`` simulates a hung bridge for timeout tests; ``exit_code``
    lets tests verify nonzero exit codes are recorded, not assumed 0.
    """

    def __init__(self, *, slow_s=0.0, exit_code=0, pid=424242):
        self.slow_s = slow_s
        self.exit_code = exit_code
        self.pid = pid
        self.owned_titles = set()
        self.released_wrappers = []
        self.acquired_wrappers = []

    def handle(self, request):
        if self.slow_s:
            time.sleep(self.slow_s)
        method = request["method"]
        params = request.get("params", {})
        if request.get("units") != UNITS:
            return self._error(request, "units must be 'mm'")
        if method == "hello":
            return self._ok(request, {"bridge": "mock", "protocol": PROTOCOL_VERSION})
        if method == "spawn":
            return self._ok(request, {"pid": self.pid, "owned": True})
        if method == "create_empty_document":
            title = params.get("title", "mock-part.SLDPRT")
            self.owned_titles.add(title)
            self.acquired_wrappers.append("model:" + title)
            return self._ok(request, {"title": title, "owned": True})
        if method == "close_document":
            title = params.get("title")
            if title not in self.owned_titles:
                return self._error(request, f"refusing to close unowned document {title!r}")
            self.owned_titles.discard(title)
            return self._ok(request, {"title": title, "closed": True})
        if method == "list_titles":
            return self._ok(request, {"titles": sorted(self.owned_titles)})
        if method == "echo_point":
            values = validate_double_array(params["point"], 3)
            return self._ok(request, {"point": list(values)})
        if method == "echo_transform":
            values = validate_double_array(params["transform"], 16)
            return self._ok(request, {"transform": list(values)})
        if method == "exit_app":
            if self.owned_titles:
                return self._error(
                    request,
                    "refusing ExitApp while owned documents remain: "
                    + ", ".join(sorted(self.owned_titles)),
                )
            return self._ok(request, {"exit_requested": True})
        if method == "teardown_report":
            return self._ok(request, {"exit_code": self.exit_code})
        return self._error(request, f"unknown method {method!r}")

    def _ok(self, request, result):
        return {"protocol": PROTOCOL_VERSION, "id": request["id"],
                "ok": True, "result": result}

    def _error(self, request, message):
        return {"protocol": PROTOCOL_VERSION, "id": request["id"],
                "ok": False, "error": message}


class BridgeClient:
    """Client over a transport exposing ``handle(request) -> response``.

    The real transport is a named-pipe JSON-lines channel to the C# bridge
    (see csharp-bridge/src/SwBridge.cs); MockTransport covers Linux tests.
    """

    def __init__(self, transport, *, timeout_s=30.0, pid=None):
        self.transport = transport
        self.timeout_s = timeout_s
        self.pid = pid

    def call(self, method, params=None):
        request = make_request(method, params)
        started = time.monotonic()
        response = self.transport.handle(request)
        elapsed_ms = (time.monotonic() - started) * 1000.0
        if elapsed_ms > self.timeout_s * 1000.0:
            raise BridgeTimeoutError(
                f"bridge request {method} exceeded {self.timeout_s}s"
            )
        if not response.get("ok"):
            message = response.get("error", "bridge error")
            if "unowned" in message:
                raise OwnershipError(message)
            raise BridgeError(message)
        return response["result"]

    def teardown(self, *, owned_titles=()):
        """Run the 5-step teardown in order and record every step.

        Returns a report whose ``steps`` list is in TEARDOWN_STEPS order and
        whose ``exit_code`` is the recorded process exit code (int, possibly
        nonzero). The caller persists it; nothing here assumes exit 0.
        """
        steps = []
        started = time.monotonic()

        def record(step, owned_docs, extra=None):
            entry = {
                "stage": "S5",
                "event": step,
                "owned_docs": list(owned_docs),
                "pid": self.pid,
                "elapsed_ms": round((time.monotonic() - started) * 1000.0, 3),
            }
            if extra:
                entry.update(extra)
            steps.append(entry)
            return entry

        remaining = list(owned_titles)
        for title in list(remaining):
            self.call("close_document", {"title": title})
            remaining.remove(title)
        record("close_documents", remaining)
        titles = self.call("list_titles")
        record("enumerate_titles", titles["titles"])
        if titles["titles"]:
            raise OwnershipError(
                "teardown refused: documents remain open: "
                + ", ".join(titles["titles"])
            )
        self.call("exit_app")
        record("exit_app", [])
        # Release wrappers in reverse acquisition order, after ExitApp.
        released = list(reversed(getattr(self.transport, "acquired_wrappers", [])))
        record("release_wrappers", [], {"released": released})
        report = self.call("teardown_report")
        exit_code = report["exit_code"]
        record("process_exit", [], {"exit_code": exit_code})
        order = [s["event"] for s in steps]
        assert order == list(TEARDOWN_STEPS), f"teardown step order violated: {order}"
        return {"steps": steps, "exit_code": exit_code}
