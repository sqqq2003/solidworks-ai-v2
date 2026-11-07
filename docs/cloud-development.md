# Portable development

Use Python 3.11 or 3.12, create a venv, then `python -m pip install -r requirements-cloud.txt` and `python work/run_cloud_tests.py`. GitHub Actions runs both versions on Ubuntu. No pywin32, CAD process or customer drawings are needed. Desktop GUI and actual SolidWorks validation are separate.

`python a01.py plan` returns 3 (review_required) until real dimensions, ranges, template identity and engineering approval are available. `python a01.py doctor` does not probe CAD. `python a01.py verify-baseline` returns 1/unavailable if the intentionally excluded original archive is absent. It never pretends those hashes were checked.

Default generated output is under repository `runtime/`; override via SW_AI_WORKSPACE. Do not point it at original engineering archives. Native modeling requires the serialized STA worker and exclusive lease. PID-only termination is disabled; mocks may inject a harmless killer callback. A native spawned-session/lifetime-handle implementation is still required before real writes can be qualified.

Regression coverage and its exclusions are explicit in results/cloud/latest.json. Four skips cover original source hashes, two unavailable DWG fixtures, and unavailable LibreDWG. tests/pending_features contains 36 unimplemented feature-contract cases and is NOT part of passing regression. Run `python -m unittest discover -s tests/pending_features -v` to see the missing interfaces. Do not erase or mark these passed.

A01-002B-2 portable implementation now binds resume metadata to source content, all source-module hashes, geometry and generation parameters, status and artifact SHA256. Metadata is written atomically; existing CAD files are never overwritten by the resume layer. Degraded, corrupt, changed-input and unrecorded files cannot resume as passed. This verifies simulation/output provenance only, not native CAD geometry or engineering acceptance. Next: Windows acceptance of the native session owner bridge and its use with this batch flow.
