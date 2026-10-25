"""Append-only local design cases; retrieval is advice, never automatic approval."""
import json,sqlite3,time
from contextlib import contextmanager
from pathlib import Path
from design_review.impact import review_digest
from .projects import safe_relative,file_hash


@contextmanager
def connection(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path)
    db.execute('CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    try:
        with db:yield db
    finally:db.close()


def add_case(database,case,*,evidence_root=None):
    if not all(case.get(k) for k in ('title','source','source_revision','context','outcome')):raise ValueError('case provenance/context/outcome required')
    if case.get('grade') not in {'offline','native_reported','native_reviewed'}:raise ValueError('explicit evidence grade required')
    if case['grade']=='native_reviewed' and not case.get('reviewer'):raise ValueError('named native evidence reviewer required')
    for evidence in case.get('evidence',[]):
        if evidence_root is None:raise ValueError('local evidence root required')
        root=Path(evidence_root).resolve();path=(root/safe_relative(evidence['name'])).resolve()
        if not path.is_relative_to(root) or not path.is_file() or file_hash(path)!=evidence['sha256']:raise ValueError('case evidence missing/changed')
    if case['grade']!='offline' and not case.get('evidence'):raise ValueError('native case requires hashed evidence')
    payload={**case,'recorded_at':time.time()};key=review_digest(payload)
    with connection(database) as db:db.execute('INSERT INTO cases VALUES (?,?)',(key,json.dumps(payload,ensure_ascii=False,allow_nan=False)))
    return {'status':'case_recorded','id':key,'automatic_application_allowed':False}


def search_cases(database,query,context):
    words=query.casefold().split();ranked=[]
    with connection(database) as db:
        for key,raw in db.execute('SELECT id,payload FROM cases'):
            row=json.loads(raw)
            if any(context.get(k)!=v for k,v in row['context'].items()):continue
            text=json.dumps(row,ensure_ascii=False).casefold();score=sum(word in text for word in words)
            if words and not score:continue
            ranked.append({'id':key,'score':score,'case':row,'reuse_status':'review_required','automatic_application_allowed':False})
    return sorted(ranked,key=lambda x:(-x['score'],x['id']))
