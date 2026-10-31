"""Owned Windows API implementation for assembly creation and linked variants.

All signatures are untested on native SW. No COM imports or attachment at import.
Call via run_owned_native; the session layer supplies the proved task instance.
"""
from pathlib import Path
import json
import sys

from .assembly_builder import validate_transform, finite


def read_member(obj,name):
    """Read a COM member. View iterators are property-first.

    ``GetNextView`` on SW2025 is a propget. Calling the generated method raises
    ``DISP_E_MEMBERNOTFOUND``. A property result, including None at the end of
    the chain, is returned without that call. Any other member still calls a
    method, and only a member-not-found error retries as a property get.
    """
    from part_verification import is_member_not_found
    from sw_compat.com_access import read_propget, read_view_iterator, view_iterator
    if view_iterator(name):
        return read_view_iterator(obj, name)
    value = getattr(obj, name)
    if not callable(value):
        return value
    try:
        return value()
    except Exception as exc:
        if not is_member_not_found(exc):
            raise
        try:
            return read_propget(obj, name)
        except AttributeError:
            raise exc


def retarget_saved_title(lease, title_before, model):
    """Point the existing lease entry at the title SaveAs left open.

    Does not adopt any other open document. A title already marked foreign
    still fails in ``rename_owned``.
    """
    title_after = str(read_member(model, 'GetTitle'))
    if title_after != str(title_before):
        lease.rename_owned(str(title_before), title_after)
    return title_after


def math_transform(utility, array):
    """CreateTransform argument must be SAFEARRAY(double), not a raw list."""
    from sw_math_arrays import double_array
    return utility.CreateTransform(double_array(array, 16))


