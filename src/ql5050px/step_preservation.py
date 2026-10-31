"""Narrow AP203 occurrence deletion without reserializing geometric entities.

IDs are diagnostic edit evidence, not stable model references. The caller must
prove the intended coincident occurrences independently. No automatic dedup.
"""
import hashlib
import re
from pathlib import Path


def statements(data):
    """Split Part 21 statements, respecting strings, doubled quotes and comments."""
    start = i = 0
    quoted = comment = False
    while i < len(data):
        if comment:
            if data[i:i+2] == b'*/':
                comment = False
                i += 2
            else:
                i += 1
            continue
        if quoted:
            if data[i:i+2] == b"''":
                i += 2
                continue
            if data[i] == 39:
                quoted = False
        elif data[i:i+2] == b'/*':
            comment = True
            i += 2
            continue
        elif data[i] == 39:
            quoted = True
        elif data[i] == 59:
            yield start, i+1, data[start:i+1]
            start = i+1
        i += 1
    if quoted or comment or data[start:].strip():
        raise ValueError('unterminated STEP statement')


def references(record):
    stripped = re.sub(rb"'(?:[^']|'')*'|/\*.*?\*/", b'', record, flags=re.S)
    return {int(n) for n in re.findall(rb'#(\d+)', stripped.split(b'=', 1)[-1])}


class StepDocument:
    def __init__(self, data):
        self.data = data
        self.sha256 = hashlib.sha256(data).hexdigest()
        self.records = {}
        self.spans = {}
        section = None
        data_sections = 0
        for start, end, raw in statements(data):
            text = re.sub(rb'/\*.*?\*/', b'', raw, flags=re.S).strip()
            if text == b'DATA;':
                data_sections += 1
                section = 'data'
            elif text == b'ENDSEC;':
                section = None
            elif section == 'data':
                match = re.fullmatch(rb'#(\d+)\s*=.*;', text, re.S)
                if not match:
                    raise ValueError('unsupported STEP data statement')
                key = int(match[1])
                if key in self.records:
                    raise ValueError('duplicate STEP entity ID')
                self.records[key] = raw
                self.spans[key] = (start, end)
        if data_sections != 1 or not self.records or not data.lstrip().startswith(b'ISO-10303-21;') or not data.rstrip().endswith(b'END-ISO-10303-21;'):
            raise ValueError('expected one complete Part 21 data section')
        self.validate()

    def validate(self):
        known = set(self.records)
        if any(references(record) - known for record in self.records.values()):
            raise ValueError('dangling STEP reference')

    def remove_occurrence_metadata(self, ids, *, expected_sha256, output, detach_axes=()):
        """Fail closed; validate all bytes/references before exclusively creating output."""
        if expected_sha256 != self.sha256:
            raise ValueError('source baseline hash mismatch')
        ids = set(ids)
        if not ids or any(type(n) is not int for n in ids) or not ids <= self.records.keys():
            raise ValueError('explicit existing entity IDs required')
        detach_axes = set(detach_axes)
        if not detach_axes <= ids or any(type(n) is not int for n in detach_axes):
            raise ValueError('detached axes must be explicitly deleted entities')
        for key in detach_axes:
            if not re.search(rb'=\s*AXIS2_PLACEMENT_3D\s*\(', self.records[key]):
                raise ValueError('only construction axes may be detached')
        edited = {}
        for key, record in self.records.items():
            if key in ids or not references(record) & detach_axes:
                continue
            match = re.search(rb"=\s*SHAPE_REPRESENTATION\s*\(\s*'(?:[^']|'')*'\s*,\s*\(([^()]*)\)", record)
            if not match:
                raise ValueError('axis still used outside an assembly item list')
            items = [int(n) for n in re.findall(rb'#(\d+)', match[1])]
            if not detach_axes & set(items):
                raise ValueError('axis is not an assembly representation item')
            remaining = [n for n in items if n not in detach_axes]
            if not remaining:
                raise ValueError('cannot empty assembly representation')
            edited[key] = record[:match.start(1)] + b', '.join(b'#'+str(n).encode() for n in remaining) + record[match.end(1):]
        allowed = (
            b'NEXT_ASSEMBLY_USAGE_OCCURRENCE', b'PRODUCT_DEFINITION_SHAPE',
            b'CONTEXT_DEPENDENT_SHAPE_REPRESENTATION', b'ITEM_DEFINED_TRANSFORMATION',
            b'CC_DESIGN_SECURITY_CLASSIFICATION',
        )
        placement_kinds = (b'AXIS2_PLACEMENT_3D', b'CARTESIAN_POINT', b'DIRECTION')
        placement_ids = set()
        for key in ids:
            expr = self.records[key].split(b'=', 1)[1].strip()
            ordinary = any(re.match(kind+rb'\s*\(', expr) for kind in allowed)
            code = re.sub(rb"'(?:[^']|'')*'|/\*.*?\*/",b'',expr,flags=re.S)
            types = re.findall(rb'([A-Z_][A-Z_0-9]*)\s*\(',code)
            complex_link = (expr.startswith(b'(') and len(types)==3 and set(types)=={
                b'REPRESENTATION_RELATIONSHIP',b'REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION',
                b'SHAPE_REPRESENTATION_RELATIONSHIP'})
            placement = any(re.match(kind+rb'\s*\(', expr) for kind in placement_kinds)
            if placement:
                placement_ids.add(key)
                continue
            if not ordinary and not complex_link:
                raise ValueError('geometric or unsupported entity deletion refused')
        # Only construction placements made unreachable by this edit may go.
        # A point/direction may never be deleted independently of such an axis.
        roots = {n for n in placement_ids if b'AXIS2_PLACEMENT_3D' in self.records[n]}
        reachable = set(roots)
        todo = list(roots)
        while todo:
            for ref in references(self.records[todo.pop()]) & placement_ids - reachable:
                reachable.add(ref)
                todo.append(ref)
        if reachable != placement_ids:
            raise ValueError('coordinate deletion without detached construction placement refused')
        if any(references(edited.get(n,record)) & placement_ids for n, record in self.records.items() if n not in ids):
            raise ValueError('construction placement is still referenced')
        spans = sorted((self.spans[n][0],self.spans[n][1],n) for n in ids | edited.keys())
        chunks = []
        cursor = 0
        for start, end, key in spans:
            chunks.append(self.data[cursor:start])
            if key in edited:chunks.append(edited[key])
            cursor = end
        candidate = b''.join(chunks) + self.data[cursor:]
        check = StepDocument(candidate)
        if set(check.records) != set(self.records)-ids or any(
                edited.get(key,record).strip() != check.records[key].strip()
                for key, record in self.records.items() if key not in ids):
            raise ValueError('retained STEP entities changed')
        output = Path(output)
        # Parent creation and file creation occur only after candidate validation.
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open('xb') as stream:
            stream.write(candidate)
        return {'source_sha256': self.sha256, 'output_sha256': check.sha256,
                'removed_entities': sorted(ids), 'retained_entities': len(check.records),
                'removed_detached_placement_entities': sorted(placement_ids),
                'edited_assembly_item_lists': sorted(edited),
                'retained_entity_bytes_identical': not edited,
                'retained_unedited_entity_bytes_identical': True, 'geometry_reserialized': False,
                'requires_native_validation': True, 'production_approved': False}
