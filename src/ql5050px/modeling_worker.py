"""One worker lifetime per native part. External parent observes final exit."""
import json,sys
from pathlib import Path
from .native_part_host import run_native_part

def main():
    request=json.loads(Path(sys.argv[1]).read_text())
    result=run_native_part(request['sw_exe'],request['template'],request['plan'],sys.argv[2])
    print(json.dumps(result))
    return 0 if result['modeling']=='saved_reopened' and result['cleanup']=='owned_document_closed' else 1
if __name__=='__main__':raise SystemExit(main())
