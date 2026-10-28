"""Read the old GT-ZX specification CSV as unconfirmed planning data."""
import csv
import hashlib
import io
import math
from pathlib import Path

ALIASES = {
    'Length': ('Length', '长度', '机长'), 'Width': ('Width', '宽度', '机宽'),
    'Height': ('Height', '高度', '机高'), 'FootHeight': ('FootHeight', '脚杯高', '脚高'),
    'RollerLong': ('RollerLong', '长滚筒', '动力滚筒长'),
    'RollerShort': ('RollerShort', '短滚筒', '分段滚筒长'),
    'RollerLongExtra': ('RollerLongExtra', '滚筒宽余量'),
    'Beam692Extra': ('Beam692Extra', '横梁692余量'),
    'Beam682Extra': ('Beam682Extra', '方管682余量'),
    'ColumnExtra': ('ColumnExtra', '立柱扣减'), 'SheetTrim': ('SheetTrim', '钣金长扣减'),
    'side': ('靠左/靠右', '方向'), 'spec_name': ('规格名称', '机型代号', '输出名'),
    'machine_type': ('机型类型',),
}


def read_legacy_csv(path):
    file = Path(path).expanduser().resolve(strict=True)
    if file.suffix.casefold() != '.csv' or not file.is_file():
        raise ValueError('请选择改机规格 CSV 文件')
    data = file.read_bytes()
    if len(data) > 5 * 1024 * 1024: raise ValueError('规格表超过 5 MB')
    rows = list(csv.reader(io.StringIO(data.decode('utf-8-sig'), newline='')))
    if len(rows) < 2 or len(rows) > 10001: raise ValueError('规格表没有数据或行数过多')
    headers = [str(x).strip() for x in rows[0]]
    if len(headers) != len(set(headers)): raise ValueError('规格表存在重复列名')
    indices = {}
    for key, aliases in ALIASES.items():
        hits = [headers.index(x) for x in aliases if x in headers]
        if len(hits) > 1: raise ValueError('同一参数有多个别名列：' + key)
        if hits: indices[key] = hits[0]
    if not all(k in indices for k in ('Length','Width','Height')):
        raise ValueError('缺少长、宽或高列')
    specs = []
    for number, cells in enumerate(rows[1:], 2):
        if not any(str(c).strip() for c in cells): continue
        values = {}
        for key, index in indices.items():
            text = cells[index].strip() if index < len(cells) else ''
            if not text: continue
            if key not in {'side','spec_name','machine_type'}:
                try: value = float(text.replace(',', ''))
                except ValueError: raise ValueError(f'第 {number} 行 {key} 不是数字') from None
                if not math.isfinite(value) or value <= 0: raise ValueError(f'第 {number} 行 {key} 必须为正的有限数值')
                values[key] = value
            else: values[key] = text
        if any(k not in values for k in ('Length','Width','Height')):
            raise ValueError(f'第 {number} 行缺少长、宽或高')
        specs.append({'row': number, 'values': values, 'confirmed': False})
    if not specs: raise ValueError('规格表没有非空数据行')
    return {'source': str(file), 'sha256': hashlib.sha256(data).hexdigest(), 'specs': specs,
            'units': 'mm', 'cad_executed': False, 'production_approved': False,
            'note': '旧表数据仅供规划；空白项不套用旧程序默认值。'}
