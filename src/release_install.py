"""Inspect/install a checksummed source test kit into a NEW directory. Never runs it."""
import hashlib
from io import BytesIO
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile
from project_delivery import parse_json, write_new
from release_candidate import bundle_manifest
from test_handoff_audit import validate_matrix

MAX_ARCHIVE = 32 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
RESERVED = {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
OUTER_FILES = {'source.zip','candidate.json','matrix.json','submission-template.json','source-index.json','READ-FIRST.txt'}


def safe_name(name):
    if not isinstance(name,str) or not name or '\\' in name or ':' in name or '\0' in name:
        raise ValueError('invalid archive member name')
    path=PurePosixPath(name)
    if not path.parts or path.is_absolute() or '..' in path.parts or path.as_posix()!=name.rstrip('/'):
        raise ValueError('archive member path is not canonical')
    if any(part.endswith(('.', ' ')) or part.split('.')[0].upper() in RESERVED for part in path.parts):
        raise ValueError('archive member is unsafe on Windows')
    return path.as_posix()


def members(bundle):
    entries=bundle.infolist()
    if len(entries)>3000 or sum(e.file_size for e in entries)>MAX_EXPANDED:
        raise ValueError('expanded archive exceeds source-kit limits')
    seen={};result={}
    for entry in entries:
        name=safe_name(entry.filename);key=name.casefold()
        kind=stat.S_IFMT(entry.external_attr>>16)
        if kind not in {0,stat.S_IFREG,stat.S_IFDIR} or entry.flag_bits & 1:
            raise ValueError('special, symlinked or encrypted archive member refused')
        if key in seen:raise ValueError('duplicate/case-colliding archive member')
        seen[key]=not entry.is_dir()
        if entry.file_size>16*1024*1024:raise ValueError('individual source file exceeds size limit')
        if not entry.is_dir():result[name]=entry
    for name in seen:
        for parent in PurePosixPath(name).parents:
            if parent.as_posix()!='.' and seen.get(parent.as_posix()) is True:
                raise ValueError('archive file conflicts with a directory')
    return result


def load_kit(archive, expected_sha256=None):
    path=Path(archive)
    if path.stat().st_size>MAX_ARCHIVE:raise ValueError('test kit too large')
    data=path.read_bytes();actual=hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None:
        if not isinstance(expected_sha256,str) or not re.fullmatch('[0-9a-f]{64}',expected_sha256):raise ValueError('full kit SHA256 required')
        if actual!=expected_sha256:raise ValueError('test kit checksum mismatch')
    try:
        with zipfile.ZipFile(BytesIO(data)) as outer:
            top=members(outer)
            if not {'source.zip','candidate.json','matrix.json','submission-template.json'}<=set(top) or set(top)-OUTER_FILES:
                raise ValueError('unexpected/missing source-kit members')
            metadata={name:outer.read(item) for name,item in top.items() if name!='source.zip'}
            source=outer.read(top['source.zip'])
        candidate=parse_json(metadata['candidate.json'].decode('utf-8-sig'))
        if not isinstance(candidate,dict):raise ValueError('candidate metadata must be a record')
        payload=dict(candidate);identity=payload.pop('candidate_id',None)
        if candidate.get('schema_version')!=1 or hashlib.sha256(bundle_manifest(payload)).hexdigest()!=identity:
            raise ValueError('candidate identity mismatch')
        if candidate.get('source_only') is not True or candidate.get('runtime_bundled') is not False:
            raise ValueError('only source kits are supported; native runtime packages require their own installer')
        revision=candidate.get('source_revision','')
        if not re.fullmatch('[0-9a-f]{40}',revision):raise ValueError('full source revision required')
        if hashlib.sha256(source).hexdigest()!=candidate.get('package_sha256'):raise ValueError('inner source ZIP mismatch')
        matrix=parse_json(metadata['matrix.json'].decode('utf-8-sig'))
        if not isinstance(matrix,dict):raise ValueError('matrix must be a record')
        validate_matrix(matrix)
        if hashlib.sha256(bundle_manifest(matrix)).hexdigest()!=candidate.get('matrix_sha256'):
            raise ValueError('matrix checksum mismatch')
        if any(lane['sha']!=revision for lane in matrix['lanes']):raise ValueError('matrix references a different source revision')
        with zipfile.ZipFile(BytesIO(source)) as inner:
            listing=members(inner)
            handoff=parse_json(inner.read('HANDOFF.json').decode('utf-8-sig'))
            if not isinstance(handoff,dict):raise ValueError('handoff must be a record')
            files=handoff.get('files',{})
            if not isinstance(files,dict) or not files or handoff.get('revision')!=revision:
                raise ValueError('invalid source handoff manifest')
            if hashlib.sha256(bundle_manifest(handoff)).hexdigest()!=candidate.get('source_manifest_sha256'):
                raise ValueError('handoff manifest checksum mismatch')
            if type(candidate.get('file_count')) is not int or len(files)!=candidate['file_count']:
                raise ValueError('source file count mismatch')
            if set(listing)!=set(files)|{'HANDOFF.json','READ-FIRST.txt'}:
                raise ValueError('unlisted or missing source payload')
            contents={}
            for name,digest in files.items():
                safe_name(name)
                body=inner.read(name)
                if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest) or hashlib.sha256(body).hexdigest()!=digest:
                    raise ValueError('source file checksum mismatch: '+name)
                contents[name]=body
            for name in ('HANDOFF.json','READ-FIRST.txt'):contents[name]=inner.read(name)
        if 'source-index.json' in metadata:
            index=parse_json(metadata['source-index.json'].decode('utf-8-sig'))
            if not isinstance(index,dict):raise ValueError('source index must be a record')
            if index.get('schema_version')!=1 or index.get('source_revision')!=revision:raise ValueError('source index revision mismatch')
            for name in files:
                body=contents[name]
                digest=hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest()
                if index.get('files',{}).get(name)!=digest:raise ValueError('pinned Git blob mismatch: '+name)
    except (zipfile.BadZipFile,KeyError,UnicodeError) as exc:
        raise ValueError('invalid or incomplete source kit: '+str(exc)) from exc
    metadata['source.zip']=source
    report={'schema_version':1,'status':'passed' if expected_sha256 else 'review_required',
            'scope':'source_kit_integrity_only','kit_sha256':actual,'source_revision':revision,
            'candidate_id':identity,'source_files':len(files),'external_checksum_verified':expected_sha256 is not None,
            'runtime_bundled':False,'cad_executed':False,'manufacturing_approved':False}
    return report,metadata,contents


