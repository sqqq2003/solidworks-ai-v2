"""Audit two native K variants without assuming a changed flat bounding box."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from k_factor_evidence import audit_variants


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('evidence', type=Path)
    p.add_argument('--basis', choices=('fixed_blank', 'fixed_outside_legs'))
    p.add_argument('--thickness', type=float, required=True)
    p.add_argument('--radius', type=float, required=True)
    p.add_argument('--angle', type=float, required=True)
    args = p.parse_args()
    report = audit_variants(json.loads(args.evidence.read_text(encoding='utf-8-sig')),
        geometry_basis=args.basis, thickness_mm=args.thickness, radius_mm=args.radius, angle_degrees=args.angle)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 3  # Evidence audit is never mechanical acceptance.


if __name__ == '__main__':
    raise SystemExit(main())
