"""Read-only snapshot normalization, stable document identities and classification."""
import hashlib
import json
from pathlib import PureWindowsPath

LABELS = {'frame':('frame','机架'), 'conveyor':('conveyor','输送','roller'),
          'left_drive':('left','左驱动'), 'right_drive':('right','右驱动'),
          'sealing':('sealing','封箱','tape'), 'standard_parts':('bearing','轴承','bolt','螺栓')}


def identity(path, configuration):
    key = str(PureWindowsPath(path)).casefold()+'|'+configuration
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def scan_snapshot(snapshot, previous=None):
    if snapshot.get('machine')!='QL-5050PX':
        raise ValueError('explicit QL identity required; GT-ZX snapshots rejected')
    documents, edges, missing = {}, [], []
    for source in snapshot.get('documents',[]):
        row = dict(source)
        key = identity(row['path'],row['configuration'])
        row['id'] = key
        row['fingerprint'] = hashlib.sha256(json.dumps(source,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if key in documents and documents[key]['fingerprint']!=row['fingerprint']:
            raise ValueError('conflicting duplicate document snapshot')
        documents[key] = row
        if row.get('exists') is not True: missing.append(row['path'])
        for child in row.get('children',[]):
            edges.append({'parent':key,'child':identity(child['path'],child['configuration']),
                          'occurrence':child['occurrence'],'transform':child.get('transform')})
        text = ' '.join([row['path'],str(row.get('properties',{}))]).casefold()
        matches = [{'module':label,'confidence':0.65,'evidence':'name/property keyword',
                    'keywords':[word for word in words if word in text], 'review_status':'review_required'}
                   for label,words in LABELS.items() if any(word in text for word in words)]
        row['classification_candidates'] = matches
    for edge in edges:
        if edge['child'] not in documents: missing.append('unscanned:'+edge['child'])
    old = (previous or {}).get('documents',{})
    return {'schema_version':1,'machine':'QL-5050PX','documents':documents,'relations':edges,
            'missing_references':sorted(set(missing)),
            'changed':[k for k,v in documents.items() if old.get(k,{}).get('fingerprint')!=v['fingerprint']],
            'removed':sorted(set(old)-set(documents)), 'cad_written':False,'native_acceptance':'unverified'}


class ReadOnlyScanner:
    """Requires a proved owned app/session; source opened readonly and closed unsaved.

    Host detail_reader(model) supplies dimensions/mates/equations via its typed
    API when SW bindings differ. Built-in reader captures feature/property data.
    """
    def __init__(self, app, lease, detail_reader=None):
        self.app,self.lease,self.detail_reader = app,lease,detail_reader

    def scan(self,path,configuration):
        import sys
        if sys.platform!='win32': raise RuntimeError('Windows scanner required')
        from sw_session import require_model_write, close_owned_document
        require_model_write(self.lease)
        # Verify supplied app is the app proved by the existing ownership layer.
        import pythoncom, win32com.client
        import solidworks_generator as sw
        bound,_ = sw._connect_task_solidworks(self.lease,win32com,pythoncom)
        if int(bound.GetProcessID())!=int(self.app.GetProcessID()): raise RuntimeError('foreign app refused')
        visited,rows = set(),[]
        def visit(filename,config):
            key = identity(filename,config)
            if key in visited: return
            visited.add(key)
            kind = 2 if filename.lower().endswith('.sldasm') else 1
            opened = self.app.OpenDoc6(filename,kind,3,config,0,0)
            model = opened[0] if isinstance(opened,tuple) else opened
            if model is None: rows.append({'path':filename,'configuration':config,'exists':False}); return
            title = model.GetTitle()
            self.lease.note_owned_document(title,handle_id=id(model))
            try:
                features,dimensions,equations,children = [],[],[],[]
                feature = model.FirstFeature()
                while feature is not None:
                    features.append({'name':feature.Name,'type':feature.GetTypeName2()})
                    display = feature.GetFirstDisplayDimension()
                    while display is not None:
                        dim = display.GetDimension2(0)
                        dimensions.append({'name':dim.FullName,'feature':feature.Name,
                            'value_si':dim.SystemValue,'unit':'SI','source':'native_dimension'})
                        display = feature.GetNextDisplayDimension(display)
                    feature = feature.GetNextFeature()
                manager = model.GetEquationMgr()
                if manager is not None:
                    for i in range(manager.GetCount()): equations.append(str(manager.Equation(i)))
                if kind==2:
                    for c in model.GetComponents(True) or []:
                        child = {'path':c.GetPathName(),'configuration':c.ReferencedConfiguration,'occurrence':c.Name2}
                        if child['path']: children.append(child)
                details = self.detail_reader(model) if self.detail_reader else {}
                rows.append({'path':filename,'configuration':config,'exists':True,'features':features,
                    'dimensions':dimensions,'equations':equations,'children':children,
                    'properties':model.Extension.CustomPropertyManager[config].GetAll3(),
                    'material':getattr(model,'GetMaterialPropertyName2',lambda *_:None)(config,''),
                    'mates_status':'pending_detail_reader',**details})
            finally: close_owned_document(self.lease,self.app,title)
            for child in children: visit(child['path'],child['configuration'])
        visit(str(path),configuration)
        return scan_snapshot({'machine':'QL-5050PX','documents':rows})
