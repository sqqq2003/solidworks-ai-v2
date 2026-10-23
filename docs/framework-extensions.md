# Framework extensions (after the Issue #6 five modules)

Additive layers built on top of the Issue #6 offline framework. None of them
starts SolidWorks, and every output keeps its `cad_executed=False` /
`sw_live=not_applicable_on_linux` markers.

| # | Extension | Entry | Honesty boundary |
|---|-----------|-------|------------------|
| 1 | Machine registry | `src/machine_registry.py`, `data/machines/index.json` | Structural index only; never invents or copies confirmed dimensions |
| 2 | Material data | `src/material_data.py`, `data/material_properties.json`, `data/k_factor_table.json` | Confirmed rows only; K ships with **no** production rows; missing → unresolved, never a default |
| 3 | Estimate | `src/sheetmetal_estimate.py`, `data/labor_rates.json` | `estimate_only`; every rate is a labeled planning assumption, not a quote |
| 4 | Drawing numbers | `src/drawing_numbers.py` | Monotonic, journaled; an issued number is never reused for another part |
| 5 | Mate-chain pre-check | `src/a01_next/mate_chain.py` | Data-model checks only; `mates_solved=False`; no solver, no motion, no exact interference |
| 6 | Schema validation | `src/schema_validate.py`, `docs/schemas/` | Dependency-free validator for the schema subset used by module outputs |
| 7 | Unified CLI | `swctl.py` | Thin dispatch over the modules above; one JSON document per command |
| 8 | Live smoke runbook | `work/smoke_live_once.py`, `docs/real-machine-smoke.md` | The only sanctioned live entry; refuses unless every gate passes; never run by the cloud suite |

## Commands

```bat
python swctl.py machines
python swctl.py plan --machine ql5050px
python swctl.py unfold --legs 30,40 --thickness 2.5 --radius 1.5 --angle 90 --k 0.33
python swctl.py estimate --unfold runtime\plan.json --width 400 --material SUS304 --qty 5
python swctl.py numbers --parts panel-a,panel-b --journal runtime\numbers.json
python swctl.py precheck --groups runtime\chain.json
python swctl.py bom
python swctl.py schema-check --name unfold-plan --file runtime\plan.json
python swctl.py demo
```

## Cloud CI

`.github/workflows/cloud-tests.yml` runs the portable regression on
ubuntu-latest (Python 3.11/3.12, ezdxf only — no pywin32) plus the offline
demo, and uploads the evidence. The `--live` refusal tests are deterministic
there because `com_available()` honors the `SW_API_FORCE_NO_COM=1` test hook.
