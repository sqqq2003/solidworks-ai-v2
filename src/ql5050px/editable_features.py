"""Native host mixin for explicitly mapped sketches and simple extrude/cut features.

Host supplies guard(), model and proved document ownership. This does not attach
or create an unknown SW session. Unsupported features fail before any operation.
"""
from .feature_operations import FeatureOperationsMixin, validate_operations
from .com_selection import select_by_id

class EditableFeaturesMixin(FeatureOperationsMixin):
    supported_feature_kinds = {'sketch','extrude','cut','fillet','chamfer','mirror','pattern'}
    def create_editable_feature(self,feature):
        self.guard()
        model=self.model
        kind=feature['kind'];p=feature.get('parameters',{})
        if not feature.get('confirmed') or not feature.get('evidence'):raise ValueError('confirmed feature evidence required')
        if kind not in self.supported_feature_kinds:raise ValueError('native builder not implemented for '+kind)
        validate_operations([feature])
        if kind in {'fillet','chamfer','mirror','pattern'}:return self.create_mapped_operation(feature)
        model.ClearSelection2(True)
        if kind=='sketch':
            if not p.get('plane'):raise ValueError('mapped sketch plane required')
            if not select_by_id(model.Extension,p['plane'],'PLANE'):raise RuntimeError('plane selection failed')
            manager=model.SketchManager;manager.InsertSketch(True)
            try:
                for entity in p.get('entities',[]):
                    if entity['type']=='line':
                        a,b=entity['start'],entity['end']
                        segment=manager.CreateLine(a[0]/1000,a[1]/1000,0,b[0]/1000,b[1]/1000,0)
                    elif entity['type']=='circle':
                        x,y=entity['center'];segment=manager.CreateCircleByRadius(x/1000,y/1000,0,entity['radius']/1000)
                    elif entity['type']=='arc':
                        center,start,end=entity['center'],entity['start'],entity['end']
                        direction=entity['direction']
                        if direction not in (-1,1):raise ValueError('explicit arc direction required')
                        segment=manager.CreateArc(center[0]/1000,center[1]/1000,0,start[0]/1000,start[1]/1000,0,end[0]/1000,end[1]/1000,0,direction)
                    else:raise ValueError('unsupported sketch entity')
                    if segment is None:raise RuntimeError('sketch entity creation failed')
                self.apply_sketch_constraints(p.get('constraints',[]))
                sketch=manager.ActiveSketch
                if sketch is None:raise RuntimeError('no active native sketch')
                import solidworks_generator as sw
                module=sw.ensure_solidworks_typelib()
                raw=model.FeatureByPositionReverse(0)
                if raw is None:raise RuntimeError('active sketch feature not found')
                native=sw._as_interface(module,raw,'IFeature')
                if native.GetTypeName2() not in {'ProfileFeature','3DProfileFeature'}:
                    raise RuntimeError('latest feature is not the active sketch; refusing to rename it')
                native.Name=feature['id']
            finally:manager.InsertSketch(True)
        else:
            sketch=p.get('sketch')
            depth=p.get('depth_mm')
            if not sketch or type(depth) not in (int,float) or depth<=0:raise ValueError('mapped sketch and positive depth required')
            if not select_by_id(model.Extension,sketch,'SKETCH'):raise RuntimeError('sketch selection failed')
            if kind=='extrude':
                native=model.FeatureManager.FeatureExtrusion2(True,False,False,0,0,depth/1000,0,False,False,False,False,0,0,False,False,False,False,True,True,True,0,0,False)
            else:
                native=model.FeatureManager.FeatureCut3(True,False,bool(p.get('reverse',False)),0,0,depth/1000,0,False,False,False,False,0,0,False,False,False,False,False,True,True,True,True,False,0,0,False)
            if native is None:raise RuntimeError('native feature creation failed')
            native.Name=feature['id']
        return {'feature':feature['id'],'status':'created_pending_readback'}

    def verify_feature_tree(self,names):
        self.guard()
        import solidworks_generator as sw
        module=sw.ensure_solidworks_typelib()
        part=sw._as_interface(module,self.model,'IPartDoc')
        evidence=[]
        for name in names:
            raw=part.FeatureByName(name)
            if raw is None:raise RuntimeError('feature missing after reopen: '+name)
            f=sw._as_interface(module,raw,'IFeature')
            evidence.append({'name':name,'native_type':f.GetTypeName2()})
        return {'features':evidence,'dimensions_verified':False,'status':'pending_native_validation'}


