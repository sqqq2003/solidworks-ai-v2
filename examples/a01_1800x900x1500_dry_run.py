#!/usr/bin/env python3
"""Load the A01 spec, solve 1800×900×1500, and dry-run the mock SolidWorks adapter.

This does not open SolidWorks. Unmapped OEM dimensions stay null.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.a01_parametric.cli import main


if __name__ == "__main__":
    raise SystemExit(
        main(
            [
                "--length",
                "1800",
                "--width",
                "900",
                "--height",
                "1500",
                "--dry-run",
            ]
        )
    )
