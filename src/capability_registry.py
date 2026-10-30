"""Evidence-bound capability inventory. This module never launches CAD.

Evidence records are claims requiring human review, not authorization to write
CAD or a substitute for existing session and engineering safety gates.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
STAGES = ('simulation', 'solidworks', 'engineering')
SHA256 = re.compile(r'^[0-9a-f]{64}$')
MAX_FILE = 64 * 1024 * 1024
CATALOG = (
    ('dxf_overview', 'DXF 图纸概览', 'ezdxf / 只读', ('src/dxf_overview.py', 'src/desktop_ui.py')),
    ('drawing_analysis', 'DWG / DXF 图纸识别', 'ezdxf / SolidWorks 转换', ('src/cad_analyzer.py', 'src/dwg_converter.py')),
    ('sheet_metal', '钣金零件生成', 'SolidWorks COM', ('src/sheet_metal_pipeline.py', 'src/solidworks_generator.py')),
    ('roller', '滚筒零件生成', 'SolidWorks COM', ('src/roller_spec.py', 'src/solidworks_generator.py')),
    ('turned', '车削零件生成', 'SolidWorks COM', ('src/turned_generate.py', 'src/solidworks_generator.py')),
    ('assembly', '整机参数改型与配合', 'SolidWorks COM', ('src/a01_next/production.py', 'src/a01_next/native_production.py')),
    ('geometry_change', '尺寸与几何变化记录', 'SolidWorks COM / 离线比较',
     ('src/geometry_evidence.py', 'src/native_geometry_snapshot.py', 'src/a01_next/native_production.py', 'src/part_verification.py')),
    ('drawing_bom', '三视图与 BOM', 'SolidWorks COM', ('src/ql5050px/native_drawings.py', 'src/ql5050px/drawing_verification.py')),
)


def file_sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def selected_input(path: str | None) -> dict:
    if not path:
        return {'path': None, 'sha256': None, 'reason': '未选择输入文件'}
    try:
        target = Path(path).expanduser().resolve(strict=True)
        if not target.is_file() or target.stat().st_size > MAX_FILE:
            return {'path': str(target), 'sha256': None, 'reason': '不是文件或大于64 MB，未计算哈希'}
        return {'path': str(target), 'sha256': file_sha256(target), 'reason': None}
    except OSError as exc:
        return {'path': str(path), 'sha256': None, 'reason': f'无法读取输入文件：{exc}'}


def installed_file_version(path: str | None) -> dict:
    """Read executable metadata only; do not start or attach to SolidWorks."""
    if not path:
        return {'path': None, 'version': None, 'reason': '未选择 SolidWorks 程序'}
    try:
        target = Path(path).expanduser().resolve(strict=True)
        if not target.is_file() or target.name.casefold() != 'sldworks.exe':
            raise ValueError('请选择 SLDWORKS.exe')
        import win32api
        value = win32api.GetFileVersionInfo(str(target), '\\')
        ms, ls = value['FileVersionMS'], value['FileVersionLS']
        version = '.'.join(str(part) for part in (ms >> 16, ms & 65535, ls >> 16, ls & 65535))
        return {'path': str(target), 'version': version, 'reason': None,
                'basis': 'executable_file_version_not_running_session'}
    except Exception as exc:
        return {'path': str(path), 'version': None, 'reason': f'无法读取程序版本：{exc}'}


def _linked_claim(record, *, capability_id, stage, current_code, input_sha, sw_version, evidence_dir):
    """Check exact bindings; even a match is a claim pending independent review."""
    if not isinstance(record, dict) or record.get('capability_id') != capability_id or record.get('stage') != stage:
        return {'state': 'unverified', 'reason': '无匹配记录'}
    if record.get('result') != 'passed':
        return {'state': 'unverified', 'reason': '证据未声明通过'}
    try:
        timestamp = datetime.fromisoformat(str(record.get('tested_at', '')).replace('Z', '+00:00'))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError('timezone missing')
    except ValueError:
        return {'state': 'unverified', 'reason': '证据日期无效或缺少时区'}
    if not current_code or any(value is None for value in current_code.values()) or record.get('code_sha256') != current_code:
        return {'state': 'unverified', 'reason': '代码哈希不匹配'}
    if not input_sha or record.get('source_sha256') != input_sha:
        return {'state': 'unverified', 'reason': '输入文件哈希未匹配'}
    if stage != 'simulation' and (not sw_version or record.get('solidworks_version') != sw_version):
        return {'state': 'unverified', 'reason': 'SolidWorks 程序版本未匹配'}
    try:
        relative = Path(record.get('evidence_file', ''))
        if relative.is_absolute() or not relative.parts:
            raise ValueError('invalid evidence path')
        base = Path(evidence_dir).resolve(strict=True)
        evidence = (base / relative).resolve(strict=True)
        if not evidence.is_relative_to(base) or not evidence.is_file() or evidence.stat().st_size > MAX_FILE:
            raise ValueError('evidence outside store or unavailable')
        expected = record.get('evidence_sha256')
        if not isinstance(expected, str) or not SHA256.fullmatch(expected) or file_sha256(evidence) != expected:
            raise ValueError('evidence digest mismatch')
    except (OSError, ValueError, TypeError):
        return {'state': 'unverified', 'reason': '证据文件缺失、越界或哈希不匹配'}
    return {'state': 'linked_review_required', 'reason': '记录与当前文件匹配，仍需人工核验证据',
            'tested_at': timestamp.isoformat(), 'evidence_file': str(relative),
            'evidence_sha256': expected}


def build_capability_report(*, root: Path = ROOT, source_path=None, sw_exe=None,
                            records=None, evidence_dir=None, version_info=None) -> dict:
    root = Path(root).resolve()
    evidence_dir = Path(evidence_dir) if evidence_dir else root / 'runtime' / 'capability-evidence'
    input_info = selected_input(source_path)
    sw = version_info if version_info is not None else installed_file_version(sw_exe)
    records = records if isinstance(records, list) else []
    capabilities = []
    for cap_id, label, backend, files in CATALOG:
        hashes = {}
        for rel in files:
            target = root / rel
            try: hashes[rel] = file_sha256(target)
            except OSError: hashes[rel] = None
        claims = {}
        for stage in STAGES:
            candidates = [r for r in records if isinstance(r, dict) and r.get('capability_id') == cap_id and r.get('stage') == stage]
            # Never silently select a favorable record from conflicting claims.
            if len(candidates) > 1:
                claims[stage] = {'state':'unverified', 'reason':'存在多条记录，需要先人工整理'}
            else:
                claims[stage] = _linked_claim(candidates[0] if candidates else None,
                    capability_id=cap_id, stage=stage, current_code=hashes,
                    input_sha=input_info['sha256'], sw_version=sw.get('version'), evidence_dir=evidence_dir)
        capabilities.append({'id':cap_id,'label':label,'backend':backend,
                             'code_sha256':hashes,'evidence':claims})
    return {'schema_version':1, 'selected_input':input_info, 'solidworks':sw,
            'capabilities':capabilities, 'cad_executed':False, 'production_approved':False}


def load_records(root: Path = ROOT) -> tuple[list, str | None]:
    path = Path(root) / 'runtime' / 'capability-evidence' / 'index.json'
    if not path.exists():
        return [], None
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError('证据索引超过 1 MB')
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('records'), list):
            raise ValueError('证据索引格式无效')
        return data['records'], None
    except (OSError, ValueError, UnicodeError) as exc:
        return [], str(exc)


def format_capability_report(report: dict, *, load_error=None) -> str:
    sw = report['solidworks']; source = report['selected_input']
    lines = ['能力与验证状态', '模拟、实机和工程验收分别记录；证据匹配后仍需人工核对。',
             '', 'SolidWorks 程序版本：' + str(sw.get('version') or sw.get('reason') or '未验证'),
             '输入文件：' + str(source.get('path') or '未选择'),
             '输入 SHA256：' + str(source.get('sha256') or source.get('reason') or '未验证')]
    if load_error: lines.extend(['', '证据索引读取失败：' + load_error])
    names = {'simulation':'模拟测试','solidworks':'SolidWorks 实机','engineering':'工程验收'}
    for capability in report['capabilities']:
        lines.extend(['', capability['label'] + ' · ' + capability['backend']])
        for stage in STAGES:
            claim = capability['evidence'][stage]
            label = '凭据已匹配，待复核' if claim['state'] == 'linked_review_required' else '未验证'
            lines.append('  ' + names[stage] + '：' + label + '（' + claim['reason'] + '）')
    lines.extend(['', '文件版本只表示所选程序的版本，不代表实际连接的 SolidWorks 会话。',
                  '代码哈希覆盖各能力列出的关键文件，未覆盖全部依赖，仍需人工复核。',
                  '此清单不授权 CAD 写入，也不代表生产放行。'])
    return '\n'.join(lines)
