"""Reuse only an empty verified session, or launch when none exists.

No unknown document is adopted/closed in the strict attached route. The legacy
acceptance attach route remains unchanged for its independently pinned tests.
"""
from contextlib import contextmanager
from pathlib import Path
import time

from sw_owned_launch import (AttachedBinding, _snapshot_open_documents, _format_open_documents,
                             _read_pid, _finish_attached)
from sw_session import SessionOwnershipError


class IdleBinding(AttachedBinding):
    def validate(self, lease, *, documents=True):
        image_ok,pid=self._read_connection_or_rebind(lease)
        if not image_ok or pid!=self.lifetime.pid:
            lease.writes_blocked=True
            raise SessionOwnershipError('idle attached PID/image changed')
        if documents:
            opened,untitled=_snapshot_open_documents(self.app,self.list_titles)
            foreign=[d for d in opened if d['title'] not in lease.owned_docs]+untitled
            if foreign:
                lease.writes_blocked=True
                lease.foreign_titles.update(d.get('title','') for d in foreign)
                raise SessionOwnershipError('foreign documents preserved; writes refused: '+_format_open_documents(foreign))
        return None

    def evidence(self):
        result=super().evidence()
        result.update(connection_policy='verified_idle_existing_pid_no_document_adoption',
                      closed_before_write=[],closed_during_write=[],foreign_documents_closed=False)
        return result


def bind_idle(lifetime, discover, list_titles):
    from sw_session import current_lease, on_task_sta, require_model_write
    if not on_task_sta():raise SessionOwnershipError('idle binding requires task STA')
    lease=current_lease()
    if lease.native_launch is not None or lease.shared_com_bound or lease.writes_blocked or lease.poisoned:
        raise SessionOwnershipError('fresh lease required')
    app=discover(lifetime.pid)
    if app is None or _read_pid(app)!=lifetime.pid or lifetime.probe(lifetime.pid) is None:
        raise SessionOwnershipError('existing PID/COM/image proof failed')
    # Two independent snapshots; neither performs CloseDoc or changes a document.
    for _ in range(2):
        opened,untitled=_snapshot_open_documents(app,list_titles)
        if opened or untitled:raise SessionOwnershipError('save/close documents yourself, or select dedicated session: '+_format_open_documents(opened+untitled))
    binding=IdleBinding(lifetime,app,_read_pid,list_titles);binding.rediscover=discover
    lease.attached_existing=True;lease.created_by_task=False;lease.spawn_claimed=False
    lease.close_doc_only=True;lease.reuse_attached=True;lease.shared_com_bound=True
    lease.foreign_titles=set();lease.foreign_titles_known=True
    lease.observed_pid=lifetime.pid;lease.note_bound_application(app);lease.list_open_titles=list_titles
    lease.keep_application_open=True
    if not lease.prove_attached_reuse(lifetime.pid,lifetime.probe):raise SessionOwnershipError('idle PID proof failed')
    lease.native_launch=binding
    require_model_write(lease)
    return binding


@contextmanager
def modeling_session(executable, mode='auto'):
    import sys
    if sys.platform!='win32':raise RuntimeError('Windows SolidWorks required')
    from sw_owned_launch import (_matching_sldworks_pids, _open_query_lifetime,
                                 _discover_attached, owned_solidworks)
    from sw_session import current_lease, on_task_sta
    from solidworks_generator import _list_open_document_titles
    if not on_task_sta():raise SessionOwnershipError('native session requires task STA')
    path=Path(executable).expanduser().resolve(strict=True)
    if path.name.casefold()!='sldworks.exe':raise ValueError('installed SLDWORKS.exe required')
    if mode not in {'auto','dedicated','idle_existing'}:raise ValueError('unknown session mode')
    if mode=='dedicated':
        with owned_solidworks(path) as binding:yield binding
        return
    pids=_matching_sldworks_pids(path)
    if not pids and mode=='auto':
        with owned_solidworks(path) as binding:yield binding
        return
    if len(pids)!=1:raise SessionOwnershipError('idle reuse requires exactly one matching SLDWORKS; no process was started')
    lifetime=_open_query_lifetime(pids[0],path);lease=current_lease();lease.native_launch_attempt=lifetime
    binding=None;failed=False
    try:
        binding=bind_idle(lifetime,_discover_attached,_list_open_document_titles)
        yield binding
    except BaseException:
        failed=True
        raise
    finally:
        if binding is not None:_finish_attached(lease,binding,lifetime,body_failed=failed)
        else:lifetime.close()
