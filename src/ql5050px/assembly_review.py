"""Read-only instance/BOM summary. No hard-coded missing-part baseline."""
from collections import Counter, defaultdict

STATES = frozenset({'loaded', 'missing', 'suppressed', 'lightweight', 'unloaded', 'unknown'})


def summarize_instances(instances, *, source_sha256, configuration, aabb_candidates=None):
    if (not isinstance(source_sha256, str) or len(source_sha256) != 64
            or any(c not in '0123456789abcdef' for c in source_sha256)):
        raise ValueError('assembly baseline SHA256 required')
    if not isinstance(configuration, str) or not configuration.strip():
        raise ValueError('assembly configuration required')
    if not isinstance(instances, list) or len(instances) > 100000:
        raise ValueError('bounded explicit assembly instance list required')
    seen, counts, groups, blockers = set(), Counter(), defaultdict(list), []
    for row in instances:
        if not isinstance(row, dict):
            raise ValueError('instance must be an object')
        key = row.get('component_path')
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError('unique full component instance path required')
        seen.add(key)
        state = row.get('load_state', 'unknown')
        if state not in STATES:
            raise ValueError('unsupported instance load state')
        counts[state] += 1
        if state != 'loaded':
            blockers.append({'component_path': key, 'reason': state})
        number, config = row.get('part_number'), row.get('configuration')
        if not isinstance(number, str) or not number or not isinstance(config, str) or not config:
            blockers.append({'component_path': key, 'reason': 'bom_identity_unconfirmed'})
            continue
        groups[(number, config)].append(row)
    bom = []
    for (number, config), rows in sorted(groups.items()):
        hashes = {r.get('document_sha256') for r in rows}
        valid_hashes = {h for h in hashes if isinstance(h, str) and len(h) == 64
                        and all(c in '0123456789abcdef' for c in h)}
        if len(valid_hashes) != 1 or len(hashes) != 1:
            blockers.append({'part_number': number, 'configuration': config,
                             'reason': 'bom_document_identity_missing_or_conflicting'})
        bom.append({'part_number': number, 'configuration': config,
                    'instance_count': len(rows), 'unit': 'count',
                    'load_states': dict(Counter(r.get('load_state', 'unknown') for r in rows)),
                    'component_paths': [r['component_path'] for r in rows],
                    'status': 'candidate_not_manufacturing_bom'})
    if not instances:
        blockers.append({'reason': 'assembly_inventory_empty'})
    return {'schema_version': 1, 'source_sha256': source_sha256, 'configuration': configuration,
        'instance_count': len(instances), 'load_state_counts': dict(counts),
        'bom_candidates': bom, 'blockers': blockers,
        'aabb_candidates': aabb_candidates if aabb_candidates is not None else [],
        'status': 'blocked' if blockers else 'inventory_complete_pending_native_review',
        'cad_executed': False, 'production_approved': False,
        'not_checked': ['native_mate_solution', 'exact_interference', 'motion', 'strength',
                        'weldment_cut_list', 'manufacturing_bom_signoff'],
        'assumptions': ['Input instance inventory is a caller-supplied observation.',
                        'Suppressed and unloaded instances remain visible in the count.',
                        'AABB overlap is a screening candidate, not native interference.']}
