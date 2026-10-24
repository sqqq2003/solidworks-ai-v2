"""Version-reviewed native feature definitions for remaining editable families."""
from .feature_operations import native_value

EXTRA={'revolve','hole','base_flange','edge_flange','sketched_bend','relief'}


def validate_extra(feature):
    p=feature.get('parameters',{})
    if feature['kind'] not in EXTRA:return
    if p.get('mapping_confirmed') is not True or not p.get('mapping_source') or type(p.get('native_feature_id')) is not int:
        raise ValueError('reviewed native feature definition required')
    if not p.get('references') or not p.get('native_properties'):raise ValueError('mapped selections/properties required')
    if feature['kind'] in {'base_flange','edge_flange','sketched_bend'}:
        for field in ('thickness_mm','radius_mm','k_factor','direction'):
            if p.get(field) is None:raise ValueError('missing bend input: '+field)
        if p['thickness_mm']<=0 or p['radius_mm']<0 or not 0<=p['k_factor']<=1:raise ValueError('invalid bend parameters')
    for name,row in p['native_properties'].items():
        if not name.isidentifier() or name.startswith('_'):raise ValueError('invalid native property')
        native_value(row)


class ExtraFeatureMixin:
    def create_extra_feature(self,feature):
        validate_extra(feature);self.guard();p=feature['parameters']
        self.select_mapped(p['references'])
        definition=self.model.FeatureManager.CreateDefinition(p['native_feature_id'])
        if definition is None:raise RuntimeError('native feature definition unavailable')
        for name,row in p['native_properties'].items():setattr(definition,name,native_value(row))
        native=self.model.FeatureManager.CreateFeature(definition)
        if native is None:raise RuntimeError('native '+feature['kind']+' creation failed')
        native.Name=feature['id']
        return {'feature':feature['id'],'kind':feature['kind'],'status':'created_pending_windows_validation'}
