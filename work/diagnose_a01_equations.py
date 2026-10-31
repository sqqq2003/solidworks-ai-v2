"""Offline audit of Gork equation evidence; no SolidWorks writes."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.sw_api.equation_health import analyze_equations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dump', type=Path)
    args = parser.parse_args()
    data = json.loads(args.dump.read_text(encoding='utf-8-sig'))
    report = analyze_equations(data['equations'], data.get('dimensions_mm'))
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report['status'] == 'equations_and_linked_dimensions_verified' else 3


if __name__ == '__main__':
    raise SystemExit(main())
