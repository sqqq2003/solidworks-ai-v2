"""Native host mixin for explicitly mapped sketches and simple extrude/cut features.

Host supplies guard(), model and proved document ownership. This does not attach
or create an unknown SW session. Unsupported features fail before any operation.
"""
class EditableFeaturesMixin:
    supported_feature_kinds = {'sketch','extrude','cut'}
    def create_editable_feature(self,feature):
        self.guard()
        model=self.model
        kind=feature['kind'];p=feature.get('parameters',{})
        if not feature.get('confirmed') or not feature.get('evidence'):raise ValueError('confirmed feature evidence required')
        if kind not in {'sketch','extrude','cut'}:raise ValueError('native builder not implemented for '+kind)
        model.ClearSelection2(True)
        if kind=='sketch':
            if not p.get('plane'):raise ValueError('mapped sketch plane required')
            if not model.Extension.SelectByID2(p['plane'],'PLANE',0,0,0,False,0,None,0):raise RuntimeError('plane selection failed')
            manager=model.SketchManager;manager.InsertSketch(True)
            try:
                for entity in p.get('entities',[]):
                    if entity['type']=='line':
                        a,b=entity['start'],entity['end']
                        segment=manager.CreateLine(a[0]/1000,a[1]/1000,0,b[0]/1000,b[1]/1000,0)
                    elif entity['type']=='circle':
                        x,y=entity['center'];segment=manager.CreateCircleByRadius(x/1000,y/1000,0,entity['radius']/1000)
                    else:raise ValueError('unsupported sketch entity')
                    if segment is None:raise RuntimeError('sketch entity creation failed')
                sketch=manager.ActiveSketch
                if sketch is None:raise RuntimeError('no active native sketch')
                native=sketch.GetFeature();native.Name=feature['id']
            finally:manager.InsertSketch(True)
        else:
            sketch=p.get('sketch')
            depth=p.get('depth_mm')
            if not sketch or type(depth) not in (int,float) or depth<=0:raise ValueError('mapped sketch and positive depth required')
            if not model.Extension.SelectByID2(sketch,'SKETCH',0,0,0,False,0,None,0):raise RuntimeError('sketch selection failed')
            if kind=='extrude':
                native=model.FeatureManager.FeatureExtrusion2(True,False,False,0,0,depth/1000,0,False,False,False,False,0,0,False,False,False,False,True,True,True,0,0,False)
            else:
                native=model.FeatureManager.FeatureCut3(True,False,False,0,0,depth/1000,0,False,False,False,False,0,0,False,False,False,False,False,True,True,True,True,False,0,0,False)
            if native is None:raise RuntimeError('native feature creation failed')
            native.Name=feature['id']
        return {'feature':feature['id'],'status':'created_pending_readback'}

    def verify_feature_tree(self,names):
        self.guard()
        evidence=[]
        for name in names:
            f=self.model.FeatureByName(name)
            if f is None:raise RuntimeError('feature missing after reopen: '+name)
            evidence.append({'name':name,'native_type':f.GetTypeName2()})
        return {'features':evidence,'dimensions_verified':False,'status':'pending_native_validation'}
