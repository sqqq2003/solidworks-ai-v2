"""Wrap existing mapped A01 edits/drawings in the v5 byte checkpoint contract."""
from contextlib import contextmanager
import math
import os
from pathlib import Path
import uuid

from cad_checkpoint import create_checkpoint,digest_file,restore_checkpoint
from roller_variant.native import RollerDriver


class DrawingModelCheckpoint:
    # Reuse the existing native inventory and exact-owned-document recovery.
    feature_inventory=RollerDriver.feature_inventory
    body_inventory=RollerDriver.body_inventory
    assert_closed=RollerDriver.assert_closed

    def __init__(self,driver,edits,copies,root_document=None,configuration=None):
        self.driver=driver;self.lease=driver.lease;self.edits=edits
        self.copies={str(Path(k).resolve()):str(Path(v).resolve()) for k,v in copies.items()}
        self.targets=list(self.copies.values())
        if not self.targets:raise ValueError('nonempty isolated drawing dependency set required')
        for path in self.targets:driver.owned_path(path)
        self.scope=Path(os.path.commonpath([str(Path(p).parent) for p in self.targets]))
        self.scopes={(self.copies[str(Path(e['document']).resolve())],e['configuration']) for e in edits}
        if root_document is not None:self.scopes.add((str(Path(root_document).resolve()),configuration))
        self.originals={p:digest_file(p) for p in self.copies}
        self.directory=driver.root/'drawing-checkpoints'/uuid.uuid4().hex

    def guard(self):return self.driver.guard()
    def open_document(self,*args,**kwargs):return self.driver.open_document(*args,**kwargs)
    def close_document(self,model):return self.driver.close_document(model)

    def snapshot_activate_configuration(self,model,configuration):
        from src.a01_next.native_production import activate_configuration
        activate_configuration(model,configuration)

    def close_for_restore(self,targets):
        from src.ql5050px.native_machine import read_member
        app=self.guard();active=read_member(app,'ActiveDoc')
        known=list(self.driver.__dict__.get('_drawing_open_documents',{}).values())
        def same_document(a,b):
            if a is b:return True
            # PyIUnknown equality compares COM identity, rather than Python
            # wrapper id. No active-window attach or title-only adoption.
            try:
                import pythoncom
                return (a._oleobj_.QueryInterface(pythoncom.IID_IUnknown)==
                        b._oleobj_.QueryInterface(pythoncom.IID_IUnknown))
            except (AttributeError,ImportError):return False
        if active is not None and not any(same_document(active,m) for m in known):
            raise RuntimeError('ActiveDoc differs from transaction-owned documents; restore refused')
        for model in reversed(known):
            title=str(read_member(model,'GetTitle'));owned=self.lease.owned_docs.get(title)
            if owned is None or owned.handle_id!=id(model):raise RuntimeError('tracked drawing/model ownership lost')
            path=str(read_member(model,'GetPathName'))
            if path and str(Path(path).resolve()) not in targets:
                self.driver.owned_path(path)
            self.close_document(model)
        self.assert_closed(targets)

    def reopen_snapshot(self):
        from src.a01_next.native_production import activate_configuration
        from src.ql5050px.native_machine import read_member
        dimensions=[]
        for edit in self.edits:
            path=self.copies[str(Path(edit['document']).resolve())]
            model=self.open_document(path,edit['configuration'])
            try:
                activate_configuration(model,edit['configuration'])
                dimension=model.Parameter(edit['dimension'])
                if dimension is None:raise RuntimeError('checkpoint mapped dimension absent')
                value=float(read_member(dimension,'SystemValue'))
                if not math.isfinite(value):raise RuntimeError('checkpoint mapped value nonfinite')
                dimensions.append({'document':path,'configuration':edit['configuration'],
                                   'dimension':edit['dimension'],'value_si':value})
            finally:self.close_document(model)
        return {'features':self.feature_inventory(),'bodies':self.body_inventory(),'dimensions_si':dimensions}

    def create(self):
        self.assert_closed(self.targets)
        before={p:digest_file(p) for p in self.targets}
        snapshot=self.reopen_snapshot();self.assert_closed(self.targets)
        if any(digest_file(p)!=sha for p,sha in before.items()):raise RuntimeError('checkpoint native snapshot changed CAD bytes')
        return create_checkpoint(self.targets,self.directory,scope=self.scope,snapshot=snapshot,originals=self.originals)


@contextmanager
def protect_drawing_edits(driver,edits,copies,root_document=None,configuration=None):
    adapter=DrawingModelCheckpoint(driver,edits,copies,root_document,configuration)
    checkpoint=adapter.create()
    attempt=getattr(driver.lease,'durable_attempt',None)
    if attempt:
        store,key,owner=attempt
        store.update_metadata(key,owner,checkpoint={'directory':str(checkpoint.directory),
            'manifest_sha256':checkpoint.manifest_sha256,'scope':str(checkpoint.scope)},
            original_sha256=adapter.originals)
    previous=getattr(driver,'_drawing_transaction_active',False)
    driver._drawing_transaction_active=True
    try:
        yield checkpoint
    except BaseException:
        try:
            driver.last_drawing_rollback=restore_checkpoint(checkpoint,adapter)
        except Exception as error:
            driver.last_drawing_rollback={'state':'ROLLBACK_UNCONFIRMED','error':str(error),
                                          'manifest_sha256':checkpoint.manifest_sha256}
            if driver.lease is not None:driver.lease.writes_blocked=True
            if attempt:store.quarantine(key,owner,'ROLLBACK_UNCONFIRMED')
        raise
    finally:driver._drawing_transaction_active=previous
