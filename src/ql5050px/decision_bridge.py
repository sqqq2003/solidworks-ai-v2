"""Convert reviewed decisions into existing drive and assembly planning inputs."""
from copy import deepcopy
from pathlib import PureWindowsPath

from .assembly_builder import finite, validate_transform


def same_document(left, right):
    return str(PureWindowsPath(left)).casefold() == str(PureWindowsPath(right)).casefold()


def bridge_decisions(intelligence, config, bindings=None):
    """Return a copy, provenance and blockers; never approve or execute CAD writes.

    Resize dimensions use approved snapshot targets. Translations require an
    explicitly reviewed assembly/occurrence binding and an absolute mm position.
    """
    config = deepcopy(config)
    bindings = bindings or {}
    pending, converted = [], []
    drive = config.setdefault('drive', {})
    nodes = drive.setdefault('nodes', {})
    baseline = drive.setdefault('baseline', {})
    components = drive.setdefault('components', [])
    tree = config.get('assembly_tree', {})
    catalog = tree.get('catalog', {})
    root = catalog.get(tree.get('root'), {})
    if root.get('source_path') and root.get('configuration'):
        drive.setdefault('source_assembly', root['source_path'])
        drive.setdefault('assembly_configuration', root['configuration'])
    unresolved = {row['document'] for row in intelligence['decision_plan']['pending_mapping']}
    for index, action in enumerate(intelligence['decision_plan']['actions']):
        key = action['document']
        document = intelligence['database']['documents'][key]
        kind = action['action']
        def block(reason):
            pending.append({'module':'decision_bridge','document':key,'action':kind,'reason':reason})
        if kind == 'keep':
            if action['changes']:
                block('keep action contains dimension changes')
            continue
        if key in unresolved:
            block('all requested targets must be explicitly approved')
            continue
        if kind == 'resize':
            known_nodes = [node for node in catalog.values() if node.get('source_path')
                           and same_document(node['source_path'],document['path'])
                           and node.get('configuration') == document['configuration']]
            known_components = [c for c in components if c.get('document')
                                and same_document(c['document'],document['path'])
                                and c.get('configuration') == document['configuration']]
            if (document.get('component_kind') != 'editable' or document.get('protected_interface')
                    or any(n.get('component_kind') != 'editable' or n.get('protected_interface')
                           for n in known_nodes+known_components)):
                block('protected document cannot be resized')
                continue
            if document.get('exists') is not True or not document.get('configuration'):
                block('existing source document and configuration required')
                continue
            edits = []
            targets = set()
            for change in action['changes']:
                approved = [c for row in intelligence['mapping_report']['mappings']
                            if row['parameter'] == change['parameter'] for c in row['candidates']
                            if c['document_id'] == key and c['dimension'] == change['dimension']
                            and c.get('review_status') == 'confirmed']
                if len(approved) != 1 or not approved[0].get('approval_source'):
                    raise ValueError('bridge requires a unique sourced approval')
                unit = change['unit']
                if unit not in {'mm','m','deg'}:
                    raise ValueError('unsupported native dimension unit')
                before, after = finite(change['before']), finite(change['after'])
                if unit in {'mm','m'} and (before <= 0 or after <= 0):
                    raise ValueError('length dimensions must be positive')
                factor = 1000 if unit == 'm' else 1
                target = change['dimension']
                if not isinstance(target, str) or not target or target in targets:
                    raise ValueError('duplicate or empty native dimension target')
                targets.add(target)
                # Existing bindings must not compete with a generated edit.
                for component in components:
                    if (component.get('document') and same_document(component['document'],document['path'])
                            and component.get('configuration') == document['configuration']):
                        if any(b.get('target') == target for b in component.get('bindings', [])):
                            raise ValueError('existing drive binding conflicts with decision target')
                edits.append((change, before*factor, after*factor, 'mm' if unit == 'm' else unit, approved[0]))
            if not edits:
                block('resize has no approved changes')
                continue
            component_id = 'decision_'+str(index)
            if any(c['id'] == component_id for c in components):
                raise ValueError('generated decision component id collision')
            component = {'id':component_id,'component_kind':'editable',
                         'document':document['path'],'configuration':document['configuration'],'bindings':[]}
            for number, (change, before, after, unit, approval) in enumerate(edits):
                name = component_id+'_'+str(number)
                if name in nodes or name in baseline or name in drive.get('inputs', {}):
                    raise ValueError('generated decision parameter collision')
                nodes[name] = {'unit':unit,'value':after,'status':'confirmed',
                               'source':approval['approval_source']}
                baseline[name] = before
                component['bindings'].append({'parameter':name,'role':'dimension',
                                             'target':change['dimension'],'mapping_status':'confirmed'})
                converted.append({'document':key,'action':'resize','parameter':change['parameter'],
                                  'drive_parameter':name,'approval_source':approval['approval_source']})
            components.append(component)
        elif kind == 'translate':
            binding = bindings.get(key, {})
            owner = catalog.get(binding.get('assembly'), {})
            matches = [o for o in owner.get('children', []) if o['id'] == binding.get('occurrence')]
            if binding.get('reviewed') is not True or not binding.get('source') or len(matches) != 1:
                block('reviewed assembly/occurrence binding required')
                continue
            occurrence = matches[0]
            node = catalog.get(occurrence['ref'], {})
            if document.get('exists') is not True or not node.get('source_path') or not same_document(node['source_path'],document['path']) or node.get('configuration') != document['configuration']:
                block('occurrence does not match scanned document/configuration')
                continue
            if action['changes']:
                block('translate cannot include dimension changes')
                continue
            if (document.get('component_kind') in {'fixed','purchased','standard'} or document.get('protected_interface')
                    or node.get('component_kind') != 'editable' or node.get('protected_interface')):
                if binding.get('allow_reposition') is not True:
                    block('protected occurrence requires explicit reposition permission')
                    continue
            position = action['translation_mm']
            if not isinstance(position, (list,tuple)) or len(position) != 3:
                raise ValueError('translation_mm must be three absolute coordinates')
            if occurrence.get('transform_mm') is None:
                block('original rigid occurrence transform required')
                continue
            transform = validate_transform(occurrence['transform_mm'])
            before = transform[9:12]
            transform[9:12] = [finite(v) for v in position]
            occurrence['transform_mm'] = transform
            converted.append({'document':key,'action':'translate','binding':deepcopy(binding),
                              'before_mm':before,'after_mm':transform[9:12]})
        else:
            block('action requires manual native implementation/review')
    return config, {'converted':converted,'pending_mapping':pending,'native_write_allowed':False}
