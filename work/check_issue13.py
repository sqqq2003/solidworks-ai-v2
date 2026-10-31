"""Small offline integration checks; no SolidWorks acceptance implied."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from ql5050px.workflow import run_workflow
from project_workbench import build_command
request = json.loads((ROOT/'examples/ql5050px_integrated.json').read_text())
with tempfile.TemporaryDirectory() as temporary:
    folder = Path(temporary)/'package'
    result = run_workflow('integrated',request,output_dir=folder)
    assert result['status'] == 'pending_mapping'
    assert result['cad_executed'] is False
    assert result['windows_tasks']['native_write_allowed'] is False
    assert result['plan']['values_mm']['target_length'] == 1800
    assert result['intelligence']['database']['documents']
    assert result['machine_plan']['drawing_plan']['bom']
    manifest = json.loads((folder/'HANDOFF.json').read_text())
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((folder/name).read_bytes()).hexdigest() == digest
    with zipfile.ZipFile(folder/'gork-integrated.zip') as archive:
        assert archive.testzip() is None
    print('PASS offline end-to-end plans, pending gates and package checksums')
    try:
        run_workflow('integrated',request,output_dir=folder)
    except FileExistsError:
        print('PASS existing output rejected')
    else:
        raise AssertionError('existing output accepted')
request['manufacturing']['envelope']['length'] = 999
try:
    run_workflow('integrated',request)
except ValueError:
    print('PASS conflicting target rejected')
else:
    raise AssertionError('conflicting target accepted')
command = build_command({'kind':'ql5050px','action':'integrated','config':str(ROOT/'examples/ql5050px_integrated.json')})
assert 'integrated' in command
print('PASS desktop/batch shared command accepts integrated')
