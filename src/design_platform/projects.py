"""Local immutable project revisions and restore-to-new-directory only."""
from pathlib import Path,PurePosixPath,PureWindowsPath
import hashlib,json,shutil,time,uuid
from design_review.impact import review_digest


def safe_relative(name):
    if not isinstance(name,str) or not name or PurePosixPath(name).root or PureWindowsPath(name).root or PureWindowsPath(name).drive or '\\' in name or '..' in PurePosixPath(name).parts:raise ValueError('portable relative artifact name required')
    return name


def file_hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def read_revision(store,revision):
    safe_relative(revision)
    if '/' in revision:raise ValueError('revision must be a single identifier')
    folder=(Path(store).resolve()/revision).resolve()
    if not folder.is_relative_to(Path(store).resolve()):raise ValueError('external revision refused')
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    identity=manifest.pop('revision_id')
    if identity!=review_digest(manifest) or revision!='rev-'+identity:raise ValueError('revision manifest changed')
    manifest['revision_id']=identity
    for name,checksum in manifest['files'].items():
        p=(folder/'files'/safe_relative(name)).resolve()
        if not p.is_relative_to(folder/'files') or not p.is_file() or file_hash(p)!=checksum:raise ValueError('revision artifact missing/changed: '+name)
    return folder,manifest


def commit_revision(store,files,metadata,*,parent=None):
    root=Path(store).resolve();root.mkdir(parents=True,exist_ok=True)
    if parent:read_revision(root,parent)
    if not all(metadata.get(k) for k in ('project','source_revision','parameter_source')):raise ValueError('project/code/parameter provenance required')
    stage=root/('.staging-'+uuid.uuid4().hex);(stage/'files').mkdir(parents=True)
    inventory={}
    try:
        for name,source in files.items():
            safe_relative(name);source=Path(source).resolve()
            if not source.is_file():raise FileNotFoundError(source)
            target=stage/'files'/name;target.parent.mkdir(parents=True,exist_ok=True)
            before=file_hash(source);shutil.copy2(source,target)
            if file_hash(target)!=before or file_hash(source)!=before:raise ValueError('source changed during revision capture')
            inventory[name]=before
        manifest={'schema_version':1,'parent':parent,'metadata':metadata,'created_at':time.time(),'files':inventory}
        manifest['revision_id']=review_digest(manifest)
        (stage/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        final=root/('rev-'+manifest['revision_id'])
        if final.exists():raise FileExistsError(final)
        stage.rename(final)
        return {'status':'revision_saved','revision':final.name,'files':inventory,'source_modified':False}
    except Exception:
        # Only this function's unique staging directory is removed.
        shutil.rmtree(stage);raise


def restore_revision(store,revision,destination):
    folder,manifest=read_revision(store,revision)
    out=Path(destination).resolve();out.mkdir(parents=True,exist_ok=False)
    for name,checksum in manifest['files'].items():
        path=out/safe_relative(name);path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(folder/'files'/name,path)
        if file_hash(path)!=checksum:raise RuntimeError('restored artifact hash mismatch')
    return {'status':'restored_to_new_directory','directory':str(out),'revision':revision,'originals_overwritten':False}


def history(store):
    return [read_revision(store,p.name)[1] for p in sorted(Path(store).glob('rev-*')) if p.is_dir()]
