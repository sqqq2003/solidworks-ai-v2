"""Cloud entrypoint: regression, adversarial boundaries, OS lock, JSON evidence."""
import ast
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
os.chdir(ROOT)
output = ROOT / 'results/cloud'
output.mkdir(parents=True, exist_ok=True)
suite = unittest.TestLoader().discover(str(ROOT / 'tests'))
suite.addTests(unittest.TestLoader().discover(str(ROOT / 'work'), pattern='test_review_session_boundaries.py'))
with (output / 'latest.log').open('w', encoding='utf-8') as log:
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
probe = subprocess.run([sys.executable, 'work/probe_writer_lock.py'], capture_output=True, text=True, timeout=35)
pending = {}
for path in (ROOT / 'tests/pending_features').glob('test_*.py'):
    pending[path.name] = sum(isinstance(node, ast.FunctionDef) and node.name.startswith('test_') for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))))
a01_parametric = {"status": "not_run"}
try:
    from src.a01_parametric.solver import solve_spec
    parametric_plan = solve_spec()
    a01_parametric = {
        "status": parametric_plan["status"],
        "envelope_mm": parametric_plan["target_envelope_mm"],
        "pending_mapping": [row["mapping_id"] for row in parametric_plan["pending_mapping"]],
        "cad_executed": False,
        "sw_live": "not_applicable_on_linux",
    }
except Exception as exc:  # reported, not hidden
    a01_parametric = {"status": "failed", "error": str(exc), "sw_live": "not_applicable_on_linux"}
report = dict(scope='portable_simulation_only', platform=platform.system(), python=platform.python_version(),
              tests_run=result.testsRun, passed=result.testsRun-len(result.errors)-len(result.failures)-len(result.skipped),
              failures=len(result.failures), errors=len(result.errors), skipped=[dict(test=str(test), reason=reason) for test, reason in result.skipped],
              pending_feature_cases=pending, cross_process_lock_passed=probe.returncode == 0,
              solidworks_live_verified=False, sw_live='not_applicable_on_linux',
              a01_parametric=a01_parametric)
from project_workbench import capabilities, doctor
report['whole_project'] = capabilities()
report['runtime_capabilities'] = doctor()
(output / 'latest.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
print(json.dumps(report, indent=2, ensure_ascii=True))
if not result.wasSuccessful():
    print((output / 'latest.log').read_text(encoding='utf-8')[-16000:])
raise SystemExit(0 if result.wasSuccessful() and probe.returncode == 0 else 1)
