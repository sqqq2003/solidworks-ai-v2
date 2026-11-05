"""Standalone-part inspection and batch edits using existing typed modeling port."""
from contextlib import contextmanager
import math
from pathlib import Path
import shutil

from cad_checkpoint import digest_file
from modeling_domain.native import NativeModelingPort
from modeling_domain.dimension_edit import edit_reviewed_length
from modeling_domain.transaction import require_revision, RevisionConflict, feature_map
from ql5050px.native_machine import read_member
from sw_compat.com_access import com_int
from .workflow import inspect_digest


class FunctionModelPort(NativeModelingPort):
    def isolate(self, source, configuration):
        self.guard();source=Path(source).resolve(strict=True)
        if source.suffix.casefold()!='.sldprt':raise ValueError('standalone .SLDPRT required; assemblies need separate linkage review')
        if digest_file(source)!=self.originals[str(source)]:raise ValueError('source changed before copy')
        folder=self.host.root/'models';folder.mkdir(parents=True,exist_ok=False)
        self.path=folder/source.name
        with source.open('rb') as src,self.path.open('xb') as dest:shutil.copyfileobj(src,dest)
        if digest_file(self.path)!=self.originals[str(source)]:raise RuntimeError('isolated copy hash differs')
        self.host.reopen(self.path)
        from src.a01_next.native_production import activate_configuration
        activate_configuration(self.host.model,configuration)
        # A missing dependency interface is not proof of a standalone part.
        dependencies=self.host.model.GetDependencies2(True,True,True)
        if dependencies:raise ValueError('external references require a separately isolated dependency workflow')
        self.configuration=configuration
        self.owned_features={r['name'] for r in self.inventory()['features']}
        self.owned_bodies={r['name'] for r in self.inventory()['bodies']}
        if not self.owned_bodies:raise ValueError('source part has no positive solid bodies')

    def dimension(self, name):
        self.guard();dimension=self.host.model.Parameter(name)
        if dimension is None:raise ValueError('native dimension missing: '+name)
        if hasattr(dimension,'_oleobj_'):
            import solidworks_generator as sw
            dimension=sw._as_interface(sw.ensure_solidworks_typelib(),dimension,'IDimension')
        if com_int(dimension.GetType())!=0:raise ValueError('a linear dimension is required')
        return dimension

    def read_length(self,name):
        dimension=self.dimension(name);value=float(dimension.SystemValue)*1000
        if not math.isfinite(value) or value<=0:raise RuntimeError('native length invalid')
        return value

    def inspect(self, source, configuration, names=()):
        self.guard();features=self.inventory()['features'];dimensions={}
        if names:
            for name in names:
                if not isinstance(name,str) or '@' not in name:raise ValueError('explicit dimension name required')
                dimension=self.dimension(name)
                dimensions[name]={'name':name,'feature':name.split('@')[1],'value_mm':self.read_length(name),
                    'unit':'mm','editable':not bool(dimension.ReadOnly) and com_int(dimension.DrivenState)==2}
        else:
            part=self._part()
            for row in features:
                feature=part.FeatureByName(row['name'])
                if feature is None:raise RuntimeError('feature disappeared during dimension scan')
                display=feature.GetFirstDisplayDimension();seen=set()
                while display is not None:
                    dimension=display.GetDimension2(0);name=str(read_member(dimension,'FullName'))
                    if name in seen:raise RuntimeError('dimension enumeration cycle')
                    seen.add(name)
                    if len(dimensions)>=1024:raise RuntimeError('dimension inventory limit exceeded; specify names')
                    if com_int(dimension.GetType())==0:
                        value=float(dimension.SystemValue)*1000
                        if math.isfinite(value) and value>0:
                            dimensions[name]={'name':name,'feature':row['name'],'value_mm':value,'unit':'mm',
                                'editable':not bool(dimension.ReadOnly) and com_int(dimension.DrivenState)==2}
                    display=feature.GetNextDisplayDimension(display)
        result={'schema_version':1,'scope':'native_dimension_snapshot','source_document':str(Path(source).resolve()),
                'source_sha256':self.originals[str(Path(source).resolve())],'configuration':configuration,
                'dimensions':sorted(dimensions.values(),key=lambda r:r['name']),
                'inventory':self.inventory(),'simulated_only':self.simulated,'read_only':True,
                'manufacturing_approved':False}
        result['inspection_sha256']=inspect_digest(result)
        return result


