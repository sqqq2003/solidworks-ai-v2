"""Whole-project capability, environment and serial job-manifest entrypoint."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/'src')]
from project_workbench import capabilities, doctor, run_batch, write_report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='command',required=True)
    commands.add_parser('status')
    commands.add_parser('doctor')
    batch = commands.add_parser('batch')
    batch.add_argument('manifest',type=Path)
    batch.add_argument('--reports',type=Path,default=ROOT/'runtime/project-reports')
    args = p.parse_args()
    try:
        if args.command == 'status':
            report = capabilities()
        elif args.command == 'doctor':
            report = doctor()
        else:
            data = json.loads(args.manifest.read_text(encoding='utf-8-sig'))
            if data.get('schema_version') != 1:
                raise ValueError('unsupported job manifest schema')
            jobs = data['jobs']
            for job in jobs:
                for key in ('source','output','sw_exe'):
                    if key in job and not Path(job[key]).is_absolute():
                        job[key] = str((args.manifest.resolve().parent/job[key]).resolve())
            report = run_batch(jobs)
            report['report_file'] = str(write_report(report,args.reports))
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 1 if report.get('status') == 'failed' else (3 if report.get('status') == 'review_required' else 0)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'failed','error':str(exc)},ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
