"""Owned native modeling port, reusing the existing part host and checkpoints."""
from copy import deepcopy
import math
from pathlib import Path
import uuid

from cad_checkpoint import create_checkpoint,digest_file,restore_checkpoint
from drawing_review import atomic_json
from ql5050px.native_part_host import NativePartHost
from ql5050px.native_machine import read_member,retarget_saved_title
from ql5050px.com_selection import select_by_id
from sw_feature_calls import solid_blind_extrude,solid_blind_cut
from .contract import digest,validate_plan
from .transaction import RevisionConflict

FOLDERS={'SolidBodyFolder','SurfaceBodyFolder','HistoryFolder','CommentsFolder','SensorFolder',
         'FavoriteFolder','SelectionSetFolder','DetailCabinet','MaterialFolder'}
# SOLIDWORKS 2025 API swBodyOperationType_e; 2 is NOT SWBODYINTERSECT.
SWBODYINTERSECT=15901


class NativeModelingPort:
    simulated=False

    def __init__(self,host,*,originals):
        self.host=host;self.originals=originals;self.path=host.root/'models'/'work.SLDPRT'
        self.owned_bodies=set();self.owned_features=set();self.sequence=0

    def guard(self):
        result=self.host.guard()
        model=self.host.model
        if model is not None:
            active=read_member(self.host.app,'ActiveDoc')
            if active is None:raise RuntimeError('owned model is not active')
            same=active is model
            if not same:
                import pythoncom
                same=active._oleobj_.QueryInterface(pythoncom.IID_IUnknown)==model._oleobj_.QueryInterface(pythoncom.IID_IUnknown)
            title=str(read_member(model,'GetTitle'))
            owned=self.host.lease.owned_docs.get(title)
            if not same or owned is None or owned.handle_id!=id(model):
                raise RuntimeError('ActiveDoc is not the proved owned model')
        return result

    def initialize(self):
        self.guard();self.path.parent.mkdir(parents=True,exist_ok=False)
        if any(digest_file(path)!=sha for path,sha in self.originals.items()):
            raise ValueError('template/source changed before NewDocument')
        self.host.create()
        model=self.host.model;title=str(read_member(model,'GetTitle'))
        from part_verification import assert_native_save
        assert_native_save(self.path,model.SaveAs3(str(self.path),0,1))
        retarget_saved_title(self.host.lease,title,model)
        inventory=self.inventory()
        if inventory['bodies'] or any(r['native_type'] not in {'RefPlane','OriginProfileFeature','Origin'} for r in inventory['features']):
            raise ValueError('template must contain only origin/planes; use a separate reviewed edit workflow')
        self._save();return self.revision()

    def _part(self):
        import solidworks_generator as sw
        return sw._as_interface(sw.ensure_solidworks_typelib(),self.host.model,'IPartDoc')

    def _native_bodies(self):
        import solidworks_generator as sw
        return [sw._as_interface(sw.ensure_solidworks_typelib(),b,'IBody2')
                for b in (self._part().GetBodies2(sw.SW_BODY_TYPE_SOLID,False) or [])]

    def inventory(self):
        self.guard()
        import solidworks_generator as sw
        features=[];seen=set()
        def add(feature):
            from src.a01_next.native_production import feature_error
            name=str(read_member(feature,'Name'));kind=str(read_member(feature,'GetTypeName2'))
            if name in seen:return
            if len(seen)>=4096:raise RuntimeError('feature inventory limit exceeded')
            seen.add(name)
            if kind not in FOLDERS:
                error=feature_error(feature)
                if error:raise RuntimeError('native feature rebuild error: '+name+': '+str(error))
                features.append({'name':name,'native_type':kind})
            child=read_member(feature,'GetFirstSubFeature')
            walked=set()
            while child is not None:
                identity=str(read_member(child,'Name'))
                if identity in walked:raise RuntimeError('cyclic native subfeature inventory')
                walked.add(identity);add(child);child=read_member(child,'GetNextSubFeature')
        for f in sw._features(self.host.model,sw.ensure_solidworks_typelib()):add(f)
        bodies=[]
        for body in self._native_bodies():
            faces=list(read_member(body,'GetFaces') or [])
            bounds=[float(v)*1000 for v in read_member(body,'GetBodyBox')]
            properties=list(body.GetMassProperties(1.0))
            if len(properties)<5:raise RuntimeError('native body mass properties unavailable')
            volume=float(properties[3])*1e9
            if (not faces or len(bounds)!=6 or not all(math.isfinite(v) for v in bounds) or
                    any(bounds[i+3]<=bounds[i] for i in range(3)) or not math.isfinite(volume) or volume<=0):
                raise RuntimeError('native solid census failed')
            bodies.append({'name':str(read_member(body,'Name')),'faces':len(faces),'bounds_mm':bounds,'volume_mm3':volume})
        return {'features':sorted(features,key=lambda r:r['name']),
                'bodies':sorted(bodies,key=lambda r:r['name']),'bounds_precision':'approximate'}

    def revision(self):
        self.guard();model=self.host.model
        before=int(read_member(model,'GetUpdateStamp'))
        dirty=read_member(model,'GetSaveFlag')
        if type(dirty) is not bool:raise RuntimeError('native dirty state unavailable')
        manager=read_member(model,'ConfigurationManager')
        config=str(read_member(read_member(manager,'ActiveConfiguration'),'Name'))
        inventory=self.inventory();file_sha=digest_file(self.path)
        after=int(read_member(model,'GetUpdateStamp'))
        if before!=after or read_member(model,'GetSaveFlag')!=dirty:raise RevisionConflict('document changed during revision capture')
        return digest({'document':str(self.path.resolve()),'configuration':config,'file_sha256':file_sha,
                       'inventory':inventory,'dirty_stamp':after if dirty else None})

    def create_feature(self,feature):
        self.guard();f=deepcopy(feature);kind=f['kind'];p=f['parameters'];model=self.host.model
        if kind=='sketch':
            self.host.create_editable_feature(f)
        else:
            model.ClearSelection2(True)
            if not select_by_id(model.Extension,p['sketch'],'SKETCH'):raise RuntimeError('owned sketch selection failed')
            if kind=='extrude':native=solid_blind_extrude(model.FeatureManager,p['depth_mm']/1000,merge=p['merge'])
            elif kind=='cut':native=solid_blind_cut(model.FeatureManager,p['depth_mm']/1000,reverse=bool(p.get('reverse',False)))
            elif kind=='revolve':
                # Verify the reviewed named segment is still a construction
                # line, rather than picking the first line/axis in a sketch.
                sketch=self._part().FeatureByName(p['sketch'])
                if sketch is None:raise RuntimeError('owned revolve sketch absent')
                specific=sketch.GetSpecificFeature2()
                segments=list(read_member(specific,'GetSketchSegments') or [])
                axis_name=p['axis']['name'].rsplit('@',1)[0]
                axes=[s for s in segments if str(read_member(s,'GetName'))==axis_name]
                if len(axes)!=1 or read_member(axes[0],'ConstructionGeometry') is not True:
                    raise RuntimeError('reviewed construction axis not found')
                if not select_by_id(model.Extension,p['axis']['name'],'SKETCHSEGMENT',append=True,mark=16):raise RuntimeError('explicit revolve axis selection failed')
                from sw_feature_calls import solid_revolve
                native=solid_revolve(model.FeatureManager,math.radians(p['angle_degrees']),merge=p['merge'])
            else:raise ValueError('operation outside modeling whitelist')
            if native is None:raise RuntimeError('native feature creation returned no feature')
            native.Name=f['id'];model.ClearSelection2(True)
        self.owned_features.add(f['id'])

    def name_bodies(self,expected_names):
        self.guard();bodies=self._native_bodies();names=[str(read_member(b,'Name')) for b in bodies]
        if len(bodies)!=len(expected_names):raise RuntimeError('native body count mismatch before naming')
        if len(bodies)==1:
            bodies[0].Name=expected_names[0]
        else:
            missing=set(expected_names)-set(names)
            new=[b for b,n in zip(bodies,names) if n not in self.owned_bodies]
            if len(missing)!=len(new) or len(new)>1:raise RuntimeError('ambiguous multibody identity; no guessed renaming')
            if new:new[0].Name=next(iter(missing))
        self.owned_bodies=set(expected_names)
        if {str(read_member(b,'Name')) for b in self._native_bodies()}!=self.owned_bodies:raise RuntimeError('native body name readback differs')

    def rebuild(self):self.host.rebuild()

    def _save(self):
        self.guard()
        import pythoncom
        from win32com.client import VARIANT

        # Save3's Errors and Warnings are COM [out] LONG parameters. Plain
        # integers work with some generated wrappers, but pywin32's SW2025
        # dispatch requires explicit by-reference VARIANTs.
        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        result = self.host.model.Save3(1, errors, warnings)
        returned = result if isinstance(result, tuple) else (result,)
        ok = returned[0]
        error_value = returned[1] if len(returned) > 1 else errors
        warning_value = returned[2] if len(returned) > 2 else warnings
        error_code = int(getattr(error_value, 'value', error_value) or 0)
        warning_code = int(getattr(warning_value, 'value', warning_value) or 0)
        if (ok is not True and not (type(ok) is int and ok == 1)) or error_code:
            raise RuntimeError(
                'isolated model Save3 failed: errors='+str(error_code)+
                ' warnings='+str(warning_code))

    def checkpoint(self):
        self._save();snapshot=self.inventory();self.host.close()
        checkpoint=create_checkpoint([self.path],self.host.root/'model-checkpoints'/uuid.uuid4().hex,
            scope=self.path.parent,snapshot={'features':snapshot['features'],'bodies':snapshot['bodies']},originals=self.originals)
        attempt=getattr(self.host.lease,'durable_attempt',None)
        if attempt:
            store,key,owner=attempt
            store.update_metadata(key,owner,checkpoint={'directory':str(checkpoint.directory),
                'manifest_sha256':checkpoint.manifest_sha256,'scope':str(checkpoint.scope)})
        self.host.reopen(self.path)
        if self.inventory()!=snapshot:raise RuntimeError('checkpoint reopen inventory differs before first write')
        return {'checkpoint':checkpoint,'bodies':set(self.owned_bodies),'features':set(self.owned_features)}

    def close_for_restore(self,targets):
        self.guard();active=read_member(self.host.app,'ActiveDoc');model=self.host.model
        if active is not None:
            if model is None:raise RuntimeError('unknown ActiveDoc; preserve session')
            same=active is model
            if not same:
                import pythoncom
                same=active._oleobj_.QueryInterface(pythoncom.IID_IUnknown)==model._oleobj_.QueryInterface(pythoncom.IID_IUnknown)
            title=str(read_member(model,'GetTitle'));owned=self.host.lease.owned_docs.get(title)
            if not same or owned is None or owned.handle_id!=id(model) or str(Path(read_member(model,'GetPathName')).resolve()) not in targets:
                raise RuntimeError('ActiveDoc is not the checkpoint-owned model')
        if model is not None:self.host.close()

    def assert_closed(self,targets):
        import solidworks_generator as sw
        self.guard()
        if sw._list_open_document_titles(self.host.app) or any(self.host.app.GetOpenDocumentByName(p) is not None for p in targets):
            raise RuntimeError('restore target still loaded')

    def reopen_snapshot(self):
        self.host.reopen(self.path)
        try:
            snapshot=self.inventory()
            return {'features':snapshot['features'],'bodies':snapshot['bodies']}
        finally:self.host.close()

    def restore(self,baseline):
        result=restore_checkpoint(baseline['checkpoint'],self)
        self.owned_bodies=set(baseline['bodies']);self.owned_features=set(baseline['features'])
        self.host.reopen(self.path);return result

    def save_reopen(self):
        self._save();self.host.close();self.host.reopen(self.path)
        if read_member(self.host.model,'GetSaveFlag') is not False:raise RuntimeError('reopened document unexpectedly dirty')

    def record(self,phase,value):
        self.sequence+=1
        atomic_json(self.host.root/'evidence'/f'{self.sequence:04d}-{phase}.json',value,exclusive=True)

    def quarantine(self,state):
        self.host.lease.writes_blocked=True
        attempt=getattr(self.host.lease,'durable_attempt',None)
        if attempt:attempt[0].quarantine(attempt[1],attempt[2],state)

    def capture_camera(self):
        self.guard();view=read_member(self.host.model,'ActiveView')
        # Keep native value objects as well as independent arrays; restore must
        # not recompute an approximate camera from a standard view name.
        orientation=read_member(view,'Orientation3');translation=read_member(view,'Translation3')
        scale=float(read_member(view,'Scale2'))
        return {'orientation':orientation,'translation':translation,'scale':scale,
                'orientation_array':list(read_member(orientation,'ArrayData')),
                'translation_array':list(read_member(translation,'ArrayData'))}

    def set_camera(self,name):
        self.guard();native={'front':'*Front','top':'*Top','right':'*Right','isometric':'*Isometric'}[name]
        if self.host.model.ShowNamedView2(native,-1) is False:raise RuntimeError('standard camera unavailable')
        self.host.model.ViewZoomtofit2()

    def restore_camera(self,prior):
        self.guard();view=read_member(self.host.model,'ActiveView')
        view.Orientation3=prior['orientation'];view.Translation3=prior['translation'];view.Scale2=prior['scale']
        self.host.model.GraphicsRedraw2()

    def camera_matches(self,prior):
        actual=self.capture_camera()
        return (len(actual['orientation_array'])==len(prior['orientation_array']) and
                len(actual['translation_array'])==len(prior['translation_array']) and
                all(math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-10) for key in ('orientation_array','translation_array') for a,b in zip(actual[key],prior[key])) and
                math.isclose(actual['scale'],prior['scale'],rel_tol=1e-9,abs_tol=1e-10))

    def capture_image(self,path):
        self.guard()
        if Path(path).exists():raise FileExistsError(path)
        if self.host.model.SaveBMP(str(path),1200,900) is not True:raise RuntimeError('native image capture failed')

    def intersection_on_copies(self,left,right):
        self.guard();bodies={str(read_member(b,'Name')):b for b in self._native_bodies()}
        for name in (left,right):
            fault=read_member(bodies[name],'Check3')
            if fault is None or int(read_member(fault,'Count'))!=0:
                raise RuntimeError('native body validity not proved before Boolean')
        # Measure real part bodies before the copies are consumed by Boolean.
        # IModelDoc2.ClosestDistance supports solid bodies, not temporary ones.
        import pythoncom
        from win32com.client import VARIANT
        point_a=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_VARIANT,None)
        point_b=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_VARIANT,None)
        raw_distance=self.host.model.ClosestDistance(bodies[left],bodies[right],point_a,point_b)
        # Generated wrappers can return the two [out] arguments as a tuple.
        if isinstance(raw_distance,tuple):
            if len(raw_distance)!=3:raise RuntimeError('ClosestDistance result shape unavailable')
            raw_distance,pa,pb=raw_distance
        else:pa,pb=point_a.value,point_b.value
        distance=float(raw_distance)*1000
        if (not math.isfinite(distance) or distance<0 or any(
                not isinstance(p,(list,tuple)) or len(p)!=3 or any(
                    type(v) not in (int,float) or not math.isfinite(v) for v in p) for p in (pa,pb))):
            raise RuntimeError('ClosestDistance has no verified solution')
        if not math.isclose(math.dist(pa,pb)*1000,distance,rel_tol=1e-5,abs_tol=1e-5):
            raise RuntimeError('ClosestDistance endpoints disagree')
        # Both operands are transient copies. Original part bodies are never
        # passed to a destructive Boolean and failed result != zero volume.
        a,b=bodies[left].Copy2(False),bodies[right].Copy2(False)
        if a is None or b is None:raise RuntimeError('body Copy2 failed')
        error=VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
        raw=a.Operations2(SWBODYINTERSECT,b,error)
        code=int(error.value)
        if isinstance(raw,tuple) and len(raw)==2 and type(raw[1]) is int:
            raw,code=raw
        # SolidWorks may signal no intersection with an error code. This route
        # intentionally leaves it UNKNOWN until a version-specific native
        # adapter proves the no-intersection status, rather than assuming 0.
        if code!=0 or raw is None:raise RuntimeError('intersection Boolean unconfirmed: '+str(code))
        pieces=list(raw) if isinstance(raw,(list,tuple)) else [raw]
        volume=0.
        for body in pieces:
            import solidworks_generator as sw
            body=sw._as_interface(sw.ensure_solidworks_typelib(),body,'IBody2')
            properties=list(body.GetMassProperties(1.0))
            if len(properties)<4:raise RuntimeError('intersection mass properties unavailable')
            piece_volume=float(properties[3])*1e9
            if not math.isfinite(piece_volume) or piece_volume<0:raise RuntimeError('intersection volume invalid')
            volume+=piece_volume
        return {'status':'measured','intersection_volume_mm3':volume,'distance_mm':distance}
