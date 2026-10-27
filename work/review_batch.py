"""Offline sheet review CLI. Every edit creates a new file; no CAD execution."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def main(argv=None):
    parser = argparse.ArgumentParser(description='钣金批量审核：只读识别、参数确认、清单检查；不执行CAD')
    commands = parser.add_subparsers(dest='action', required=True)
    prepare = commands.add_parser('prepare', help='从 DXF 建立候选审核清单')
    prepare.add_argument('--source', required=True)
    prepare.add_argument('--output', required=True)
    for action in ('parameter', 'select'):
        command = commands.add_parser(action, help='记录确认并另存新清单')
        command.add_argument('--manifest', required=True)
        command.add_argument('--part', required=True)
        command.add_argument('--actor', required=True)
        command.add_argument('--output', required=True)
        if action == 'parameter':
            command.add_argument('--key', required=True)
            command.add_argument('--value', required=True, help='数值或策略文本')
            command.add_argument('--source-note', required=True)
        else:
            command.add_argument('--include', choices=('yes', 'no'), required=True)
            command.add_argument('--reason', required=True)
    check = commands.add_parser('check', help='检查清单是否完整；不是测试或实机验收')
    check.add_argument('--manifest', required=True)
    check.add_argument('--source', help='移动目录后重新指定相同内容的源文件')
    plans = commands.add_parser('plan-jobs', help='转换为现有工作台规划任务，不生成零件')
    plans.add_argument('--manifest', required=True)
    plans.add_argument('--source')
    commands.add_parser('integration', help='显示 I01–I08 代码融合状态')
    args = parser.parse_args(argv)
    try:
        from batch_review_manifest import (create_manifest, load_manifest, save_manifest,
                                          select_part, set_parameter, validate_manifest)
        if args.action == 'integration':
            from skill_integration import integration_status
            result = integration_status()
        elif args.action == 'prepare':
            result = create_manifest(args.source)
            save_manifest(result, args.output)
        else:
            result = load_manifest(args.manifest)
            if args.action == 'plan-jobs':
                from batch_review_manifest import compile_plan_jobs
                result = compile_plan_jobs(result, source=args.source)
            elif args.action == 'check':
                result = validate_manifest(result, source=args.source)
            else:
                if args.action == 'parameter':
                    value = args.value if args.key == 'hole_policy' else float(args.value)
                    set_parameter(result, args.part, key=args.key, value=value,
                                  source=args.source_note, actor=args.actor)
                else:
                    select_part(result, args.part, included=args.include == 'yes',
                                actor=args.actor, reason=args.reason)
                save_manifest(result, args.output)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
        return 3 if result.get('status') == 'blocked' else 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({'status': 'failed', 'message': str(error),
                          'cad_executed': False}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
