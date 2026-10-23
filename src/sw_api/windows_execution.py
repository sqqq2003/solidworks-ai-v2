"""Windows driver bridge for the transaction protocol.

The driver is supplied by Windows integration, with resolved native dimensions,
configuration-aware read/write, rebuild errors, copy isolation and recovery.
No COM import or process attachment occurs during discovery on Linux.
"""
import sys
from contextlib import contextmanager


class WindowsExecutionPort:
    simulated = False

    def __init__(self, driver):
        self.driver = driver
        self.lease = None

    @contextmanager
    def writer(self):
        if sys.platform != "win32":
            raise RuntimeError("sw_live=not_applicable_on_linux")
        from .win32com_backend import _import_sw_session
        session = _import_sw_session()
        self.lease = session.require_model_write()
        try:
            yield
        finally:
            self.lease = None

    def guarded(self, method, *args):
        from .win32com_backend import _import_sw_session
        if self.lease is None:
            raise RuntimeError("single writer session required")
        _import_sw_session().require_model_write(self.lease)
        return getattr(self.driver, method)(*args)

    def preflight(self, mappings, destination):
        return self.guarded("preflight", mappings, destination)

    def read(self, mapping):
        return self.guarded("read", mapping)

    def write(self, mapping, value):
        return self.guarded("write", mapping, value)

    def rebuild(self):
        return self.guarded("rebuild")

    def checkpoint(self):
        return self.guarded("checkpoint")

    def restore(self, checkpoint):
        return self.guarded("restore", checkpoint)

    def save_as(self, destination):
        return self.guarded("save_as", destination)

    def reopen(self, destination):
        return self.guarded("reopen", destination)
