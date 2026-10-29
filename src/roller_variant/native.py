"""Reuse guarded native machine Pack-and-Go, document and session services."""
import hashlib,math,sys
from pathlib import Path
from sw_api.mapping import load_mappings
from ql5050px.native_machine import NativeMachineDriver,read_member
from .execution import execute_variant


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


class RollerDriver(NativeMachineDriver):
    simulated=False
    def guard(self):
        app=super().guard()
        if not getattr(self,'_bound_once',False):
            self.lease.note_bound_application(app);self._bound_once=True
        return app
    def isolate(self,request,destination):
        self.request=request;self.rows=load_mappings(request['mappings'])
        self.original_hashes={str(Path(p).resolve()):sha(p) for p in {request['source_document'],*(r.document for r in self.rows)}}
        self.source=self.pack_and_go(request['source_document'],destination,request['configuration'])
        self.copies=self.receipt['events'][-1]['copies']
        if not set(self.original_hashes)<=set(self.copies):raise ValueError('mapping document outside isolated roller dependency set')
        self.scopes={(self.copies[str(Path(r.document).resolve())],r.configuration) for r in self.rows}
        self.scopes.add((self.source,request['configuration']))
    def read_all(self):
        values={}
        for row in self.rows:
            model=self.open_document(self.copies[str(Path(row.document).resolve())],row.configuration)
            try:
                if not model.ShowConfiguration2(row.configuration):raise RuntimeError('configuration unavailable')
                dimension=model.Parameter(row.dimension)
                if dimension is None:raise ValueError('mapped dimension missing: '+row.parameter)
                value=float(dimension.SystemValue)*1000
                if not math.isfinite(value):raise RuntimeError('invalid native dimension')
                values[row.parameter]=value
            finally:self.close_document(model)
        return values
    def write(self,change):
        row=next(r for r in self.rows if r.parameter==change['parameter'])
        model=self.open_document(self.copies[str(Path(row.document).resolve())],row.configuration)
        try:
            if not model.ShowConfiguration2(row.configuration):raise RuntimeError('configuration unavailable')
            dim=model.Parameter(row.dimension)
            if dim is None or not math.isclose(float(dim.SystemValue)*1000,change['before_mm'],abs_tol=.01):raise RuntimeError('stale dimension plan')
            if int(dim.SetSystemValue3(change['after_mm']/1000,3,[row.configuration]))!=0:raise RuntimeError('dimension edit rejected')
            if not read_member(model,'EditRebuild3'):raise RuntimeError('dimension rebuild failed')
            self.save_work(model)
        finally:self.close_document(model)
    def save_work(self,model):
        self.guard();self.owned_path(read_member(model,'GetPathName'))
        result=model.Save3(1,0,0)
        if not result or (isinstance(result,tuple) and (not result[0] or (len(result)>1 and result[1]))):raise RuntimeError('isolated Save3 failed')
    def rebuild_save(self):
        scopes=sorted(self.scopes,key=lambda item:item[0]==self.source)
        for path,configuration in scopes:
            model=self.open_document(path,configuration)
            try:
                if not model.ShowConfiguration2(configuration):raise RuntimeError('configuration unavailable')
                if not read_member(model,'EditRebuild3'):raise RuntimeError('roller rebuild failed')
                self.verify_references(model);self.save_work(model)
            finally:self.close_document(model)
    def reopen(self):
        model=self.open_document(self.source,self.request['configuration'])
        try:
            if not read_member(model,'EditRebuild3'):raise RuntimeError('reopened roller rebuild failed')
            self.verify_references(model)
        finally:self.close_document(model)
    def feature_inventory(self):
        import solidworks_generator as sw
        module=sw.ensure_solidworks_typelib();result=[]
        for path,configuration in sorted(self.scopes):
            model=self.open_document(path,configuration)
            try:
                activate=getattr(self,'snapshot_activate_configuration',None)
                if activate:activate(model,configuration)
                elif not model.ShowConfiguration2(configuration):raise RuntimeError('configuration unavailable')
                result.append({'document':Path(path).name,'configuration':configuration,
                    'features':[(str(f.Name),str(f.GetTypeName2())) for f in sw._features(model,module)]})
            finally:self.close_document(model)
        return result
    def mechanical_inventory(self):
        if Path(self.source).suffix.lower()!='.sldasm':return {'scope':'standalone_part_no_mates'}
        model=self.open_document(self.source,self.request['configuration'])
        try:
            if not model.ShowConfiguration2(self.request['configuration']):raise RuntimeError('configuration unavailable')
            mates={}
            for component in model.GetComponents(False) or []:
                for mate in component.GetMates() or []:
                    mates[str(read_member(mate,'Name'))]=int(read_member(mate,'Status'))
            manager=read_member(model,'InterferenceDetectionManager')
            manager.TreatCoincidenceAsInterference=False
            return {'mates':sorted(mates.items()),'interference_count':len(manager.GetInterferences() or []),
                'scope':'mate_native_status_and_static_interference_only; motion_unverified'}
        finally:self.close_document(model)

    def axial_extent(self,axis):
        import solidworks_generator as sw
        from part_verification import solid_inventory
        model=self.open_document(self.source,self.request['configuration'])
        try:
            if not model.ShowConfiguration2(self.request['configuration']):raise RuntimeError('configuration unavailable')
            module=sw.ensure_solidworks_typelib();index='xyz'.index(axis)
            if int(read_member(model,'GetType'))==1:
                bounds,_=solid_inventory(sw._as_interface(module,model,'IPartDoc'),sw,module)
            else:
                boxes=[list(c.GetBox(False,False)) for c in model.GetComponents(False) or []]
                if not boxes or any(len(b)!=6 or any(not math.isfinite(x) for x in b) for b in boxes):raise RuntimeError('assembly bounds unavailable')
                bounds=[min(b[i] for b in boxes)*1000 for i in range(3)]+[max(b[i] for b in boxes)*1000 for i in range(3,6)]
            return bounds[index+3]-bounds[index]
        finally:self.close_document(model)
    def artifacts(self):
        return {'copied_files':{str(Path(path).relative_to(self.root)):{'sha256':sha(path),'bytes':Path(path).stat().st_size} for path in self.copies.values() if Path(path).is_file()},
            'source_sha256_before':self.original_hashes,
            'source_sha256_after':{path:sha(path) for path in self.original_hashes}}

    def assert_closed(self,targets):
        app=self.guard()
        # A referenced component can remain loaded after its parent closes.
        # Require the entire application inventory empty before byte restore.
        import solidworks_generator as sw
        if sw._list_open_document_titles(app):
            raise RuntimeError('documents remain loaded; byte restore refused')
        for path in targets:
            if app.GetOpenDocumentByName(str(path)) is not None:
                raise RuntimeError('restore target still loaded')

    def close_for_restore(self,targets):
        app=self.guard()
        active=read_member(app,'ActiveDoc')
        if active is not None:
            path=str(Path(str(read_member(active,'GetPathName'))).resolve())
            title=str(read_member(active,'GetTitle'))
            owned=self.lease.owned_docs.get(title)
            # A different active model must never be closed as recovery.
            if path not in targets or owned is None or owned.handle_id!=id(active):
                raise RuntimeError('ActiveDoc is not the exact owned restore target; reconcile required')
            self.close_document(active)
        self.assert_closed(targets)

    def body_inventory(self):
        import solidworks_generator as sw
        from part_verification import solid_inventory
        module=sw.ensure_solidworks_typelib();result=[]
        for path,configuration in sorted(self.scopes):
            model=self.open_document(path,configuration)
            try:
                activate=getattr(self,'snapshot_activate_configuration',None)
                if activate:activate(model,configuration)
                elif not model.ShowConfiguration2(configuration):raise RuntimeError('configuration unavailable')
                if int(read_member(model,'GetType'))==1:
                    bounds,boxes=solid_inventory(sw._as_interface(module,model,'IPartDoc'),sw,module)
                    bodies={'solid_count':len(boxes),'solid_bounds_mm':sorted(boxes),'union_mm':bounds}
                else:
                    bodies={'scope':'assembly_components; solids_snapshotted_in_dependency_parts',
                            'components':sorted(str(read_member(c,'GetPathName')) for c in model.GetComponents(False) or [])}
                result.append({'document':str(path),'configuration':configuration,**bodies})
            finally:self.close_document(model)
        return result

    def reopen_snapshot(self):
        return {'features':self.feature_inventory(),'bodies':self.body_inventory(),
                'dimensions_mm':self.read_all(),'mechanics':self.mechanical_inventory()}

    def checkpoint(self):
        from cad_checkpoint import create_checkpoint
        targets=list(self.copies.values());self.assert_closed(targets)
        hashes={p:sha(p) for p in targets}
        snapshot=self.reopen_snapshot();self.assert_closed(targets)
        if any(sha(p)!=expected for p,expected in hashes.items()):
            raise RuntimeError('snapshot collection changed saved model bytes')
        checkpoint=create_checkpoint(targets,self.root/'rollback-checkpoint',
            scope=self.root/'isolated',snapshot=snapshot,originals=self.original_hashes)
        attempt=getattr(self,'durable_attempt',None)
        if attempt:
            store,key,owner=attempt
            store.update_metadata(key,owner,checkpoint={'directory':str(checkpoint.directory),
                'manifest_sha256':checkpoint.manifest_sha256,'scope':str(checkpoint.scope)})
        return checkpoint

    def restore(self,checkpoint):
        from cad_checkpoint import restore_checkpoint
        return restore_checkpoint(checkpoint,self)
    def close(self):
        if getattr(self,'original_hashes',None):
            for path,before in self.original_hashes.items():
                if sha(path)!=before:raise RuntimeError('source changed during isolated execution')
        if getattr(self,'app',None) is not None:
            self.guard()
            import solidworks_generator as sw
            if sw._list_open_document_titles(self.app):raise RuntimeError('documents remain open; operator recovery required')
        # Each method closes its registered documents in finally; no blanket close.


