"""One callable batch in P0/P1/P2 order; each module failure is retained."""
import json
import hashlib
from pathlib import Path
from .dimensions import solve_chain, tolerance_stack
from .assembly import diagnose_assembly
from .changes import track_changes, change_report
from .review import review_design
from .transmission import transmission
from .weldments import plan_frame
from .costs import estimate_cost
from .similarity import find_similar
from .proposals import compare_proposals, instruction_request
from .common import review_digest
from .native_review import prepare_native_review

MODULES = {
    'dimensions': (0, solve_chain), 'assembly': (0, diagnose_assembly),
    'changes': (0, track_changes), 'tolerances': (0, tolerance_stack), 'review': (0, review_design),
    'transmission': (1, transmission), 'weldments': (1, plan_frame), 'costs': (1, estimate_cost),
    'similarity': (1, find_similar), 'change_report': (1, change_report),
    'proposals': (2, compare_proposals), 'instruction': (2, instruction_request)}


def run_module(name, request):
    if name not in MODULES: raise ValueError('unknown engineering module: '+name)
    return MODULES[name][1](request)


def build_batch(request, destination=None):
    unknown=set(request['modules'])-MODULES.keys()
    if unknown: raise ValueError('unknown modules: '+str(sorted(unknown)))
    reports={}
    for name, (_, operation) in MODULES.items():
        if name not in request['modules']: continue
        try: reports[name]=operation(request['modules'][name])
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            reports[name]={'status':'failed','error':type(exc).__name__+': '+str(exc),'native_status':'not_run'}
    states=[r['status'] for r in reports.values()]
    status='failed' if 'failed' in states else 'review_required' if not states or 'review_required' in states else 'degraded' if 'degraded' in states else 'passed'
    report={'schema_version':1,'status':status,'modules':reports,'request_sha256':review_digest(request),
            'scope':'offline_engineering_core_only','cad_executed':False,'manufacturing_approved':False,
            'native_status':'pending_windows_validation'}
    if destination is not None:
        root=Path(destination);root.mkdir(parents=True,exist_ok=False)
        files={}
        for name,data in [('request.json',request),('engineering-result.json',report)]:
            content=json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')
            (root/name).write_bytes(content); files[name]=hashlib.sha256(content).hexdigest()
        source=Path(__file__).parent
        reused=source.parent
        code={str(p.relative_to(reused)):hashlib.sha256(p.read_bytes()).hexdigest()
              for folder in (source,reused/'design_review',reused/'design_platform',reused/'ql5050px')
              for p in sorted(folder.glob('*.py'))}
        (root/'HANDOFF.json').write_text(json.dumps({'schema_version':1,'files':files,'code_sha256':code,
                    'source_revision':request.get('source_revision','unrecorded'),
                    'native_status':'not_run','original_files_modified':False},indent=2),encoding='utf-8')
    return report
