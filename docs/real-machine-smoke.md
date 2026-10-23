# Real-machine live smoke (operator PC only)

`work/smoke_live_once.py` is the **only** sanctioned way to exercise the live
path, and it runs on a Windows machine that actually has SolidWorks
installed. It is deliberately not part of the cloud/offline framework: the
cloud regression never opens SolidWorks, and this document exists so the
one real run leaves evidence instead of folklore.

## Before you run

1. **Work on a throwaway assembly.** Copy the operator test model to a
   scratch folder. Never point `--assembly` at a customer mother file.
2. **Prepare a confirmed mapping JSON.** Every value must be confirmed with
   provenance, e.g.:

   ```json
   {
     "values": {
       "height": {"value_mm": 750.0, "confirmed": true, "provenance": "operator measurement 2026-10-24"},
       "length": {"value_mm": 1300.0, "confirmed": true, "provenance": "operator measurement 2026-10-24"},
       "width":  {"value_mm": 600.0,  "confirmed": true, "provenance": "operator measurement 2026-10-24"}
     }
   }
   ```

   The gate rejects the whole run if any value is unconfirmed. No guesses.

3. **Locate `SLDWORKS.exe`.** Default install path is fine; export
   `SW_EXE` if it differs.

## Run

```bat
set SW_LIVE_SMOKE_CONFIRM=1
set SW_EXE=C:\Program Files\SOLIDWORKS\SLDWORKS.exe
python work\smoke_live_once.py ^
    --assembly "D:\scratch\test-model.SLDASM" ^
    --save-as  "D:\scratch\test-model-copy.SLDASM" ^
    --mapping  runtime\live-smoke-mapping.json ^
    --out      results\windows\live_smoke.json
```

The script exits `2` and touches nothing unless **all** gates pass:
explicit confirm, assembly exists, work-copy rules (both `.SLDASM`,
different paths), `SLDWORKS.exe` exists and is named exactly
`SLDWORKS.exe`, COM importable, mapping fully confirmed.

## Evidence to collect

`results/windows/live_smoke.json` records the gate list and the apply
result. A trustworthy run also shows:

- the work copy opens, the equation values read back as written, and the
  file closes **without saving** so the source on disk is untouched;
- no other SolidWorks document was closed by the run.

## If it fails

Do not force it. Record the failure in the dispatch `KNOWN_ISSUES.md`
with the gate names from the refusal report and stop. The offline
framework does not depend on the live path.
