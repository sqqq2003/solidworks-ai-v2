"""Mock tests for the C# bridge contract (Issue #25).

Run on Linux with:  python3 -m unittest discover -s tests -v
(from the csharp-bridge directory, with python/ on sys.path -- see README.)

Mock success is never native acceptance: every Windows behaviour tested
here (COM release order, ExitApp, exit codes) is pending_windows_validation
until Gork runs the acceptance matrix in INTEGRATION.md.
"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from bridge_client import (
    PROTOCOL_VERSION,
    TEARDOWN_STEPS,
    UNITS,
    BendParameters,
    BridgeClient,
    BridgeTimeoutError,
    MissingParameterError,
    MockTransport,
    OwnershipError,
    checkpoint_record,
    m_to_mm,
    make_request,
    mm_to_m,
    validate_double_array,
)


class TestContractMessages(unittest.TestCase):
    def test_request_carries_protocol_id_and_units(self):
        req = make_request("hello")
        self.assertEqual(req["protocol"], PROTOCOL_VERSION)
        self.assertTrue(req["id"])
        self.assertEqual(req["units"], "mm")

    def test_hello_roundtrip(self):
        client = BridgeClient(MockTransport())
        result = client.call("hello")
        self.assertEqual(result["protocol"], PROTOCOL_VERSION)


class TestUnits(unittest.TestCase):
    def test_mm_m_roundtrip(self):
        self.assertAlmostEqual(m_to_mm(mm_to_m(1234.5)), 1234.5)
        self.assertAlmostEqual(mm_to_m(1000.0), 1.0)
        self.assertEqual(UNITS, "mm")


class TestArrays(unittest.TestCase):
    def test_point_roundtrip_3(self):
        client = BridgeClient(MockTransport())
        point = [1.0, 2.5, -3.25]
        result = client.call("echo_point", {"point": point})
        self.assertEqual(result["point"], point)

    def test_transform_roundtrip_16(self):
        client = BridgeClient(MockTransport())
        transform = [1.0 if i % 5 == 0 else 0.0 for i in range(16)]
        result = client.call("echo_transform", {"transform": transform})
        self.assertEqual(result["transform"], transform)

    def test_array_wrong_length_rejected(self):
        with self.assertRaises(ValueError):
            validate_double_array([1.0, 2.0], 3)
        with self.assertRaises(ValueError):
            validate_double_array([1.0] * 15 + [float("nan")], 16)


class TestTimeoutAndExitCode(unittest.TestCase):
    def test_slow_bridge_times_out(self):
        client = BridgeClient(MockTransport(slow_s=0.2), timeout_s=0.05)
        with self.assertRaises(BridgeTimeoutError):
            client.call("hello")

    def test_exit_code_recorded_zero_and_nonzero(self):
        ok_client = BridgeClient(MockTransport(exit_code=0))
        report = ok_client.teardown()
        self.assertEqual(report["exit_code"], 0)
        bad_client = BridgeClient(MockTransport(exit_code=-1073741819))
        report = bad_client.teardown()
        # 0xC0000005 as signed int32: recorded distinctly, never assumed 0.
        self.assertEqual(report["exit_code"], -1073741819)


class TestNoDefaults(unittest.TestCase):
    """t / R / K are per-job inputs. Missing input -> pending, never a default.

    The factory numbers below appear ONLY in test_factory_case_labelled,
    explicitly labelled as one measured case, never as module defaults.
    """

    def test_missing_thickness_raises_pending(self):
        params = BendParameters(radius_mm=1.0, angle_degrees=90.0, k_factor=0.36)
        with self.assertRaises(MissingParameterError) as ctx:
            params.validate()
        self.assertEqual(ctx.exception.status, "pending_confirmation")
        self.assertIn("thickness_mm", ctx.exception.missing)

    def test_missing_k_factor_raises_pending(self):
        params = BendParameters(thickness_mm=2.5, radius_mm=1.0, angle_degrees=90.0)
        with self.assertRaises(MissingParameterError) as ctx:
            params.validate()
        self.assertEqual(ctx.exception.status, "pending_confirmation")
        self.assertIn("k_factor", ctx.exception.missing)

    def test_module_has_no_numeric_defaults(self):
        import bridge_client
        for name in ("DEFAULT_T", "DEFAULT_K", "DEFAULT_THICKNESS", "DEFAULT_K_FACTOR"):
            self.assertFalse(
                hasattr(bridge_client, name), f"forbidden default constant {name}"
            )

    def test_factory_case_labelled_not_default(self):
        # ONE factory measured case (2026-10-22 symmetric U-channel),
        # used ONLY to back-verify the formula chain. NOT a default.
        params = BendParameters(
            thickness_mm=2.5, radius_mm=1.0, angle_degrees=90.0, k_factor=0.36
        )
        self.assertAlmostEqual(params.bend_allowance_mm(), 2.9845, places=3)
        self.assertAlmostEqual(params.bend_deduction_mm(), 4.0155, places=3)
        # Nominal shop values BA=3.0 / BD=4.0 are the above rounded to 0.1/0.01.
        self.assertAlmostEqual(params.bend_allowance_mm(), 3.0, places=1)
        self.assertAlmostEqual(params.bend_deduction_mm(), 4.0, places=1)


class TestFormulaChainParameterized(unittest.TestCase):
    """BA/BD chain + K back-derivation, across NON-factory parameter sets.

    Proves t / R / K flow as parameters: the same code path handles every
    job's inputs, and K derived back from a measured BD matches the input K.
    """

    CASES = [
        (1.5, 1.0, 90.0, 0.44),
        (3.0, 2.0, 90.0, 0.40),
        (2.0, 1.5, 120.0, 0.33),
        (0.8, 0.8, 90.0, 0.50),
    ]

    def test_chain_roundtrips(self):
        for t, radius, angle, k in self.CASES:
            with self.subTest(t=t, radius=radius, angle=angle, k=k):
                params = BendParameters(
                    thickness_mm=t, radius_mm=radius,
                    angle_degrees=angle, k_factor=k,
                )
                bd = params.bend_deduction_mm()
                derived = params.k_factor_from_bend_deduction(bd)
                self.assertTrue(math.isclose(derived, k, abs_tol=1e-9))
                # BD method: flat = outside legs - BD, per bend.
                self.assertAlmostEqual(
                    params.flat_length_mm(38.0, 48.0), 38.0 + 48.0 - bd
                )


class TestOwnershipAndTeardown(unittest.TestCase):
    def test_foreign_title_close_refused(self):
        client = BridgeClient(MockTransport())
        with self.assertRaises(OwnershipError):
            client.call("close_document", {"title": "someone-else.SLDPRT"})

    def test_teardown_step_order(self):
        transport = MockTransport(pid=777)
        client = BridgeClient(transport, pid=777)
        client.call("create_empty_document", {"title": "job.SLDPRT"})
        report = client.teardown(owned_titles=["job.SLDPRT"])
        order = [s["event"] for s in report["steps"]]
        self.assertEqual(order, list(TEARDOWN_STEPS))
        self.assertEqual(report["exit_code"], 0)

    def test_teardown_refuses_with_open_documents(self):
        client = BridgeClient(MockTransport())
        client.call("create_empty_document", {"title": "job.SLDPRT"})
        # teardown() called without listing the owned title: list_titles
        # still shows it open, so teardown must refuse, not ExitApp.
        with self.assertRaises(OwnershipError):
            client.teardown(owned_titles=[])


class TestCheckpointRecord(unittest.TestCase):
    def test_checkpoint_shape(self):
        record = checkpoint_record("S2", "plan-abc", {"rebuilt": True})
        self.assertEqual(record["checkpoint"], "ckpt-S2.json")
        self.assertEqual(record["plan_id"], "plan-abc")
        self.assertEqual(len(record["evidence_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
