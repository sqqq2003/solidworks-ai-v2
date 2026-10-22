"""Harmless two-process lock probe; the jobs only write review marker files."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import types

parser = argparse.ArgumentParser()
parser.add_argument('--child', choices=['first', 'second'])
parser.add_argument('--folder', type=Path)
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]

if args.child:
    fake = types.ModuleType('pythoncom')
    fake.CoInitialize = lambda: None
    fake.CoUninitialize = lambda: None
    sys.modules['pythoncom'] = fake
    sys.path.insert(0, str(ROOT / 'src'))
    import sw_session

    def harmless_job():
        (args.folder / (args.child + '.entered')).write_text('pure marker, no CAD', encoding='utf-8')
        if args.child == 'first':
            deadline = time.monotonic() + 8
            while not (args.folder / 'release').exists() and time.monotonic() < deadline:
                time.sleep(0.02)

    try:
        sw_session.run_on_task_sta(harmless_job, timeout=10, task_name='pure-cross-process-probe')
        print('entered')
    except sw_session.SessionOwnershipError:
        print('refused')
    raise SystemExit(0)

folder = ROOT / 'results' / 'codex' / ('lock-probe-' + str(time.time_ns()))
folder.mkdir(parents=True)
first = subprocess.Popen([sys.executable, __file__, '--child', 'first', '--folder', str(folder)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    deadline = time.monotonic() + 5
    while not (folder / 'first.entered').exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    if not (folder / 'first.entered').exists():
        raise RuntimeError('First pure job failed to acquire its lock')
    second = subprocess.run([sys.executable, __file__, '--child', 'second', '--folder', str(folder)], capture_output=True, text=True, timeout=4)
    overlap = (folder / 'second.entered').exists()
finally:
    (folder / 'release').write_text('done', encoding='utf-8')
    out, err = first.communicate(timeout=12)
report = {'scope': 'pure-marker-jobs-only-no-CAD', 'passed': not overlap and first.returncode == 0 and second.returncode == 0 and second.stdout.strip() == 'refused',
          'overlapping_processes_entered': overlap, 'first_output': out,
          'second_output': second.stdout, 'second_stderr': second.stderr,
          'cad_started': False, 'processes_terminated': False}
(ROOT / 'results' / 'codex' / 'cross-process-lock-initial.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report))

raise SystemExit(0 if report["passed"] else 1)