class NativeMachineDriver:
    def __init__(self,lease,work_root):
        self.lease = lease
        self.root = Path(work_root).resolve()
        self.app = None
        self.receipt = {'documents':{},'events':[],'native_acceptance':'unverified'}

    def guard(self):
        if sys.platform!='win32': raise RuntimeError('native machine operations require Windows')
        from sw_session import require_model_write
        require_model_write(self.lease)
        if self.app is None:
            import pythoncom
            import win32com.client
            import solidworks_generator as sw
            raw,_ = sw._connect_task_solidworks(self.lease,win32com,pythoncom)
            self.lease.note_bound_application(raw)
            self.app = sw._as_interface(sw.ensure_solidworks_typelib(),raw,'ISldWorks')
            # Typed wrappers are a different Python identity. Bind this one and reuse it.
            self.lease.note_bound_application(self.app)
        return self.app

    def owned_path(self,path):
        path = Path(path).resolve()
        if not path.is_relative_to(self.root): raise ValueError('native writes require task work root')
        return path

    def open_document(self,path,configuration='',readonly=False):
        app = self.guard()
        path = Path(path).resolve()
        if not path.is_file(): raise FileNotFoundError(path)
        kind = {'.sldprt':1,'.sldasm':2,'.slddrw':3}.get(path.suffix.lower())
        if kind is None: raise ValueError('unsupported native document')
        opened = app.OpenDoc6(str(path),kind,1|(2 if readonly else 0),configuration,0,0)
        model = opened[0] if isinstance(opened,tuple) else opened
        errors = opened[1] if isinstance(opened,tuple) and len(opened)>1 else 0
        if model is None or errors: raise RuntimeError(f'OpenDoc6 failed: {errors}')
        if Path(str(read_member(model,'GetPathName'))).resolve()!=path:
            raise RuntimeError('opened document differs from requested path')
        title = str(read_member(model,'GetTitle'))
        self.lease.note_owned_document(title,handle_id=id(model))
        return model

    def close_document(self,model):
        self.guard()
        from sw_session import close_owned_document
        close_owned_document(self.lease,self.app,str(read_member(model,'GetTitle')))

    def activate(self,model):
        self.guard()
        title = str(read_member(model,'GetTitle'))
        self.app.ActivateDoc3(title,False,0,0)
        active = read_member(self.app,'ActiveDoc')
        if active is None or str(read_member(active,'GetTitle'))!=title:
            raise RuntimeError('could not activate task document')

    def pack_and_go(self,source,folder,configuration):
        """Source opened readonly; isolate every native dependency with SavePackAndGo."""
        folder = self.owned_path(folder)
        folder.mkdir(parents=True,exist_ok=False)
        model = self.open_document(source,configuration,readonly=True)
        try:
            package = model.Extension.GetPackAndGo()
            if package is None: raise RuntimeError('GetPackAndGo failed')
            package.IncludeDrawings = False
            package.FlattenToSingleFolder = True
            names = list(package.GetDocumentNames())
            basenames = [Path(str(n)).name.casefold() for n in names]
            if len(basenames)!=len(set(basenames)): raise ValueError('Pack and Go duplicate basenames require explicit remapping')
            if not package.SetSaveToName(True,str(folder)): raise RuntimeError('SetSaveToName failed')
            statuses = model.Extension.SavePackAndGo(package)
            if statuses is None or any(int(code)!=0 for code in statuses):
                raise RuntimeError('SavePackAndGo returned native errors: '+str(statuses))
            copies = {str(Path(str(name)).resolve()):str(folder/Path(str(name)).name) for name in names}
            if not copies or any(not Path(p).is_file() for p in copies.values()):
                raise RuntimeError('Pack and Go missing expected dependency copies')
            root_copy = copies.get(str(Path(source).resolve()))
            if root_copy is None: raise RuntimeError('source root not found in Pack and Go inventory')
            self.receipt['events'].append({'op':'pack_and_go','source':str(source),'copies':copies})
            return root_copy
        finally:
            self.close_document(model)

    def verify_references(self,model):
        if int(read_member(model,'GetType'))!=2: return []
        components = model.GetComponents(False) or []
        refs = []
        for component in components:
            path = str(read_member(component,'GetPathName'))
            if not path or not Path(path).resolve().is_relative_to(self.root):
                raise RuntimeError('assembly still references an original/external/virtual component')
            refs.append(path)
        return refs

    def save_reopen(self,model,path,configuration,expected_occurrences=None):
        path = self.owned_path(path)
        if not read_member(model,'EditRebuild3'): raise RuntimeError('native rebuild failed')
        self.verify_references(model)
        if path.exists(): raise FileExistsError(path)
        title_before = str(read_member(model,'GetTitle'))
        if int(model.SaveAs3(str(path),0,1))!=0 or not path.is_file(): raise RuntimeError('native SaveAs3 failed')
        # SaveAs renames the open document. guard() inventories titles before
        # CloseDoc; the pre-save title would look unowned. Referenced models
        # SolidWorks loads for drawing views are not registered here.
        retarget_saved_title(self.lease, title_before, model)
        self.close_document(model)
        reopened = self.open_document(path,configuration)
        if not read_member(reopened,'EditRebuild3'): raise RuntimeError('reopen rebuild failed')
        refs = self.verify_references(reopened)
        count = len(reopened.GetComponents(True) or []) if int(read_member(reopened,'GetType'))==2 else None
        if expected_occurrences is not None and count!=expected_occurrences:
            raise RuntimeError('reopened immediate component count mismatch')
        self.close_document(reopened)
        return {'path':str(path),'configuration':configuration,'references':refs,
                'immediate_component_count':count,'reopened':True,'mechanical_acceptance':'unverified'}

    def select_reference(self,model,reference,instances):
        occurrence = instances[reference['occurrence']]
        native_name = str(occurrence.Name2)
        selection = reference['entity']+'@'+native_name+'@'+str(read_member(model,'GetTitle')).rsplit('.',1)[0]
        if not model.Extension.SelectByID2(selection,reference['entity_type'],0,0,0,True,1,None,0):
            raise RuntimeError('mate reference selection failed: '+selection)

    def upsert_mate(self,model,mate,instances):
        self.activate(model)
        model.ClearSelection2(True)
        old = model.FeatureByName(mate['id'])
        if old is not None:
            # Update only the explicit named mate in the isolated copy.
            if not old.Select2(False,0) or not model.Extension.DeleteSelection2(0):
                raise RuntimeError('could not replace mapped mate')
        for reference in mate['references']: self.select_reference(model,reference,instances)
        types = {'coincident':0,'concentric':1,'distance':5,'parallel':3,'angle':6,'lock':16}
        if mate['type'] not in types: raise ValueError('unsupported native mate type')
        distance = finite(mate.get('distance_mm',0))/1000
        from math import radians
        result = model.AddMate5(types[mate['type']],int(mate.get('alignment',0)),False,
            distance,0,0,0,0,radians(finite(mate.get('angle_deg',0))),0,0,False,False,0,0)
        feature = result[0] if isinstance(result,tuple) else result
        error = result[1] if isinstance(result,tuple) and len(result)>1 else 0
        if feature is None or error: raise RuntimeError('AddMate5 failed: '+str(error))
        feature.Name = mate['id']
        model.ClearSelection2(True)

    def build_assembly(self,plan,destination):
        self.guard()
        if plan['status']!='ready_for_native': raise ValueError('unresolved assembly plan')
        folder = self.owned_path(destination)
        folder.mkdir(parents=True,exist_ok=False)
        catalog = plan['tree']['catalog']
        for ref in plan['dependency_order']:
            node = catalog[ref]
            if node.get('source_path'):
                copied = self.pack_and_go(node['source_path'],folder/(ref+'-refs'),node['configuration'])
                model = self.open_document(copied,node['configuration'])
            elif node['type']=='assembly':
                model = self.app.NewDocument(node['template'],0,0,0)
                if model is None: raise RuntimeError('assembly NewDocument failed')
                self.lease.note_owned_document(str(read_member(model,'GetTitle')),handle_id=id(model))
            else:
                generation = node['generation']
                if generation['kind']!='sheet': raise ValueError('only mapped sheet generation supported; other parts require reusable source')
                from cad_analyzer import analyze_cad_file
                from .sheet_metal import generate_native
                target = folder/(ref+'-generated.SLDPRT')
                generate_native(analyze_cad_file(generation['cad_path']),target,generator_options=generation['options'])
                model = self.open_document(target,node['configuration'])
            if not model.ShowConfiguration2(node['configuration']): raise RuntimeError('configuration switch failed')
            instances = {}
            self.activate(model)
            for item in node.get('children',[]):
                child = self.receipt['documents'][item['ref']]
                transform = validate_transform(item['transform_mm'])
                component = model.GetComponentByName(item['native_name']) if item.get('native_name') else None
                if item.get('native_name') and component is None:
                    raise RuntimeError('mapped source occurrence is missing')
                if component is not None:
                    if not component.Select4(False,None,False): raise RuntimeError('component replacement selection failed')
                    if not model.ReplaceComponents2(child['path'],child['configuration'],False,0,True):
                        raise RuntimeError('isolated component reference replacement failed')
                    component = model.GetComponentByName(item['native_name'])
                    if component is None: raise RuntimeError('replacement occurrence could not be resolved')
                else:
                    component = model.AddComponent5(child['path'],0,child['configuration'],False,'',
                        transform[9]/1000,transform[10]/1000,transform[11]/1000)
                if component is None: raise RuntimeError('AddComponent5 failed')
                component.Name2 = item['id']
                component.ReferencedConfiguration = child['configuration']
                array = transform[:]
                array[9:12] = [v/1000 for v in array[9:12]]
                component.Transform2 = math_transform(self.app.GetMathUtility(), array)
                if catalog[item['ref']].get('component_kind')=='fixed':
                    if not component.Select4(False,None,False): raise RuntimeError('fixed component selection failed')
                    model.FixComponent()
                instances[item['id']] = component
            for mate in plan['tree'].get('mates',[]):
                if mate.get('assembly',plan['tree']['root'])==ref: self.upsert_mate(model,mate,instances)
            suffix = '.SLDASM' if node['type']=='assembly' else '.SLDPRT'
            self.receipt['documents'][ref] = self.save_reopen(model,folder/(ref+suffix),node['configuration'],
                len(node.get('children',[])) if node['type']=='assembly' else None)
        return self.receipt

    def apply_drive(self,plan,destination):
        """Modify only Pack-and-Go copies; config-specific values and readback."""
        self.guard()
        if plan['status']!='ready_for_native': raise ValueError('drive plan unresolved or conflicted')
        folder = self.owned_path(destination)
        folder.mkdir(parents=True,exist_ok=False)
        root_copy = self.pack_and_go(plan['source_assembly'],folder/'refs',plan['assembly_configuration'])
        copies = self.receipt['events'][-1]['copies']
        changes = []
        for component in plan['component_modifications']:
            source = str(Path(component['document']).resolve())
            if source not in copies: raise RuntimeError('modified document not in isolated dependency set')
            model = self.open_document(copies[source],component['configuration'])
            if not model.ShowConfiguration2(component['configuration']): raise RuntimeError('drive configuration switch failed')
            self.activate(model)
            for edit in component['edits']:
                target = edit['target']
                if isinstance(target,dict) and target.get('kind')=='component_translation':
                    if edit['unit']!='mm': raise ValueError('component translation requires mm')
                    part = model.GetComponentByName(target['occurrence'])
                    if part is None: raise RuntimeError('missing positioned component')
                    array = list(part.Transform2.ArrayData)
                    axis = target['axis']
                    if type(axis) is not int or axis not in (0,1,2): raise ValueError('translation axis must be 0/1/2')
                    array[9+axis] = edit['after']/1000
                    part.Transform2 = math_transform(self.app.GetMathUtility(), array)
                    if abs(list(part.Transform2.ArrayData)[9+axis]-array[9+axis])>1e-8:
                        raise RuntimeError('component transform readback mismatch')
                else:
                    if edit['unit'] not in {'mm','deg'}: raise ValueError('native dimension supports mm/deg only')
                    from math import radians
                    value = edit['after']/1000 if edit['unit']=='mm' else radians(edit['after'])
                    dimension = model.Parameter(target)
                    if dimension is None: raise RuntimeError('mapped native dimension missing')
                    if int(dimension.SetSystemValue3(value,3,[component['configuration']]))!=0:
                        raise RuntimeError('configuration-specific dimension write rejected')
                    if abs(float(dimension.SystemValue)-value)>1e-8:
                        raise RuntimeError('dimension readback mismatch')
                changes.append({'component':component['component'],**edit})
            if not read_member(model,'EditRebuild3'): raise RuntimeError('drive part rebuild failed')
            saved = model.Save3(1,0,0)
            if not saved or (isinstance(saved,tuple) and (not saved[0] or (len(saved)>1 and saved[1]))):
                raise RuntimeError('work-copy Save3 failed')
            self.close_document(model)
            reopened = self.open_document(copies[source],component['configuration'])
            for edit in component['edits']:
                if isinstance(edit['target'],str):
                    from math import radians
                    expected = edit['after']/1000 if edit['unit']=='mm' else radians(edit['after'])
                    if abs(float(reopened.Parameter(edit['target']).SystemValue)-expected)>1e-8:
                        raise RuntimeError('saved dimension readback mismatch')
            self.close_document(reopened)
        for mate in plan['affected_mates']:
            copied = copies.get(str(Path(mate['document']).resolve()))
            if not copied: raise RuntimeError('mate assembly not in isolated copy set')
            model = self.open_document(copied,mate['configuration'])
            instances = {str(c.Name2):c for c in model.GetComponents(True) or []}
            self.upsert_mate(model,mate['native_mate'],instances)
            if not read_member(model,'EditRebuild3') or not model.Save3(1,0,0):
                raise RuntimeError('mate update rebuild/save failed')
            self.close_document(model)
        model = self.open_document(root_copy,plan['assembly_configuration'])
        receipt = self.save_reopen(model,folder/'variant.SLDASM',plan['assembly_configuration'])
        return {'document':receipt,'changes':changes,'status':'native_changes_readback',
                'native_checks':plan['native_checks'],'mechanical_acceptance':'unverified'}

    def inspect_native(self,document,motion_samples=()):
        """Report native mate states/interference and sampled mate-drive evidence.

        Samples are discrete, not a continuous dynamics or collision proof.
        Dimension changes are restored even on failure, and never saved.
        """
        self.owned_path(document)
        model = self.open_document(document)
        if int(read_member(model,'GetType'))!=2: raise ValueError('mechanical checks require assembly')
        evidence = {'mates':[],'interference':[],'motion':[],'simulated_only':False,
                    'acceptance':'unverified'}
        try:
            seen = set()
            for component in model.GetComponents(False) or []:
                for mate in component.GetMates() or []:
                    name = str(read_member(mate,'Name'))
                    if name in seen: continue
                    seen.add(name)
                    evidence['mates'].append({'name':name,'native_status':int(read_member(mate,'Status'))})
            manager = read_member(model,'InterferenceDetectionManager')
            manager.TreatCoincidenceAsInterference = False
            for hit in manager.GetInterferences() or []:
                evidence['interference'].append({'volume_m3':float(read_member(hit,'Volume')),
                    'components':[str(c.Name2) for c in read_member(hit,'Components')]})
            for sample in motion_samples:
                dimension = model.Parameter(sample['dimension'])
                if dimension is None: raise RuntimeError('motion mate dimension unresolved')
                original = float(dimension.SystemValue)
                try:
                    for value in sample['values_si']:
                        dimension.SystemValue = finite(value)
                        if not read_member(model,'EditRebuild3'): raise RuntimeError('motion sample rebuild failed')
                        evidence['motion'].append({'dimension':sample['dimension'],'requested_si':value,
                            'readback_si':float(dimension.SystemValue),
                            'interference_count':len(manager.GetInterferences() or [])})
                finally:
                    dimension.SystemValue = original
                    if not read_member(model,'EditRebuild3'): raise RuntimeError('motion sample restoration failed')
            return evidence
        finally:
            self.close_document(model)


