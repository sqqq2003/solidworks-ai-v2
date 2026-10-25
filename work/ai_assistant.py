"""Model-provider configuration status or explicitly requested advisory chat."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ai_assistant import AIConfig,AssistantSession,AssistantError
from ai_assistant.tools import tool_definitions


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('status');sub.add_parser('tools')
    chat=sub.add_parser('chat');chat.add_argument('--request',type=Path,required=True)
    chat.add_argument('--out',type=Path)
    args=parser.parse_args(argv)
    try:
        config=AIConfig.from_env()
        if args.action=='status':report=dict(config.public_status(),status='review_required')
        elif args.action=='tools':report={'tools':tool_definitions(),'native_write_allowed':False}
        else:
            if args.out and (args.out.exists() or not args.out.parent.is_dir()):raise ValueError('output must be new')
            request=json.loads(args.request.read_text(encoding='utf-8-sig'))
            report=AssistantSession(config).chat(request['text'])
            if args.out:
                with args.out.open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False,indent=2,allow_nan=False)
        print(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False));return 3 if args.action=='chat' else 0
    except (AssistantError,ValueError,KeyError,TypeError,OSError) as exc:
        # Input/transport errors are sanitized; never dump a request or headers.
        message=str(exc) if isinstance(exc,AssistantError) else '请求文件、输出路径或参数无效。'
        print(json.dumps({'status':'review_required','error':message,'cad_executed':False},ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
