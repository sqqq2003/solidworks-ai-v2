"""I01-I08 fusion status, independent of upstream marketing/verification claims."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEMS = (
    ('I01', 'capability evidence', (), ('src/capability_registry.py',)),
    ('I02', 'geometry change evidence', ('I01',), ('src/geometry_evidence.py', 'src/native_geometry_snapshot.py')),
    ('I03', 'parameter and stable reference review', ('I02',),
     ('src/a01_parametric/register.py', 'src/parameter_ledger.py', 'src/a01_next/stable_references.py', 'src/batch_review_manifest.py')),
    ('I04', 'bounded feature operations', ('I02',), ('src/ql5050px/feature_operations.py', 'src/sw_feature_calls.py')),
    ('I05', 'drawing and PDF evidence', ('I01', 'I02'), ('src/ql5050px/drawing_verification.py', 'src/ql5050px/native_drawings.py')),
    ('I06', 'assembly and BOM review', ('I03', 'I05'),
     ('src/ql5050px/interference_audit.py', 'src/ql5050px/assembly_review.py')),
    ('I07', 'traceable portable delivery', (), ('work/build_portable.py', 'src/delivery_manifest.py')),
    ('I08', 'future structural analysis evaluation', ('I06', 'I07'), ()),
)


def integration_status(root=ROOT):
    root = Path(root)
    return {'plan_id': 'SWAI-INTEGRATION-20261026', 'items': [
        {'id': key, 'scope': scope, 'depends_on': list(deps), 'files': list(files),
         'missing_files': [f for f in files if not (root / f).is_file()],
         'implementation': 'code_present_unverified' if files and all((root / f).is_file() for f in files)
                           else 'deferred' if not files else 'incomplete',
         'simulation': 'not_run_this_batch', 'solidworks': 'unverified', 'engineering': 'unverified'}
        for key, scope, deps, files in ITEMS],
        'external_code_copied': False, 'production_approved': False,
        'note': 'Method-level integration only. File existence is not functional verification.'}
