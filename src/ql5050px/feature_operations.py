"""Explicit native feature-data operations and sketch constraints for owned hosts.

Feature IDs/property names come from a reviewed version-specific SW mapping;
this module never guesses feature type enum values or selection references.
"""
import math
from .com_selection import select_by_id

PROPERTIES={
 'fillet':{'DefaultRadius','Radius','IsMultipleRadius','PropagateFeatureToParts'},
 'chamfer':{'EdgeChamferDistance','VertexChamferDistance','EdgeChamferAngle','EqualDistance'},
 'mirror':{'GeometryPattern','PropagateVisualProperty'},
 'pattern':{'D1Spacing','D2Spacing','D1TotalInstances','D2TotalInstances','D1ReverseDirection','D2ReverseDirection','GeometryPattern'}}
RELATIONS={'horizontal':'sgHORIZONTAL2D','vertical':'sgVERTICAL2D','coincident':'sgCOINCIDENT','concentric':'sgCONCENTRIC','parallel':'sgPARALLEL','perpendicular':'sgPERPENDICULAR','equal':'sgSAMELENGTH','tangent':'sgTANGENT'}


def native_value(row):
    value=row['value'];unit=row.get('unit')
    if type(value) is bool:
        if unit!='boolean':raise ValueError('boolean property requires explicit boolean unit')
        return value
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('finite native property required')
    if unit=='mm':return value/1000
    if unit=='deg':return math.radians(value)
    if unit=='count':
        if type(value) is not int or value<1:raise ValueError('positive integer count required')
        return value
    if unit=='ratio':return value
    raise ValueError('unsupported native property unit')


def validate_operations(features):
    for f in features:
        p=f.get('parameters',{})
        if f['kind'] in PROPERTIES:
            if p.get('mapping_confirmed') is not True or not p.get('mapping_source') or type(p.get('native_feature_id')) is not int:
                raise ValueError('reviewed version-specific feature-data mapping required')
            if not p.get('references') or not p.get('native_properties'):raise ValueError('feature selections and properties required')
            for name,row in p['native_properties'].items():
                if name not in PROPERTIES[f['kind']]:raise ValueError('unsupported feature-data property '+name)
                native_value(row)
        if f['kind']=='sketch':
            for constraint in p.get('constraints',[]):
                if constraint.get('confirmed') is not True or not constraint.get('source') or not constraint.get('references'):
                    raise ValueError('confirmed sourced sketch constraint required')
                if constraint['kind'] not in RELATIONS and constraint['kind']!='dimension':raise ValueError('unsupported sketch relation')
                if constraint['kind']=='dimension':
                    if constraint.get('unit') not in {'mm','deg'}:raise ValueError('driving dimension must be length or angle')
                    native_value(constraint)
                    xyz=constraint.get('position_mm')
                    if not isinstance(xyz,(list,tuple)) or len(xyz)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in xyz):raise ValueError('finite xyz dimension position required')


class FeatureOperationsMixin:
    def select_mapped(self,references):
        self.guard();self.model.ClearSelection2(True)
        for ref in references:
            if not ref.get('name') or not ref.get('type'):raise ValueError('named selection reference required')
            if not select_by_id(self.model.Extension,ref['name'],ref['type'],append=True,mark=ref.get('mark',0)):
                raise RuntimeError('native reference selection failed: '+ref['name'])

    def create_mapped_operation(self,feature):
        validate_operations([feature]);self.guard()
        p=feature['parameters'];self.select_mapped(p['references'])
        definition=self.model.FeatureManager.CreateDefinition(p['native_feature_id'])
        if definition is None:raise RuntimeError('CreateDefinition failed')
        for name,row in p['native_properties'].items():setattr(definition,name,native_value(row))
        native=self.model.FeatureManager.CreateFeature(definition)
        if native is None:raise RuntimeError('native '+feature['kind']+' creation failed')
        native.Name=feature['id'];self.model.ClearSelection2(True)
        return {'feature':feature['id'],'status':'created_pending_native_validation'}

    def apply_sketch_constraints(self,constraints):
        for row in constraints:
            self.select_mapped(row['references'])
            if row['kind']=='dimension':
                xyz=[v/1000 for v in row['position_mm']]
                if len(xyz)!=3:raise ValueError('dimension placement requires xyz')
                display=self.model.AddDimension2(*xyz)
                if display is None:raise RuntimeError('dimension creation failed')
                dimension=display.GetDimension2(0);value=native_value(row)
                if int(dimension.SetSystemValue3(value,1,None))!=0:raise RuntimeError('driving dimension rejected')
                if not math.isclose(float(dimension.SystemValue),value,rel_tol=1e-8,abs_tol=1e-9):raise RuntimeError('dimension readback mismatch')
            else:self.model.SketchAddConstraints(RELATIONS[row['kind']])
        self.model.ClearSelection2(True)


