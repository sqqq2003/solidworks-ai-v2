# Deferred original feature contracts

These original tests require algorithms absent from the uploaded source. They are retained verbatim apart from import bootstrap, excluded from regression discovery (no __init__.py), and must not be counted as passes. Run `python -m unittest discover -s tests/pending_features -v` to reproduce the three module import errors.

[
  {
    "file": "test_border_relief_notch.py",
    "cases": 9,
    "reason": "Original test snapshot targets geometry interfaces absent from the uploaded implementation; retained for separate feature development, not counted as passing."
  },
  {
    "file": "test_spur_segments.py",
    "cases": 5,
    "reason": "Original test snapshot targets geometry interfaces absent from the uploaded implementation; retained for separate feature development, not counted as passing."
  },
  {
    "file": "test_turned_part.py",
    "cases": 22,
    "reason": "Original test snapshot targets geometry interfaces absent from the uploaded implementation; retained for separate feature development, not counted as passing."
  }
]