class DimensionExecutionPort:
    """Adapter for design_platform.native -> existing sw_api.transaction.execute."""
    def __init__(self, native, edit, baseline_inspection):
        self.native=native;self.edit=edit;self.baseline=baseline_inspection
        self.simulated=native.simulated;self.current=native.revision();self.saved=None;self.rollback=None
        self.rows={r['parameter']:r for r in edit['changes']}
        self.initial_features=feature_map(native.inventory())
        self.initial_body_count=len(native.inventory()['bodies'])

    def check_revision(self):return require_revision(self.native,self.current)

    @contextmanager
    def writer(self):
        self.check_revision();yield

    def preflight(self, rows, destination):
        self.check_revision()
        if Path(destination).resolve()!=self.native.path.resolve():raise ValueError('destination must be this isolated owned part')
        if len(rows)>64:raise ValueError('batch dimension limit exceeded')
        for row in rows:
            if row.parameter not in self.rows or row.dimension!=self.rows[row.parameter]['dimension']:
                raise ValueError('mapping differs from reviewed physical target')
        if feature_map(self.native.inventory())!=self.initial_features:raise RevisionConflict('feature inventory changed')

    def read(self, row):
        self.check_revision()
        return self.native.read_length(row.dimension)/(1000 if row.unit=='m' else 1)

    def checkpoint(self):
        self.check_revision();self.saved=self.native.checkpoint();self.current=self.native.revision()
        return self.saved

    def write(self, row, value):
        self.check_revision();change=self.rows[row.parameter]
        if change['protected']:raise ValueError('protected interface cannot be written')
        after_mm=value*(1000 if row.unit=='m' else 1)
        if not math.isclose(after_mm,change['after_mm'],rel_tol=0,abs_tol=1e-8):raise ValueError('unreviewed target')
        edit_reviewed_length(self.native,self.saved['checkpoint'],configuration=row.configuration,
            dimension_name=row.dimension,before_mm=change['before_mm'],after_mm=after_mm,
            allowed_range=change['allowed_range'],source=change['source'])
        self.current=self.native.revision()
        self.native.record('parameter_written',{'parameter':row.parameter,'dimension':row.dimension,
                            'before_mm':change['before_mm'],'after_mm':after_mm,'revision':self.current})

    def rebuild(self):
        self.check_revision();self.native.rebuild();self.current=self.native.revision();self.verify_inventory()

    def verify_inventory(self):
        inventory=self.native.inventory()
        if feature_map(inventory)!=self.initial_features or len(inventory['bodies'])!=self.initial_body_count:
            raise RuntimeError('dimension edit changed feature inventory or body count')
        for change in self.edit['changes']:
            value=self.native.read_length(change['dimension'])
            if not math.isclose(value,change['after_mm'],rel_tol=0,abs_tol=1e-6):raise RuntimeError('mapped/protected dimension differs')
        return inventory

    def save_as(self,destination):
        self.preflight([],destination);self.native._save();self.current=self.native.revision()

    def reopen(self,destination):
        self.check_revision();self.native.host.close();self.native.host.reopen(self.native.path)
        from src.a01_next.native_production import activate_configuration
        activate_configuration(self.native.host.model,self.edit['configuration'])
        if read_member(self.native.host.model,'GetSaveFlag') is not False:raise RuntimeError('reopened edited part unexpectedly dirty')
        self.current=self.native.revision();self.verify_inventory()

    def restore(self,checkpoint):
        import sys
        if isinstance(sys.exc_info()[1],RevisionConflict):
            self.native.quarantine('OUTCOME_UNKNOWN')
            self.rollback={'state':'OUTCOME_UNKNOWN','reason':'preserve_foreign_edit_and_reconcile'}
            raise RuntimeError('manual edit preserved; reconcile before recovery')
        try:self.rollback=self.native.restore(checkpoint)
        except BaseException:
            self.native.quarantine('ROLLBACK_UNCONFIRMED');raise
        if self.rollback.get('state')!='RESTORED':
            self.native.quarantine('ROLLBACK_UNCONFIRMED');raise RuntimeError('rollback not confirmed')
        self.current=self.native.revision()
