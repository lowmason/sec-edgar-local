"""Behavioral offline guard regressions; every denied route uses recording stubs."""
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).parent
STUBS = r'''
import importlib.util, json, socket
calls = []
def record(name, result=None):
    def operation(*args, **kwargs):
        calls.append(name)
        return result
    return operation
socket.socket.connect = record('connect')
socket.socket.connect_ex = record('connect_ex', 0)
socket.socket.sendto = record('sendto', 1)
socket.getaddrinfo = record('getaddrinfo', [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 42421))])
socket.gethostbyname = record('gethostbyname', '127.0.0.1')
socket.gethostbyname_ex = record('gethostbyname_ex', ('fixture', [], ['127.0.0.1']))
socket.gethostbyaddr = record('gethostbyaddr', ('fixture', [], ['127.0.0.1']))
socket.getnameinfo = record('getnameinfo', ('fixture', '443'))
def blocked(operation):
    try:
        operation()
    except AssertionError:
        return True
    return False
'''


def guarded_spawn_probe(selected, output):
    namespace = {}
    exec(STUBS, namespace)
    if not import_available():
        output.put({'guard_available': False})
        return
    import network_guard
    network_guard.install()
    with network_guard.selected_origin(selected):
        exec("with socket.socket() as sock:\n    denied = [blocked(lambda: sock.connect(('198.51.100.1', 443))), blocked(lambda: sock.connect_ex(('127.0.0.1', 42422))), blocked(lambda: socket.getaddrinfo('unapproved.invalid', 443))]\n    sock.connect(('127.0.0.1', 42421))", namespace)
    output.put({'guard_available': True, 'denied': namespace['denied'], 'calls': namespace['calls'], 'pid': os.getpid()})


def import_available():
    import importlib.util
    return 'network_guard' in sys.modules or importlib.util.find_spec('network_guard') is not None


class NetworkGuardTests(unittest.TestCase):
    def probe(self, code):
        done = subprocess.run([sys.executable, '-c', STUBS + '\n' + code],
            cwd=TESTS, env={**os.environ, 'PYTHONPATH': str(TESTS), 'PYTHONDONTWRITEBYTECODE': '1'},
            capture_output=True, text=True, timeout=15)
        self.assertEqual(done.returncode, 0, done.stderr)
        proof = json.loads(done.stdout)
        self.retain({'argv': done.args, 'stdout': done.stdout, 'stderr': done.stderr, 'exit': done.returncode, 'proof': proof})
        return proof

    def retain(self, proof):
        destination = os.environ.get('SEC_EDGAR_TASK8_GUARD_TRACE_DIR')
        if destination:
            root = Path(destination)
            root.mkdir(parents=True, exist_ok=True)
            (root / (self.id().split('.')[-1] + '.json')).write_text(json.dumps(proof, indent=2, sort_keys=True) + '\n')

    def test_ordinary_support_import_installs_connection_and_resolution_denial(self):
        proof = self.probe("""
import support
with socket.socket() as sock:
    denied = [blocked(lambda: sock.connect(('198.51.100.1', 443))),
              blocked(lambda: sock.connect_ex(('198.51.100.1', 443))),
              blocked(lambda: socket.getaddrinfo('unapproved.invalid', 443)),
              blocked(lambda: socket.gethostbyname('unapproved.invalid')),
              blocked(lambda: socket.gethostbyname_ex('unapproved.invalid')),
              blocked(lambda: socket.gethostbyaddr('198.51.100.1')),
              blocked(lambda: socket.getnameinfo(('198.51.100.1', 443), 0)),
              blocked(lambda: sock.sendto(b'fixture', ('198.51.100.1', 443)))]
print(json.dumps({'denied': denied, 'calls': calls}))
""")
        self.assertEqual(proof['denied'], [True] * 8)
        self.assertEqual(proof['calls'], [])

    def test_explicit_helper_denies_connect_ex_resolution_and_unselected_loopback(self):
        proof = self.probe("""
import support
support.block_external_network()
with socket.socket() as sock:
    denied = [blocked(lambda: sock.connect_ex(('198.51.100.1', 443))),
              blocked(lambda: socket.getaddrinfo('unapproved.invalid', 443)),
              blocked(lambda: sock.connect(('127.0.0.1', 42422))),
              blocked(lambda: sock.connect_ex(('::1', 42422)))]
print(json.dumps({'denied': denied, 'calls': calls}))
""")
        self.assertEqual(proof['denied'], [True] * 4)
        self.assertEqual(proof['calls'], [])

    def test_only_selected_fixture_origin_is_allowed_and_scope_closes(self):
        self.assertTrue(import_available(), 'a separate test-only selected-origin guard is required')
        proof = self.probe("""
import support, network_guard
with socket.socket() as sock:
    with network_guard.selected_origin('http://127.0.0.1:42421'):
        sock.connect(('127.0.0.1', 42421))
        sock.connect_ex(('127.0.0.1', 42421))
        socket.getaddrinfo('127.0.0.1', 42421)
        denied = [blocked(lambda: sock.connect(('127.0.0.1', 42422))),
                  blocked(lambda: socket.getaddrinfo('localhost', 42421)),
                  blocked(lambda: socket.getaddrinfo('127.0.0.1', 42422))]
    denied.append(blocked(lambda: sock.connect(('127.0.0.1', 42421))))
print(json.dumps({'denied': denied, 'calls': calls}))
""")
        self.assertEqual(proof['denied'], [True] * 4)
        self.assertEqual(proof['calls'], ['connect', 'connect_ex', 'getaddrinfo'])

    def test_suite_runner_installs_guard_before_unittest_executes(self):
        self.assertTrue(import_available(), 'the test runner must install denial before discovery')
        proof = self.probe("""
import unittest, network_guard
captured = {}
def run(**kwargs):
    with socket.socket() as sock:
        captured['denied'] = blocked(lambda: sock.connect_ex(('198.51.100.1', 443)))
    captured['calls'] = calls
unittest.main = run
network_guard.main(['discover', '-s', '.'])
print(json.dumps(captured))
""")
        self.assertTrue(proof['denied'])
        self.assertEqual(proof['calls'], [])

    def test_spawned_process_has_selected_origin_and_denies_network(self):
        spawn = multiprocessing.get_context('spawn')
        output = spawn.Queue()
        process = spawn.Process(target=guarded_spawn_probe, args=('http://127.0.0.1:42421', output))
        try:
            process.start()
            proof = output.get(timeout=15)
            process.join(5)
            self.retain({'pid': process.pid, 'exit': process.exitcode, 'proof': proof})
            self.assertEqual(process.exitcode, 0)
            self.assertTrue(proof['guard_available'], 'spawned fixture needs an explicit installed guard')
            self.assertEqual(proof['denied'], [True] * 3)
            self.assertEqual(proof['calls'], ['connect'])
            self.assertNotEqual(proof['pid'], os.getpid())
        finally:
            if process.is_alive():
                process.terminate()
                process.join(2)
            output.close()
            output.join_thread()


