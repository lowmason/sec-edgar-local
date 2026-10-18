"""Test-only network denial with scoped, exact loopback fixture origins.

This module is outside the installed package. The runner installs it before test
imports; support imports install it for focused runs and spawned fixture helpers.
"""
from __future__ import annotations

import socket
import sys
import json
import os
import re
from contextvars import ContextVar
from collections import Counter
from contextlib import contextmanager
from functools import wraps
from threading import RLock
from urllib.parse import urlsplit
from pathlib import Path

_INSTALLED = False
_ORIGINS: Counter[tuple[str, int]] = Counter()
_LOCK = RLock()
_CHECKOUT_POLICY = None
_CHECKOUT_ROOTS = tuple(Path(value) for value in
    ('/Users/lowell/Projects/sec-edgar', '/Users/lowell/Projects/sec-edgar-local'))
_POLICY_FILE = 'checkout-policy.json'


def checkout_policy():
    """Snapshot only an explicitly installed proof scope; source tests have none."""
    if _CHECKOUT_POLICY is None:
        return None
    return {'version': 'sec-checkout-policy-v1', 'releases': list(_CHECKOUT_POLICY)}


def _policy_releases(value):
    if (not isinstance(value, dict) or set(value) != {'version', 'releases'}
            or value['version'] != 'sec-checkout-policy-v1'
            or not isinstance(value['releases'], list)
            or any(not isinstance(path, str) or not Path(path).is_absolute()
                   or Path(path).parent.name != 'releases'
                   or re.fullmatch(r'sha256=[0-9a-f]{64}', Path(path).name) is None
                   for path in value['releases'])):
        raise ValueError('invalid copied checkout policy')
    return tuple(sorted(set(value['releases'])))


def write_checkout_policy(harness, value):
    """Seal a selected proof's scope into its copied, stdlib-only bootstrap."""
    if value is not None:
        _policy_releases(value)
        path = Path(harness) / _POLICY_FILE
        with path.open('x') as stream:
            json.dump(value, stream, sort_keys=True)
        path.chmod(0o444)


