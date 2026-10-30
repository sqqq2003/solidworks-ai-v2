"""Read-only drawing inventory; never creates CAD or approves dimensions."""
from __future__ import annotations

from collections import Counter
import hashlib
import math
from pathlib import Path
import re

import ezdxf

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_ENTITIES = 250_000
MAX_TEXTS = 100
MAX_WARNINGS = 100
_NUMBER = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$')


def _digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inspect_dxf(path: str | Path) -> dict:
    """Describe model-space entities and explicit dimension overrides.

    A stored DXF measurement is not independently measured geometry: its
    coordinate system, scaling and freshness require engineering review.
    """
    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file() or source.suffix.casefold() != '.dxf':
        raise ValueError('请选择 DXF 文件；DWG 请先转换为 DXF。')
    if source.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('文件超过 50 MB，无法在图纸概览中处理。')
    before = _digest(source)
    document = ezdxf.readfile(source)
    model = document.modelspace()
    if len(model) > MAX_ENTITIES:
        raise ValueError('图纸实体过多，请先拆分后再查看概览。')
    types, layers, texts, mismatches = Counter(), Counter(), [], []
    warning_count = 0
    for entity in model:
        kind = entity.dxftype()
        layer = str(entity.dxf.get('layer', '0'))
        types[kind] += 1
        layers[layer] += 1
        if kind in {'TEXT', 'MTEXT'} and len(texts) < MAX_TEXTS:
            raw = entity.dxf.get('text', '') if kind == 'TEXT' else entity.plain_text()
            value = ' '.join(str(raw).split())[:500]
            if value:
                texts.append({'layer': layer, 'text': value})
        if kind != 'DIMENSION':
            continue
        override = str(entity.dxf.get('text', '')).strip()
        stored = entity.dxf.get('actual_measurement', None)
        if not _NUMBER.fullmatch(override) or stored is None:
            continue
        try:
            display, measurement = float(override), float(stored)
        except (TypeError, ValueError, OverflowError):
            continue
        if not (math.isfinite(display) and math.isfinite(measurement)):
            continue
        if not math.isclose(display, measurement, rel_tol=1e-9, abs_tol=1e-6):
            warning_count += 1
            if len(mismatches) < MAX_WARNINGS:
                mismatches.append({'handle': str(entity.dxf.get('handle', '')),
                    'layer': layer, 'display_override': override,
                    'stored_measurement': measurement,
                    'unit': 'mm' if document.units == 4 else 'unconfirmed'})
    layouts=[]
    for layout in document.layouts:
        if layout.name.casefold()=='model':
            continue
        count=len(layout)
        if count > MAX_ENTITIES:
            layouts.append({'name':layout.name,'entity_count':count,'entity_types':None,'status':'too_many_entities'})
            continue
        layouts.append({'name':layout.name,'entity_count':count,
                        'entity_types':dict(sorted(Counter(entity.dxftype() for entity in layout).items())),
                        'status':'inventory_only'})
    if _digest(source) != before:
        raise ValueError('读取期间文件发生变化，请重新检查。')
    return {'schema_version': 1, 'status': 'review_required', 'source': str(source),
        'sha256': before, 'dxf_units_code': document.units,
        'unit_label': 'mm' if document.units == 4 else 'unconfirmed',
        'scope': 'modelspace_only', 'entity_count': len(model),
        'entity_types': dict(sorted(types.items())), 'layers': dict(sorted(layers.items())),
        'paper_layouts': layouts,
        'texts': texts, 'texts_limit': MAX_TEXTS,
        'dimension_mismatches': mismatches, 'dimension_mismatch_count': warning_count,
        'dimension_mismatches_truncated': warning_count > MAX_WARNINGS,
        'geometry_verified': False, 'production_approved': False,
        'caveats': ['只读概览不提取完整轮廓，也不验证零件或尺寸。',
            '显示标注与DXF存储测量值不同仅提示复核，不判定哪个值正确。',
            '布局仅统计实体种类和数量，未核对布局中的标注、几何或块内文字。',
            '块内文字和外部引用未展开检查。']}


def format_overview(result: dict) -> str:
    lines = ['只读图纸概览 · 待复核', f"文件：{result['source']}",
        f"实体：{result['entity_count']}  单位：{result['unit_label']}  范围：模型空间",
        '', '图层：']
    lines.extend(f'  {name}: {count} 个实体' for name, count in result['layers'].items())
    lines.extend(['', f"模型空间标注显示与存储测量值不同：{result['dimension_mismatch_count']} 处"])
    for row in result['dimension_mismatches']:
        lines.append(f"  图层 {row['layer']} / 标注 {row['handle']}：显示 {row['display_override']}，存储值 {row['stored_measurement']:g} {row['unit']}")
    if result['dimension_mismatches_truncated']:
        lines.append('  差异数量较多，仅显示前 100 处。')
    lines.extend(['', '图纸布局（仅统计，未识别内容）：'])
    for layout in result.get('paper_layouts',[]):
        lines.append(f"  {layout['name']}: {layout['entity_count']} 个实体" + ('（数量过多，未统计类型）' if layout['status']=='too_many_entities' else ''))
    if any(layout['entity_count'] for layout in result.get('paper_layouts',[])):
        lines.append('  布局中有内容，当前概览和图形预览不检查布局；请在 CAD 中核对。')
    lines.extend(['', '图中文字（最多100条）：'])
    lines.extend('  ' + item['text'] for item in result['texts'])
    lines.extend(['', *result['caveats'], '本结果不能作为生产参数或制造放行依据。'])
    return '\n'.join(lines)


def preview_geometry(path: str | Path, expected_sha256: str) -> dict:
    """Build a bounded, approximate 2D visual preview, never manufacturing geometry."""
    from ezdxf import path as dxf_path
    source = Path(path).expanduser().resolve(strict=True)
    if source.suffix.casefold() != '.dxf' or source.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('只能预览不超过 50 MB 的 DXF 文件。')
    if _digest(source) != expected_sha256:
        raise ValueError('文件已改变，请重新打开图纸。')
    document = ezdxf.readfile(source)
    model = document.modelspace()
    if len(model) > MAX_ENTITIES:
        raise ValueError('图纸实体过多，无法预览。')
    supported = {'LINE','ARC','CIRCLE','LWPOLYLINE','POLYLINE','ELLIPSE','SPLINE'}
    paths, omitted, points_used = [], Counter(), 0
    max_paths, max_points = 10000, 120000
    truncated = False
    for entity in model:
        kind = entity.dxftype()
        if kind not in supported:
            omitted[kind] += 1
            continue
        if len(paths) >= max_paths or points_used >= max_points:
            truncated = True
            break
        try:
            # ezdxf converts curves to bounded line segments for a visual preview.
            from itertools import islice
            coords = [(float(p.x), float(p.y)) for p in islice(
                dxf_path.make_path(entity).flattening(distance=0.5, segments=4),
                max_points - points_used + 1)]
            if len(coords) > max_points - points_used:
                truncated = True
                break
            if len(coords) < 2 or not all(math.isfinite(v) for point in coords for v in point):
                omitted[kind] += 1
                continue
            points_used += len(coords)
            paths.append({'layer':str(entity.dxf.get('layer','0')), 'points':coords})
        except (ValueError, TypeError, AttributeError, NotImplementedError):
            omitted[kind] += 1
    if _digest(source) != expected_sha256:
        raise ValueError('读取期间文件发生变化，请重新打开图纸。')
    return {'paths':paths,'omitted':dict(omitted),'truncated':truncated,
            'source_sha256':expected_sha256}