def http_sentinel_probe(sentinel, output):
    namespace = {}
    exec(STUBS, namespace)
    import network_guard
    def import_sentinel(transport, cancellation, channel):
        import importlib.util
        spec = importlib.util.spec_from_file_location('network_import_sentinel', sentinel)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        channel.put({'denied': module.DENIED, 'calls': namespace['calls'], 'pid': os.getpid()})
    network_guard.guarded_transport_child(None, None, output, target=import_sentinel,
                                         origin='http://127.0.0.1:42421')


class GuardImportSentinelTests(unittest.TestCase):
    def sentinel(self):
        from support_process import write_import_sentinel
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return write_import_sentinel(Path(temporary.name) / 'network_import_sentinel.py')

    def test_suite_installs_guard_before_importing_dns_and_socket_sentinel(self):
        sentinel = self.sentinel()
        probe = NetworkGuardTests()
        result = probe.probe("""
import unittest, network_guard, importlib.util
captured = {}
def import_tests(**kwargs):
    spec = importlib.util.spec_from_file_location('network_import_sentinel', SENTINEL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    captured.update(denied=module.DENIED, calls=calls)
unittest.main = import_tests
network_guard.main(['discover'])
print(json.dumps(captured))
""".replace('SENTINEL', repr(str(sentinel))))
        self.assertEqual(result, {'denied': [True, True], 'calls': []})

    def test_spawned_http_target_guards_import_sentinel_before_transport(self):
        sentinel = self.sentinel()
        spawn = multiprocessing.get_context('spawn')
        output = spawn.Queue()
        process = spawn.Process(target=http_sentinel_probe, args=(str(sentinel), output))
        try:
            process.start()
            proof = output.get(timeout=15)
            process.join(5)
            self.assertEqual(process.exitcode, 0)
            self.assertEqual(proof['denied'], [True, True])
            self.assertEqual(proof['calls'], [])
            self.assertNotEqual(proof['pid'], os.getpid())
        finally:
            if process.is_alive():
                process.terminate()
                process.join(2)
            output.close()
            output.join_thread()
