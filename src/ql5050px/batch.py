"""Single-writer, resumable dependency queue for offline and future native jobs."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
from datetime import datetime, timezone


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)


def digest(path):
    with Path(path).open("rb") as stream:
        h = hashlib.sha256()
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def order_jobs(jobs):
    catalog = {}
    for job in jobs:
        name = job["id"]
        if not isinstance(name,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}",name) or name in catalog:
            raise ValueError("unique safe job ids required")
        catalog[name] = job
    result,visiting,done = [],set(),set()
    def visit(name):
        if name not in catalog:
            raise ValueError(f"missing dependency: {name}")
        if name in visiting:
            raise ValueError("job dependency cycle")
        if name in done:
            return
        visiting.add(name)
        for dep in catalog[name].get("depends_on",[]):
            visit(dep)
        visiting.remove(name)
        done.add(name)
        result.append(catalog[name])
    for name in catalog:
        visit(name)
    return result


def resolve(payload, results, allowed):
    if isinstance(payload,dict):
        if set(payload)=={"$ref"}:
            path = payload["$ref"].split(".")
            if path[0] not in allowed:
                raise ValueError("result references require explicit depends_on")
            value = results[path[0]]["value"]
            for key in path[1:]:
                value = value[int(key)] if isinstance(value,list) else value[key]
            return deepcopy(value)
        return {k:resolve(v,results,allowed) for k,v in payload.items()}
    if isinstance(payload,list):
        return [resolve(v,results,allowed) for v in payload]
    return payload


@contextmanager
def writer(root):
    lock = root/".writer.lock"
    fd = os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        os.write(fd,canonical({"pid":os.getpid(),"started":datetime.now(timezone.utc).isoformat()}).encode())
        yield
    finally:
        os.close(fd)
        lock.unlink()


class BatchRunner:
    """Handlers (payload, new_attempt_dir) -> JSON result; native kinds opt in.

    Every successful result and its output files are hashed before journaling.
    Resume reuses only completed, unchanged artifacts. Failures/blocked jobs
    get another attempt directory. Existing outputs are never overwritten.
    """
    def __init__(self, handlers, *, version="ql5050px-batch-v2", native_kinds=()):
        self.handlers = dict(handlers)
        self.version = version
        self.native_kinds = set(native_kinds)

    def run(self, jobs, destination, *, resume=False, allow_native=False):
        ordered = order_jobs(jobs)
        root = Path(destination).resolve()
        if resume:
            if not root.is_dir():
                raise ValueError("resume directory missing")
        else:
            root.mkdir(parents=True,exist_ok=False)
        specification = {"version":self.version,"jobs":jobs,"allow_native":allow_native}
        with writer(root):
            config = root/"pipeline.json"
            if resume:
                if json.loads(config.read_text(encoding="utf-8"))!=specification:
                    raise ValueError("resume pipeline differs; use new output directory")
            else:
                with config.open("x",encoding="utf-8") as stream:
                    stream.write(canonical(specification))
            history = {}
            journal = root/"journal.jsonl"
            if journal.exists():
                for line in journal.read_text(encoding="utf-8").splitlines():
                    row = json.loads(line)
                    history[row["id"]] = row
            results = {}
            for job in ordered:
                name = job["id"]
                deps = job.get("depends_on",[])
                old = history.get(name)
                reusable = old and old["status"]=="completed"
                if reusable:
                    if old.get("kind") != job["kind"]:
                        raise ValueError(f"resume job kind mismatch: {name}")
                    artifacts = old.get("artifacts")
                    if not isinstance(artifacts,dict) or not artifacts:
                        raise ValueError(f"resume result artifact missing: {name}")
                    result_files = []
                    for relative,sha in artifacts.items():
                        artifact = (root/relative).resolve()
                        if not artifact.is_relative_to(root) or not artifact.is_file() or digest(artifact)!=sha:
                            raise ValueError(f"resume artifact missing or changed: {relative}")
                        parts = Path(relative).parts
                        if (len(parts)==3 and parts[0]==name and
                                re.fullmatch(r"attempt-[1-9][0-9]*",parts[1]) and parts[2]=="result.json"):
                            result_files.append(artifact)
                    if len(result_files)!=1:
                        raise ValueError(f"resume result artifact ambiguous or missing: {name}")
                    value = json.loads(result_files[0].read_text(encoding="utf-8"))
                    if canonical(value)!=canonical(old.get("value")):
                        raise ValueError(f"resume result value differs from hashed artifact: {name}")
                    results[name] = old
                    continue
                result = {"id":name,"kind":job["kind"],"status":"blocked","artifacts":{}}
                if any(results[d]["status"]!="completed" for d in deps):
                    result["reason"] = "dependency not completed"
                elif job["kind"] in self.native_kinds and not allow_native:
                    result.update(status="pending_native",reason="native execution disabled")
                else:
                    attempt = 1
                    folder = root/name/f"attempt-{attempt}"
                    while folder.exists():
                        attempt+=1
                        folder = root/name/f"attempt-{attempt}"
                    folder.mkdir(parents=True)
                    try:
                        if job["kind"] not in self.handlers:
                            raise ValueError("unregistered job kind")
                        payload = resolve(job.get("payload",{}),results,set(deps))
                        value = self.handlers[job["kind"]](payload,folder)
                        with (folder/"result.json").open("x",encoding="utf-8") as stream:
                            stream.write(canonical(value))
                        artifacts = {}
                        for artifact in folder.rglob("*"):
                            if artifact.is_symlink():
                                raise ValueError("symlink outputs unsupported")
                            if artifact.is_file():
                                artifacts[str(artifact.relative_to(root))] = digest(artifact)
                        result.update(status="completed",value=value,artifacts=artifacts)
                    except Exception as exc:
                        result.update(status="failed",error_type=type(exc).__name__,error=str(exc))
                result["recorded_at"] = datetime.now(timezone.utc).isoformat()
                with journal.open("a",encoding="utf-8") as stream:
                    stream.write(canonical(result)+"\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                results[name] = result
            counts = {s:sum(r["status"]==s for r in results.values()) for s in ("completed","failed","blocked","pending_native")}
            return {"jobs":results,"counts":counts,"test_status":"not_run","native_acceptance":"unverified"}

