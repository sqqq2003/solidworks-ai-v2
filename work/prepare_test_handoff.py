"""Build a checksummed source-only project test package; no customer CAD/secrets."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SUFFIXES = {'.py','.md','.json','.txt','.yml','.yaml'}
SOURCE_ROOTS = {'src':{'.py','.md'},'tests':{'.py','.json','.md'},
    'examples':{'.py','.json','.md'},'docs':{'.md'},'work':{'.py'},
    '.github':{'.yml','.yaml'}}
CONFIG_FILES = {'data/machine_spec.json','data/tasks.json','docs/ql5050px-handoff-index.json'}


def allowed_source(path):
    name = path.as_posix()
    if name in CONFIG_FILES:
        return True
    if len(path.parts)==1:
        return path.suffix=='.py' or name in {'README.md','AGENTS.md','TASK_STATUS.md',
            'requirements-cloud.txt','requirements-offline.lock.txt'}
    if path.parts[0]=='.github' and path.parts[1]!='workflows':
        return False
    return path.suffix in SOURCE_ROOTS.get(path.parts[0],set())


def collect(root):
    root = Path(root).resolve()
    # Only deliberately versioned source paths; never collect untracked files.
    names = subprocess.check_output(['git','ls-files','--cached','-z'],cwd=root).decode().split('\0')
    result = []
    for name in sorted(set(names)-{''}):
        path = Path(name)
        if (not allowed_source(path) or path.parts[0] in {'.git','runtime','results','legacy','backups'}
                or any(part.startswith('.env') or any(word in part.casefold() for word in ('secret','credential','private_key')) for part in path.parts)):
            continue
        full = root/path
        if full.is_symlink() or not full.is_file():
            continue
        result.append(path)
    return result


def build_package(root, output, revision):
    root, output = Path(root).resolve(),Path(output).resolve()
    if output.exists():
        raise FileExistsError('test package already exists; use a new path')
    files = collect(root)
    dirty = bool(subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=root).strip())
    manifest = {'schema_version':1,'revision':revision,'scope':'whole_project_source_only',
        'tracked_workspace_dirty':dirty,'untracked_files_included':False,
        'collection_policy':'tracked_source_allowlist_v2',
        'sw_live_acceptance':'pending','excluded':['customer CAD','credentials','git history','results/windows'],
        'files':{p.as_posix():hashlib.sha256((root/p).read_bytes()).hexdigest() for p in files}}
    output.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive create: never overwrite a tester's previous bundle.
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(root/path,path.as_posix())
        # Do not attach stale test statistics to a changed source snapshot.
        manifest['test_status'] = 'not_attached_requires_matching_source_revision'
        bundle.writestr('HANDOFF.json',json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
        bundle.writestr('READ-FIRST.txt',
            'SolidWorks AI V2 whole-project test bundle\n'
            '1. python work/verify_test_handoff.py .\n'
            '2. python -m pip install -r requirements-cloud.txt\n'
            '3. python work/run_cloud_tests.py\n'
            '4. python work/project.py doctor\n'
            '5. python app.py (desktop display required)\n'
            'Windows native: install pywin32 in the test virtual environment; see docs/project-testing.md.\n'
            'No original CAD, native mechanical acceptance or complete assembly/drawing engine is bundled.\n')
    return {'package':str(output),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'file_count':len(files),'revision':revision}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--revision',required=True)
    args = p.parse_args()
    print(json.dumps(build_package(ROOT,args.out,args.revision),indent=2))


if __name__ == '__main__':
    main()

