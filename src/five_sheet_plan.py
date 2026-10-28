"""Plan the five legacy drawing outputs without manufacturing assumptions."""
from __future__ import annotations

import hashlib
from pathlib import Path

SHEETS = (
    ('钣金图', ('sheet_metal', 'views', 'title', 'frame')),
    ('方管图', ('tube', 'views', 'title', 'frame')),
    ('明细图', ('bom', 'views', 'title', 'frame')),
    ('总图', ('views', 'tube', 'bom', 'title', 'frame')),
    ('三视图', ('views', 'title', 'frame')),
)


def inspect_dxf(path):
    """Record the actual file identity and layer inventory; no CAD operation."""
    import ezdxf
    file = Path(path).expanduser().resolve(strict=True)
    if not file.is_file() or file.suffix.casefold() != '.dxf':
        raise ValueError('请选择 DXF 图纸工作副本')
    def sha():
        with file.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    before = sha()
    doc = ezdxf.readfile(file)
    counts = {}
    for entity in doc.modelspace():
        layer = str(entity.dxf.get('layer', '0'))
        counts[layer] = counts.get(layer, 0) + 1
    if sha() != before:
        raise ValueError('读取时图纸发生变化，请重新检查')
    return {'path': str(file), 'sha256': before, 'dxf_units': doc.units,
            'entity_count': sum(counts.values()), 'layers': dict(sorted(counts.items()))}


def plan_five_sheets(source, *, component_evidence=None):
    """Report explicit missing inputs; plans never authorize or create outputs."""
    inventory = inspect_dxf(source)
    evidence = component_evidence or {}
    if not isinstance(evidence, dict):
        raise ValueError('区域证据必须是映射')
    rows = []
    for name, components in SHEETS:
        # Evidence must be supplied explicitly. A label or populated layer alone
        # cannot establish what belongs to a view, BOM or a cut-list.
        missing = [item for item in components if evidence.get(item) is not True]
        rows.append({'name': name, 'components': list(components),
                     'missing_confirmed_components': missing, 'status': '待审核'})
    return {'source': inventory, 'sheets': rows, 'cad_executed': False,
            'geometry_generated': False, 'production_approved': False,
            'note': '模板只用于版式核对；模型尺寸、零件与 BOM 必须另行验证。'}
