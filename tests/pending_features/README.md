# Deferred original feature contracts

One original test file still requires algorithms absent from the uploaded source. It is
retained verbatim apart from the import bootstrap, excluded from regression discovery
(no `__init__.py`), and must not be counted as passes. Run
`python -m unittest discover -s tests/pending_features -v` to reproduce the import error.

[
  {
    "file": "test_turned_part.py",
    "cases": 22,
    "reason": "Needs cad_analyzer.DrawingDimension plus a DrawingAnalysis.dimensions field (DIMENSION entities are not read today) and turned_part._axial_lengths / turned_part._radius_ladder, none of which exist in the uploaded snapshot; retained for separate feature development, not counted as passing."
  }
]

## Promoted out of this folder

`test_spur_segments.py` (5 cases) and `test_border_relief_notch.py` (9 cases) were blocked
only by a wrong import bootstrap depth (`parents[1]` instead of `parents[2]` from this
subfolder) plus two functions documented in `src/CHANGELOG.md` but missing from the
uploaded snapshot: `solidworks_generator._is_drawing_artifact_loop` and
`solidworks_generator.convert_border_hole_to_notch`. Both were rebuilt to the recorded
semantics (artifact loop = closed loop with max edge <= 2 mm and area <= 0.6 mm2; border
relief hole becomes an outer-contour notch, three square sides, <= 0.75 mm gaps stretched
to the border, < 80 % edge coverage stays a hole). They now live in `tests/` and run in
regression. Offline passes only - no SolidWorks run confirms the generated parts.
