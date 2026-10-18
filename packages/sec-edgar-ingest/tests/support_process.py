"""Immutable test-only stage harness, injected at the checked runner boundary."""
from network_guard import install, current_origins
install()

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

from sec_edgar_ingest import runtime


class CheckedRunner:
    def __init__(self, *, fault=None, pid_log=None, sentinel=None, die_with_child=False):
        self.fault = fault
        self.pid_log = pid_log
        self.sentinel = sentinel
        self.die_with_child = die_with_child

    def __call__(self, python, argv, *, deadline, environ):
        with tempfile.TemporaryDirectory(prefix='sec-checked-harness-') as temporary:
            root = Path(temporary)
            tests = Path(__file__).absolute().parent
            for name in ('checked_child_bootstrap.py', 'network_guard.py', 'support_process.py'):
                shutil.copyfile(tests / name, root / name)
            value = {'version': 'sec-checked-harness-v1', 'origins': list(current_origins()),
                'fault': self.fault, 'pid_log': str(self.pid_log) if self.pid_log else None,
                'sentinel': str(self.sentinel) if self.sentinel else None}
            path = root / 'payload.json'
            path.write_text(json.dumps(value, sort_keys=True))
            path.chmod(0o444)
            command = [*runtime.native_python_argv(python), str(root / 'checked_child_bootstrap.py'),
                       str(path), *argv[argv.index('-m') + 2:]]
            stopped = threading.Event()
            def acknowledge():
                while not stopped.wait(0.01):
                    if self.fault and Path(self.fault['marker']).is_file():
                        Path(self.fault['ack']).touch(exist_ok=True)
                        return
            monitor = threading.Thread(target=acknowledge)
            monitor.start()
            try:
                result = runtime.run_child(python, command, deadline=deadline, environ=environ)
            finally:
                stopped.set()
                monitor.join(2)
            if self.die_with_child and result.returncode == 91:
                os._exit(91)
            return result


def checked_dispatcher(*args, **kwargs):
    from sec_edgar_ingest.workflows.checked import Dispatcher
    kwargs.setdefault('child_runner', CheckedRunner())
    return Dispatcher(*args, **kwargs)


def write_import_sentinel(path, log=None):
    """Create a real import-time DNS/socket probe shared by all guard boundaries."""
    path = Path(path)
    path.write_text("import socket, json\nfrom pathlib import Path\nDENIED=[]\n"
        "def connect():\n    with socket.socket() as sock: sock.connect(('198.51.100.1',443))\n"
        "for operation in (lambda: socket.getaddrinfo('sentinel.invalid',443), connect):\n"
        "    try: operation()\n    except AssertionError: DENIED.append(True)\n"
        "    else: raise AssertionError('sentinel escaped guard')\n" +
        (f"with Path({str(log)!r}).open('a') as stream: stream.write(json.dumps(DENIED)+'\\n')\n" if log else ''))
    return path