def run_native(request,destination,sw_exe,*,inspect_only=False,state_db=None,idempotency_key=None):
    if sys.platform!='win32':raise RuntimeError('Windows SolidWorks required')
    from .planning import CORE
    rows=load_mappings(request['mappings']);names={r.parameter for r in rows}
    if not set(CORE)<=names or any(r.status!='confirmed' for r in rows):raise ValueError('confirmed native dimension mappings required')
    if request.get('interface_inventory_status')!='confirmed' or request.get('dependency_inventory_status')!='confirmed':raise ValueError('review interface and dependency inventory first')
    from sw_session import run_on_task_sta,current_lease
    from sw_owned_launch import owned_solidworks
    from cad_receipts import ReceiptStore
    from cad_checkpoint import json_bytes
    originals={str(Path(p).resolve()):sha(p) for p in {request['source_document'],*(r.document for r in rows)}}
    revision=hashlib.sha256(json_bytes(originals)).hexdigest()
    store=ReceiptStore(state_db)
    receipt=store.begin(request['source_document'],revision,{'request':request,'inspect_only':inspect_only},
        key=idempotency_key,metadata={'destination':str(Path(destination).resolve()),'original_sha256':originals})
    key,owner=receipt['key'],receipt['owner']
    if receipt['replayed']:
        return {**receipt['result'],'request_receipt':{'key':key,'status':receipt['status'],
                'session_state':receipt['session_state'],'replayed':True,'readback_repeated':False}}
    def work():
        lease=current_lease()
        lease.durable_write_guard=lambda:store.assert_writer(key,owner)
        lease.close_doc_only=True
        try:
            root=Path(destination).resolve()
            if root.exists():raise FileExistsError(root)
            from cad_reconcile import current_controller_identity, owned_process_identity
            store.update_metadata(key,owner,controller=current_controller_identity())
            with owned_solidworks(Path(sw_exe)):
                store.update_metadata(key,owner,process=owned_process_identity(lease))
                driver=RollerDriver(lease,root)
                driver.durable_attempt=(store,key,owner)
                if inspect_only:
                    import json
                    from copy import deepcopy
                    root.mkdir(parents=True,exist_ok=False)
                    try:
                        driver.isolate(request,root/'isolated')
                        measured=deepcopy(request)
                        measured['measurements']={name:{'value':value,'confirmed':True,'source':'owned isolated native dimension readback'} for name,value in driver.read_all().items()}
                        from .planning import plan_variant
                        report={'status':'inspection_review_required','request':measured,'plan':plan_variant(measured),
                            'features':driver.feature_inventory(),'mechanics':driver.mechanical_inventory(),
                            'native_acceptance':'pending_windows_validation','process_exit':'pending_external_observation'}
                        (root/'inspection.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                        return report
                    finally:
                        driver.close()
                        if 'report' in locals():report['cleanup']='owned_documents_closed'
                return execute_variant(request,driver,root)
        finally:
            # Detach from a worker that may later be reused, but never clear its
            # poison/timeout flags or the durable unresolved receipt.
            lease.durable_write_guard=None
            store.returned(key,owner)
    try:
        result=run_on_task_sta(work,timeout=900,task_name='roller-overall-variant',
                               durable_attempt=(store,key,owner))
        safe=(result.get('cleanup')=='owned_documents_closed' and
              (result.get('status') in {'saved_reopened_readback','inspection_review_required'} or
               result.get('rollback',{}).get('state')=='RESTORED' or not result.get('cad_write_attempted')))
        if safe:
            store.finish(key,owner,result,succeeded=result.get('status')!='failed')
        else:
            state='ROLLBACK_UNCONFIRMED' if result.get('rollback',{}).get('state')=='ROLLBACK_UNCONFIRMED' else 'OUTCOME_UNKNOWN'
            store.quarantine(key,owner,state)
        result['request_receipt']={'key':key,'status':store.get(key)['status'],
                                   'session_state':store.get(key)['session_state'],'replayed':False}
        return result
    except BaseException as exc:
        store.quarantine(key,owner,'OUTCOME_UNKNOWN',detail={'error_type':type(exc).__name__})
        raise