def install_checkout_policy(releases):
    """Deny checkout code/data except exact release dirs preverified by the caller.

    This is test instrumentation, not release validation. Runtime preflight is
    still the sole release authority; callers pass only its selected directories.
    """
    global _CHECKOUT_POLICY
    selected = _policy_releases({'version': 'sec-checkout-policy-v1', 'releases': list(releases)})
    if _CHECKOUT_POLICY is not None:
        if selected != _CHECKOUT_POLICY:
            raise ValueError('checkout policy is immutable within a proof process')
        return
    exceptions = tuple((Path(os.path.abspath(path)), Path(path).resolve()) for path in selected)
    roots = tuple((root, root.resolve()) for root in _CHECKOUT_ROOTS)
    original, real_original = roots[0]
    if any(path.is_relative_to(original) or resolved.is_relative_to(real_original)
           or any(root.is_relative_to(path) or real.is_relative_to(resolved) for root, real in roots)
           for path, resolved in exceptions):
        raise ValueError('checkout policy cannot exempt a source root')

    def require_path(raw, *, cwd=None):
        if isinstance(raw, int) or raw is None:
            return
        value = os.fsdecode(raw)
        if value.startswith('<') and value.endswith('>'):
            return
        path = Path(value)
        if cwd is not None and not path.is_absolute():
            path = Path(cwd) / path
        lexical = Path(os.path.abspath(path))
        # Resolve the original spelling: collapsing '..' first would hide a
        # preceding symlink's real parent and could misattribute a source open.
        resolved = path.resolve()
        for root, real_root in roots:
            lexical_denied = lexical.is_relative_to(root) and not any(
                lexical.is_relative_to(path) for path, _ in exceptions)
            resolved_denied = resolved.is_relative_to(real_root) and not any(
                resolved.is_relative_to(real) for _, real in exceptions)
            if lexical_denied or resolved_denied:
                raise PermissionError('installed proof refuses checkout access: ' + value)

    def audit(event, args):
        if event == 'open':
            require_path(directory_open_path.get() or args[0])
        elif event == 'compile':
            require_path(args[1])
        elif event == 'exec':
            require_path(args[0].co_filename)
        elif event == 'import' and args[1] is not None:
            require_path(args[1])
        elif event in ('subprocess.Popen', 'os.exec', 'os.posix_spawn'):
            child_cwd = args[2] if event == 'subprocess.Popen' and args[2] is not None else os.getcwd()
            child_cwd = Path(os.fsdecode(child_cwd))
            if not child_cwd.is_absolute():
                child_cwd = Path.cwd() / child_cwd
            require_path(child_cwd)
            executable = args[0]
            if not isinstance(executable, int):
                executable = os.fsdecode(executable)
                if os.path.dirname(executable) or event != 'subprocess.Popen':
                    require_path(executable, cwd=child_cwd)
                else:
                    environment = args[3] if event == 'subprocess.Popen' else args[2]
                    # Match POSIX child PATH lookup, including child-relative entries.
                    for entry in os.get_exec_path(environment):
                        candidate = Path(entry or '.') / executable
                        if not candidate.is_absolute():
                            candidate = child_cwd / candidate
                        if candidate.is_file() and os.access(candidate, os.X_OK):
                            require_path(candidate)
                            break
            # Python script execution is distinct from data/provenance arguments.
            argv = args[1]
            if (isinstance(argv, (list, tuple)) and not isinstance(executable, int)
                    and Path(executable).name.startswith('python')):
                arguments = iter(argv[1:])
                for argument in arguments:
                    if argument in ('-c', '-m'):
                        break
                    if argument in ('-X', '-W', '--check-hash-based-pycs'):
                        next(arguments, None)
                        continue
                    if not os.fsdecode(argument).startswith('-'):
                        require_path(argument, cwd=child_cwd)
                        break

    # CPython's open audit event omits dir_fd. Attribute that event to the real
    # directory while preserving the exact descriptor-relative storage call.
    directory_open_path = ContextVar('checkout_directory_open_path', default=None)
    actual_open = os.open

    @wraps(actual_open)
    def open_at(path, flags, mode=0o777, *, dir_fd=None):
        if dir_fd is None or os.path.isabs(path):
            return actual_open(path, flags, mode, dir_fd=dir_fd)
        if sys.platform == 'darwin':
            import fcntl
            base = os.fsdecode(fcntl.fcntl(dir_fd, fcntl.F_GETPATH, b'\0' * 1024).split(b'\0')[0])
        else:
            base = os.readlink('/proc/self/fd/' + str(dir_fd))
        token = directory_open_path.set(os.path.join(base, os.fsdecode(path)))
        try:
            return actual_open(path, flags, mode, dir_fd=dir_fd)
        finally:
            directory_open_path.reset(token)

    _CHECKOUT_POLICY = selected
    sys.addaudithook(audit)
    os.open = open_at


def restore_checkout_policy(value):
    if value is not None:
        install_checkout_policy(_policy_releases(value))


