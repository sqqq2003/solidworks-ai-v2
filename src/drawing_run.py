"""Drawing status policy over the shared durable CAD runner."""
from cad_run import note_owned_process, run_receipted_cad


def note_drawing_process(lease):
    return note_owned_process(lease)


def run_receipted_drawing(document, originals, payload, job, *, timeout, task_name, state_db=None, key=None):
    from drawing_review import drawing_implementation_hashes
    return run_receipted_cad(document, originals, payload, job, timeout=timeout, task_name=task_name,
        implementation_hashes=drawing_implementation_hashes(),
        success_statuses={'completed_partial_model_trial', 'native_workflow_executed_pending_review'},
        state_db=state_db, key=key)
