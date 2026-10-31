# A01-002B-1 session safety

This tree patches the uploaded `solidworks_generator.py` and `batch_export.py` baselines so a task cannot force-kill SolidWorks, or close a session it cannot prove it owns.

The untouched originals are in `results/cursor/baseline/src/`. Their SHA-256 values are the hashes of the files unpacked from the task pack:

- `batch_export.py` `472e86abcfa13cc14ac309592ee2dcf5c64cd83a2c64d578ec7fe9214d3c582f`
- `solidworks_generator.py` `0b1e3d722ce681d0f7fd7a17afe6b8d5594572aff6b39beac4c8e25656d8c7bd`

`src/sw_session.py` is the task-scoped worker. COM calls for generation, flat-pattern export, and roller generation run on one STA thread. The watchdog thread only records a timeout. It does not call COM. `ExitApp`, `CloseAllDocuments`, and a PID signal are allowed only after this process proves it spawned that SolidWorks PID, observed the same PID on the session, and saw no foreign documents. `GetActiveObject` / `Dispatch` alone is not that proof.

Batch export still reads a memory figure. If the figure is high and the session is not proven exclusive, export logs a refusal and continues the part. It does not attach to whatever instance is running.

## Run the simulated tests

```bash
python -m unittest tests.test_sw_session_safety -v
```

These tests use fake COM objects and fake process probes. They do not start SolidWorks. SolidWorks live behavior was not tested.

`turned_part.py` was not in this pack. The same class of teardown may still be there. This batch does not claim whole-application session safety.

## Result

`results/cursor/result.json` separates the code change, the simulated test run, and SolidWorks live status (`not tested`).
