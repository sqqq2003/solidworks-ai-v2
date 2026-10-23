"""Build a checksummed source-only project test package; no customer CAD/secrets."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_SUFFIXES = {'.py','.md','.json','.txt','.yml','.yaml'}


def collect(root):
    root = Path(root).resolve()
    names = subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=root).decode().split('\0')
    result = []
    for name in sorted(set(names)-{''}):
        path = Path(name)
        if (path.suffix.casefold() not in ALLOWED_SUFFIXES or path.parts[0] in {'.git','runtime','results','legacy','backups'}
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
    manifest = {'schema_version':1,'revision':revision,'scope':'whole_project_source_only',
        'sw_live_acceptance':'pending','excluded':['customer CAD','credentials','git history','results/windows'],
        'files':{p.as_posix():hashlib.sha256((root/p).read_bytes()).hexdigest() for p in files}}
    output.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive create: never overwrite a tester's previous bundle.
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(root/path,path.as_posix())
        results = root/'results/cloud/latest.json'
        if results.is_file():
            data = results.read_bytes()
            bundle.writestr('TEST_RESULTS.json',data)
            manifest['files']['TEST_RESULTS.json'] = hashlib.sha256(data).hexdigest()
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
