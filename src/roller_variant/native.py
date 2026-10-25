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
                if not model.ShowConfiguration2(configuration):raise RuntimeError('configuration unavailable')
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
    def close(self):
        if getattr(self,'original_hashes',None):
            for path,before in self.original_hashes.items():
                if sha(path)!=before:raise RuntimeError('source changed during isolated execution')
        if getattr(self,'app',None) is not None:
            self.guard()
            import solidworks_generator as sw
            if sw._list_open_document_titles(self.app):raise RuntimeError('documents remain open; operator recovery required')
        # Each method closes its registered documents in finally; no blanket close.


def run_native(request,destination,sw_exe,*,inspect_only=False):
    if sys.platform!='win32':raise RuntimeError('Windows SolidWorks required')
    from .planning import CORE
    rows=load_mappings(request['mappings']);names={r.parameter for r in rows}
    if not set(CORE)<=names or any(r.status!='confirmed' for r in rows):raise ValueError('confirmed native dimension mappings required')
    if request.get('interface_inventory_status')!='confirmed' or request.get('dependency_inventory_status')!='confirmed':raise ValueError('review interface and dependency inventory first')
    from sw_session import run_on_task_sta,current_lease
    from sw_owned_launch import owned_solidworks
    def work():
        root=Path(destination).resolve()
        if root.exists():raise FileExistsError(root)
        with owned_solidworks(Path(sw_exe)):
            driver=RollerDriver(current_lease(),root)
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
                finally:driver.close()
            return execute_variant(request,driver,root)
    return run_on_task_sta(work,timeout=900,task_name='roller-overall-variant')
