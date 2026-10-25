# Deferred original feature contracts

These original feature contracts (36 cases across three modules) were previously retained
because their target geometry interfaces were absent from the uploaded source. They are now
implemented and passing.

## Status: IMPLEMENTED (offline)

All 36 cases pass on the cloud/offline path. No SolidWorks machine verification has been
performed — as always, "cloud pass" is NOT "machine pass".

| file                        | cases | status      | target interfaces |
|-----------------------------|-------|-------------|-------------------|
| `test_border_relief_notch.py` | 9   | implemented | `convert_border_hole_to_notch`, `apply_rectangular_relief_expansion`, `ensure_intersection_reliefs`, `expand_rectangular_relief_notches` (solidworks_generator) |
| `test_spur_segments.py`       | 5   | implemented | `_is_drawing_artifact_loop` (solidworks_generator), `sanitize_closed_profile` (profile_sanitize) |
| `test_turned_part.py`         | 22  | implemented | `DrawingDimension`/`dimensions` (cad_analyzer), `_radius_ladder`/`_axial_lengths`/`_detect_bore`/`_tap_drill_diameter`/`_thread_depth`/`_world_point` (turned_part) |

## How to run

```
python -m unittest discover -s tests/pending_features -v
```

The import bootstrap now points `src/` at the repo root (`parents[2]`), so discovery works
standalone without setting `PYTHONPATH`.

## Notes

- The dimension-driven turned-part path is only activated when `analysis.dimensions` is
  non-empty, so existing regression cases (no dimensions) are unaffected.
- Not included in the main regression suite (`no __init__.py`); run explicitly as above.
