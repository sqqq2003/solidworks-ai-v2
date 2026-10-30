"""Capture real part observations inside a proved task-owned CAD session."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re

from app_logging import get_journal
from part_verification import solid_inventory
import solidworks_generator as sw


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def capture_owned_part(driver, model, *, source_path, source_sha256, document_key,
                       configuration, step_id, phase):
    """Rebuild and measure one owned work-copy part without saving it.

    The caller supplies a confirmed baseline and must hold the project STA and
    writer lease. Body boxes are approximate; output cannot certify shape,
    mating, dimensions, material or manufacturing.
    """
    if phase not in {'before','after'} or not isinstance(step_id,str) or not step_id.strip():
        raise ValueError('explicit step id and before/after phase required')
    if not isinstance(source_sha256,str) or not re.fullmatch('[0-9a-f]{64}',source_sha256):
        raise ValueError('confirmed source SHA256 required')
    if not isinstance(document_key,str) or not document_key.strip() or not isinstance(configuration,str) or not configuration.strip():
        raise ValueError('explicit document and configuration identity required')
    journal=get_journal()
    try:
        driver.guard()  # proves task STA, session ownership, and complete inventory
        lease=driver.lease
        title=str(sw._com_read(model,'GetTitle'))
        owned=lease.owned_docs.get(title)
        if owned is None or owned.handle_id != id(model):
            raise RuntimeError('snapshot requires the exact task-owned document handle')
        copy=driver.owned_path(str(sw._com_read(model,'GetPathName')))
        baseline=Path(source_path).resolve(strict=True)
        if not baseline.is_file() or not copy.is_file() or baseline==copy:
            raise RuntimeError('source baseline and owned work copy must be distinct files')
        if _sha(baseline)!=source_sha256:
            raise RuntimeError('source baseline hash changed')
        copy_sha=_sha(copy)
        if int(sw._com_read(model,'GetType'))!=1:
            raise RuntimeError('native geometry snapshot currently supports parts only')
        manager=sw._com_read(model,'ConfigurationManager')
        actual=str(sw._com_read(sw._com_read(manager,'ActiveConfiguration'),'Name'))
        if actual != configuration:
            raise RuntimeError('active configuration does not match confirmed identity')
        driver.guard()
        if sw._com_read(model,'EditRebuild3') is not True:
            raise RuntimeError('work-copy rebuild failed or was not verified')
        module=sw.ensure_solidworks_typelib()
        part=sw._as_interface(module,model,'IPartDoc')
        bounds,body_boxes=solid_inventory(part,sw,module)
        # Some SW COM wrappers expose this as a property returning a callable
        # dispatch object; calling that object invokes an unrelated default member.
        mass=sw._com_read(model.Extension,'CreateMassProperty')
        if mass is None:raise RuntimeError('native volume is unavailable')
        volume=float(sw._com_read(mass,'Volume'))*1e9
        if not math.isfinite(volume) or volume <= 0:raise RuntimeError('native volume is invalid')
        if _sha(baseline)!=source_sha256 or _sha(copy)!=copy_sha:
            raise RuntimeError('source or work-copy file changed during snapshot')
        result={'schema_version':1,'identity':{'source_sha256':source_sha256,
                    'document_key':document_key,'configuration':configuration,
                    'document_confirmed':True,'configuration_confirmed':True},
                'rebuilt':True,'body_count':len(body_boxes),'bounds_mm':bounds,
                'volume_mm3':volume,'dimensions_mm':{},'work_copy_sha256':copy_sha,
                'bounds_precision':'approximate','geometry_verified':False,
                'production_approved':False}
        journal.record('geometry_snapshot_captured',step_id=step_id,phase=phase,
                       work_copy=str(copy),snapshot=result)
        return result
    except Exception as error:
        journal.exception('geometry_snapshot_failed',error,step_id=step_id,phase=phase)
        raise
