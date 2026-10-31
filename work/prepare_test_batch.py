"""Collect existing S2 fixture receipts into one immutable intake manifest; no CAD."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'src')]
from test_batch_intake import _inside, _sha


def collect(root, entries):
    root = Path(root).resolve()
    cases = []
    seen = set()
    for executor, fixture_folder, report_name in entries:
        if not executor or executor in seen:
            raise ValueError('one receipt per executor required')
        seen.add(executor)
        folder = _inside(root, fixture_folder)
        receipt = json.loads((folder/'retest-plan.json').read_text(encoding='utf-8-sig'))
        if receipt.get('scope') != 'synthetic_fixture_only_not_production':
            raise ValueError('synthetic fixture receipt required')
        for name in ('source_sha256','code_sha256'):
            if not _sha(receipt.get(name)):
                raise ValueError('receipt missing expected '+name+'; regenerate fixture with current preparer')
        source = _inside(root, str((folder/'synthetic-s2-100x80.dxf').relative_to(root)))
        if hashlib.sha256(source.read_bytes()).hexdigest() != receipt['source_sha256']:
            raise ValueError('fixture changed since preparation')
        report = _inside(root, report_name)
        cases.append(dict(id='synthetic-S2', executor=executor,
            source=source.relative_to(root).as_posix(), report=report.relative_to(root).as_posix(),
            report_sha256=hashlib.sha256(report.read_bytes()).hexdigest(),
            source_sha256=receipt['source_sha256'], code_sha256=receipt['code_sha256'],
            parameters=receipt['parameters'], profile_index=receipt['profile_index']))
    if not cases:
        raise ValueError('at least one executor receipt required')
    return dict(schema_version=1,cases=cases)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--case',action='append',nargs=3,metavar=('EXECUTOR','FIXTURE_FOLDER','REPORT'),required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    try:
        root=a.root.resolve()
        output=a.out.resolve()
        if output.parent != root:
            raise ValueError('manifest must be directly inside --root')
        data=collect(root,a.case)
        with output.open('x',encoding='utf-8') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2,allow_nan=False)
            stream.write('\n')
        print(json.dumps(dict(status='prepared',cases=len(data['cases']),cad_executed=False)))
        return 0
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as error:
        print(json.dumps(dict(status='review_required',error=str(error),cad_executed=False)))
        return 3


if __name__=='__main__':raise SystemExit(main())