def run_owned_native(sw_exe,work_root,operation,payload):
    """Explicit Windows entry; fresh work root; no process attachment shortcuts."""
    if sys.platform!='win32': raise RuntimeError('Windows SolidWorks required')
    from sw_session import run_on_task_sta, current_lease
    from sw_owned_launch import owned_solidworks
    def job():
        root = Path(work_root).resolve()
        root.mkdir(parents=True,exist_ok=False)
        with owned_solidworks(Path(sw_exe)):
            from .native_drawings import ManufacturingDriver
            driver = ManufacturingDriver(current_lease(),root)
            if operation=='assembly': return driver.build_assembly(payload,root/'assembly')
            if operation=='drive': return driver.apply_drive(payload,root/'drive')
            if operation=='drawings':
                from copy import deepcopy
                receipt = deepcopy(payload['assembly_receipt'])
                for node,item in receipt['documents'].items():
                    item['path'] = driver.pack_and_go(item['path'],root/('drawing-refs-'+node),item['configuration'])
                return driver.export_manufacturing(payload['plan'],receipt,root/'drawings')
            if operation=='checks':
                copied = driver.pack_and_go(payload['document'],root/'check-refs',payload['configuration'])
                return driver.inspect_native(copied,payload.get('motion_samples',[]))
            raise ValueError('unknown native machine operation')
    return run_on_task_sta(job,timeout=900,task_name='ql-machine-native')