def checkout_evidence():
    """Observe denial before a copied proof imports any application module."""
    import importlib.machinery
    import importlib.util
    application_imported = any(name == 'sec_edgar_ingest' or name.startswith('sec_edgar_ingest.')
                               for name in sys.modules)
    if application_imported:
        raise AssertionError('checkout audit sentinel ran after an application import')
    denied = []
    for root in _CHECKOUT_ROOTS:
        path = root / '.git/HEAD'
        loader = importlib.machinery.SourceFileLoader('checkout_import_sentinel', str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        code = (lambda: None).__code__.replace(co_filename=str(root / 'checkout-exec-sentinel.py'))
        for operation in (path.read_bytes,
                          lambda: loader.exec_module(importlib.util.module_from_spec(spec)),
                          lambda: exec(code, {})):
            try:
                operation()
            except PermissionError:
                denied.append(True)
            else:
                raise AssertionError('installed proof escaped checkout audit policy')
    return {'pid': os.getpid(), 'policy': checkout_policy(), 'denied': denied,
            'application_imported': application_imported}


def _require_address(address) -> None:
    if not isinstance(address, tuple) or len(address) < 2:
        raise AssertionError('offline tests allow only selected loopback fixture addresses')
    host, port = address[:2]
    if isinstance(port, str) and port.isdecimal():
        port = int(port)
    with _LOCK:
        allowed = type(port) is int and _ORIGINS[(host, port)] > 0
    if not allowed:
        raise AssertionError('offline tests refuse an unselected network address')


def _require_host(host) -> None:
    with _LOCK:
        allowed = host in ('127.0.0.1', '::1') and any(key[0] == host and count > 0 for key, count in _ORIGINS.items())
    if not allowed:
        raise AssertionError('offline tests refuse unselected name resolution')


def _connection_guard(operation):
    @wraps(operation)
    def guarded(sock, address, *args, **kwargs):
        _require_address(address)
        return operation(sock, address, *args, **kwargs)
    return guarded


def _lookup_guard(operation):
    @wraps(operation)
    def guarded(host, port, *args, **kwargs):
        _require_address((host, port))
        return operation(host, port, *args, **kwargs)
    return guarded


def _host_guard(operation):
    @wraps(operation)
    def guarded(host, *args, **kwargs):
        _require_host(host)
        return operation(host, *args, **kwargs)
    return guarded


def _sendto_guard(operation):
    @wraps(operation)
    def guarded(sock, data, *args):
        _require_address(args[-1] if args else None)
        return operation(sock, data, *args)
    return guarded


def _sendmsg_guard(operation):
    @wraps(operation)
    def guarded(sock, buffers, ancdata=(), flags=0, address=None):
        _require_address(address)
        return operation(sock, buffers, ancdata, flags, address)
    return guarded


def install() -> None:
    """Deny real Python socket/DNS work before tests run."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    socket.socket.connect = _connection_guard(socket.socket.connect)
    socket.socket.connect_ex = _connection_guard(socket.socket.connect_ex)
    socket.socket.sendto = _sendto_guard(socket.socket.sendto)
    if hasattr(socket.socket, 'sendmsg'):
        socket.socket.sendmsg = _sendmsg_guard(socket.socket.sendmsg)
    socket.getaddrinfo = _lookup_guard(socket.getaddrinfo)
    original_nameinfo = socket.getnameinfo
    @wraps(original_nameinfo)
    def getnameinfo(address, flags):
        _require_address(address)
        return original_nameinfo(address, flags)
    socket.getnameinfo = getnameinfo
    for name in ('gethostbyname', 'gethostbyname_ex', 'gethostbyaddr'):
        setattr(socket, name, _host_guard(getattr(socket, name)))



@contextmanager
def selected_origin(origin: str):
    """Authorize one explicit fixture port until its bounded fixture is closed."""
    parsed = urlsplit(origin)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', '::1') or
            parsed.port is None or not 1 <= parsed.port <= 65535 or parsed.username or
            parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('test origin must be an exact literal loopback HTTP origin')
    address = parsed.hostname, parsed.port
    with _LOCK:
        _ORIGINS[address] += 1
    try:
        yield
    finally:
        with _LOCK:
            _ORIGINS[address] -= 1
            if not _ORIGINS[address]:
                del _ORIGINS[address]


def guarded_transport_child(transport, cancellation, channel, *, target, origin, policy=None):
    """Spawn carries only this selected fixture origin and its original target."""
    install()
    restore_checkout_policy(policy)
    with selected_origin(origin):
        return target(transport, cancellation, channel)


def main(argv=None) -> None:
    install()
    import unittest
    unittest.main(module=None, argv=['unittest', *(sys.argv[1:] if argv is None else argv)])


def current_origins() -> tuple[str, ...]:
    """Snapshot explicit fixture authorizations for an exec boundary."""
    with _LOCK:
        return tuple(sorted('http://' + ('[' + host + ']' if ':' in host else host) + ':' + str(port)
                            for (host, port), count in _ORIGINS.items() if count > 0))


if __name__ in ('__main__', '__mp_main__'):
    # Support and spawn targets share one guard instance when run as a file.
    sys.modules.setdefault('network_guard', sys.modules[__name__])
# Spawn imports this module before unpickling its partial target/application args.
# The sidecar exists only in an explicitly copied installed-proof harness.
_copied_policy = Path(__file__).absolute().with_name(_POLICY_FILE)
if _copied_policy.is_file():
    restore_checkout_policy(json.loads(_copied_policy.read_text()))
if __name__ == '__main__':
    main()
