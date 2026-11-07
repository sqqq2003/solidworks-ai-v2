"""In-memory contract backend. Never writes a CAD product."""
from contextlib import contextmanager
from copy import deepcopy


class MockExecutionPort:
    simulated = True

    def __init__(self, values, fail_at=None):
        self.values = dict(values)
        self.outputs = {}
        self.calls = []
        self.fail_at = fail_at
        self.locked = False

    def step(self, name):
        self.calls.append(name)
        if name == self.fail_at:
            raise RuntimeError("injected failure: " + name)

    @contextmanager
    def writer(self):
        if self.locked:
            raise RuntimeError("single writer required")
        self.locked = True
        try:
            yield
        finally:
            self.locked = False

    def preflight(self, mappings, destination):
        self.step("preflight")
        if destination in self.outputs:
            raise ValueError("destination already exists")
        for row in mappings:
            if row.parameter not in self.values:
                raise ValueError("physical target missing")

    def read(self, mapping):
        self.step("read")
        return self.values[mapping.parameter]

    def write(self, mapping, value):
        self.step("write")
        self.values[mapping.parameter] = value

    def rebuild(self):
        self.step("rebuild")

    def checkpoint(self):
        return deepcopy((self.values, self.outputs))

    def restore(self, checkpoint):
        self.step("restore")
        self.values, self.outputs = deepcopy(checkpoint)

    def save_as(self, destination):
        self.step("save_as")
        self.outputs[destination] = dict(self.values)

    def reopen(self, destination):
        self.step("reopen")
        self.values = dict(self.outputs[destination])