def inspect_kit(archive, *, expected_sha256=None):
    return load_kit(archive,expected_sha256)[0]


def install_kit(archive, destination, *, expected_sha256):
    if not expected_sha256:raise ValueError('installation requires the kit SHA256 from the published receipt')
    report,metadata,contents=load_kit(archive,expected_sha256)
    root=Path(destination).expanduser().resolve()
    root.mkdir(parents=True,exist_ok=False)
    app=root/'app';app.mkdir();meta=root/'candidate';meta.mkdir()
    try:
        for base,rows in ((app,contents),(meta,metadata)):
            for name,body in rows.items():
                target=base/name;target.parent.mkdir(parents=True,exist_ok=True)
                if not target.resolve().is_relative_to(base):raise ValueError('installation path escaped its new directory')
                with target.open('xb') as stream:stream.write(body)
                if hashlib.sha256(target.read_bytes()).hexdigest()!=hashlib.sha256(body).hexdigest():
                    raise ValueError('installed file readback mismatch')
        result={**report,'status':'review_required','phase':'source_installed_runtime_required',
                'directory':str(root),'app_directory':str(app),'files_written':len(contents),
                'next_steps':['Create a new Python environment and install app/requirements-cloud.txt.',
                              'Run python work/verify_test_handoff.py . inside app.',
                              'Run python app.py; native work still requires explicit Windows review.'],
                'original_installation_modified':False,'code_executed':False}
        write_new(root/'installation.json',result)
        return result
    except Exception as exc:
        try:write_new(root/'INSTALLATION-INCOMPLETE.json',{'status':'failed','error':str(exc),'code_executed':False})
        except OSError:pass
        raise
