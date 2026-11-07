"""Fail on names Python would only discover at run time (pyflakes)."""
import subprocess
import sys
from pathlib import Path

from pyflakes import api, messages, reporter

ROOT = Path(__file__).resolve().parents[1]
FATAL = (messages.UndefinedName, messages.UndefinedLocal, messages.UndefinedExport)
EXCLUDED = ('work/evidence/',)


class Collector(reporter.Reporter):
    def __init__(self):
        super().__init__(sys.stdout, sys.stderr)
        self.found = []

    def flake(self, message):
        if isinstance(message, FATAL):
            self.found.append(message)

    def syntaxError(self, filename, msg, lineno, offset, text):
        self.found.append(f'{filename}:{lineno}: syntax error: {msg}')

    def unexpectedError(self, filename, msg):
        self.found.append(f'{filename}: {msg}')


def tracked_sources():
    names = subprocess.check_output(['git', 'ls-files', '-z', '*.py'], cwd=ROOT).decode().split('\0')
    return [ROOT / name for name in names if name and not name.startswith(EXCLUDED)]


def main():
    collector = Collector()
    for path in tracked_sources():
        api.checkPath(str(path), collector)
    for message in collector.found:
        print(message)
    print(f'{len(collector.found)} undefined-name problem(s)')
    return 1 if collector.found else 0


if __name__ == '__main__':
    sys.exit(main())
