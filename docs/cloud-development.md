# Portable development

Use Python 3.11 or 3.12, create a venv, then `python -m pip install -r requirements-cloud.txt` and `python work/run_cloud_tests.py`. GitHub Actions runs both versions on Ubuntu. No pywin32, CAD process or customer drawings are needed. Desktop GUI and actual SolidWorks validation are separate.

`python a01.py plan` returns 3 (review_required) until real dimensions, ranges, template identity and engineering approval are available. `python a01.py doctor` does not probe CAD. `python a01.py verify-baseline` returns 1/unavailable if the intentionally excluded original archive is absent. It never pretends those hashes were checked.

Default generated output is under repository `runtime/`; override via SW_AI_WORKSPACE. Do not point it at original engineering archives. Native modeling requires the serialized STA worker and exclusive lease. PID-only termination is disabled; mocks may inject a harmless killer callback. A native spawned-session/lifetime-handle implementation is still required before real writes can be qualified.

Regression coverage and its exclusions are explicit in results/cloud/latest.json. Four skips cover original source hashes, two unavailable DWG fixtures, and unavailable LibreDWG. tests/pending_features contains 36 unimplemented feature-contract cases and is NOT part of passing regression. Run `python -m unittest discover -s tests/pending_features -v` to see the missing interfaces. Do not erase or mark these passed.

A01-002B-2 next: bind a resume manifest to source content, parameters, code revision and output hash; require explicit completed/degraded status; test stale/corrupt outputs. A nonempty file alone remains unverified_existing.
