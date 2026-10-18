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


class CloudImportInventoryTests(unittest.TestCase):
    def test_all_default_test_support_and_application_imports_exclude_cloud_sdks(self):
        import ast
        roots = (TESTS, TESTS.parent / 'src' / 'sec_edgar_ingest')
        forbidden = []
        for root in roots:
            for path in root.rglob('*.py'):
                for node in ast.walk(ast.parse(path.read_text())):
                    names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                             else [node.module or ''] if isinstance(node, ast.ImportFrom) else [])
                    for name in names:
                        if name.split('.')[0] in ('azure', 'msal'):
                            forbidden.append((str(path), node.lineno, name))
        self.assertEqual(forbidden, [])


class CheckoutPolicyTests(unittest.TestCase):
    def isolated_probe(self, body, *, policy=None, files=None):
        import shutil
        with tempfile.TemporaryDirectory(prefix='sec-checkout-probe-') as directory:
            root = Path(directory)
            shutil.copy2(TESTS / 'network_guard.py', root / 'network_guard.py')
            if policy is not None:
                (root / 'checkout-policy.json').write_text(json.dumps(policy))
            for name, text in (files or {}).items():
                (root / name).write_text(text)
            script = root / 'probe.py'
            script.write_text('import sys;sys.path.insert(0,' + repr(str(root)) + ')\n' + body)
            done = subprocess.run([sys.executable, '-I', '-B', '-X', 'pycache_prefix=/dev/null', str(script)],
                                  cwd=root, capture_output=True, text=True, timeout=30)
            self.assertEqual(done.returncode, 0, done.stderr)
            return json.loads(done.stdout)

    def test_explicit_policy_denies_both_source_roots_and_code_attributed_execution(self):
        proof = self.isolated_probe('''
import importlib.util,importlib.machinery,json,os,pathlib,subprocess,network_guard
roots = ('/Users/lowell/Projects/sec-edgar', '/Users/lowell/Projects/sec-edgar-local')
precompiled = [compile('pass', root+'/audit-sentinel.py','exec') for root in roots]
installer = getattr(network_guard,'install_checkout_policy',None)
denied=[]
if installer:
    installer(())
    for root,code in zip(roots,precompiled):
        path = pathlib.Path(root)/'.git/HEAD'
        loader=importlib.machinery.SourceFileLoader('checkout_import',str(path))
        spec=importlib.util.spec_from_loader(loader.name,loader)
        for operation in (lambda:path.read_bytes(), lambda:exec(code,{}),
                lambda:compile('pass',root+'/sentinel.py','exec'),
                lambda:loader.exec_module(importlib.util.module_from_spec(spec)),
                lambda:subprocess.run([root+'/scripts/sec-edgar-local'],check=False)):
            try: operation()
            except PermissionError: denied.append(True)
            else: denied.append(False)
print(json.dumps({'available':bool(installer),'denied':denied}))
''')
        self.assertTrue(proof['available'], 'explicit checkout-denial audit policy is required')
        self.assertEqual(proof['denied'], [True] * 10)

    def test_path_aliases_cannot_escape_and_only_exact_selected_release_is_allowed(self):
        project = TESTS.resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix='audit-selected-', dir=project / 'releases') as directory:
            selected = Path(directory) / 'releases' / ('sha256=' + 'a' * 64)
            selected.mkdir(parents=True)
            (selected / 'allowed.py').write_text('VALUE=1\n')
            body = '''
import importlib.util,json,pathlib,network_guard,sys
selected=pathlib.Path(SELECTED)
alias=pathlib.Path('alias')
alias.symlink_to('/Users/lowell/Projects/sec-edgar-local')
(selected/'escape').symlink_to('/Users/lowell/Projects/sec-edgar/.git')
installer=getattr(network_guard,'install_checkout_policy',None)
denied=[]; allowed=[]
if installer:
    installer((str(selected),))
    for path in (alias/'.git/HEAD',selected/'..'/'..'/'pyproject.toml',
            selected.parent/'artifact-cache'/'artifacts.json',
            selected.with_name(selected.name+'-sibling')/'other.py',
            selected/'escape'/'HEAD',
            selected/'escape'/'..'/'pyproject.toml',
            pathlib.Path('/Users/lowell/Projects/sec-edgar/.git/HEAD')):
        try:path.read_bytes()
        except PermissionError:denied.append(True)
        else:denied.append(False)
    for path in (selected/'allowed.py',pathlib.Path('outside.py')):
        if path.name=='outside.py':path.write_text('VALUE=2')
        spec=importlib.util.spec_from_file_location(path.stem,path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        allowed.append(module.VALUE)
print(json.dumps({'available':bool(installer),'denied':denied,'allowed':allowed}))
'''.replace('SELECTED', repr(str(selected)))
            proof = self.isolated_probe(body)
        self.assertTrue(proof['available'], 'exact selected-release exception is required')
        self.assertEqual(proof['denied'], [True] * 7)
        self.assertEqual(proof['allowed'], [1, 2])

    def test_copied_spawn_main_has_policy_before_application_class_unpickle(self):
        policy = {'version': 'sec-checkout-policy-v1', 'releases': []}
        app_module = '''
import json,os,sys,pathlib
denied=[]
for root in ('/Users/lowell/Projects/sec-edgar','/Users/lowell/Projects/sec-edgar-local'):
    try:(pathlib.Path(root)/'.git/HEAD').read_bytes()
    except PermissionError:denied.append(True)
    else:denied.append(False)
with pathlib.Path(__file__).with_name('order.jsonl').open('a') as stream:
    stream.write(json.dumps({'event':'application-class-import','pid':os.getpid(),'denied':denied})+'\\n')
class Transport: pass
def exchange(transport,cancellation,channel):
    channel.put({'pid':os.getpid(),'denied':denied})
'''
        body = '''
import json,os,pathlib,network_guard,multiprocessing,functools
denied=[]
for root in ('/Users/lowell/Projects/sec-edgar','/Users/lowell/Projects/sec-edgar-local'):
    try:(pathlib.Path(root)/'.git/HEAD').read_bytes()
    except PermissionError:denied.append(True)
    else:denied.append(False)
with pathlib.Path('order.jsonl').open('a') as stream:
    stream.write(json.dumps({'event':'main-before-application','pid':os.getpid(),'denied':denied})+'\\n')
if __name__=='__main__':
    from application_sentinel import Transport,exchange
    spawn=multiprocessing.get_context('spawn'); channel=spawn.Queue()
    target=functools.partial(network_guard.guarded_transport_child,target=exchange,origin='http://127.0.0.1:42421')
    process=spawn.Process(target=target,args=(Transport(),None,channel))
    process.start();proof=channel.get(timeout=15);process.join(10)
    records=[json.loads(line) for line in pathlib.Path('order.jsonl').read_text().splitlines()]
    print(json.dumps({'child':proof,'pid':os.getpid(),'exit':process.exitcode,'records':records}))
    channel.close();channel.join_thread()
'''
        proof = self.isolated_probe(body, policy=policy, files={'application_sentinel.py': app_module})
        self.assertEqual(proof['exit'], 0)
        self.assertNotEqual(proof['pid'], proof['child']['pid'])
        child = [item for item in proof['records'] if item['pid'] == proof['child']['pid']]
        self.assertEqual([item['event'] for item in child],
                         ['main-before-application', 'application-class-import'])
        self.assertTrue(all(item['denied'] == [True, True] for item in proof['records']), proof)

    def test_default_source_harness_has_no_checkout_policy(self):
        proof = self.isolated_probe('''
import json,pathlib,network_guard
print(json.dumps({'readable':bool(pathlib.Path('/Users/lowell/Projects/sec-edgar-local/.git/HEAD').read_bytes())}))
''')
        self.assertTrue(proof['readable'])

    def test_policy_refuses_root_alias_exception_and_scope_replacement(self):
        proof = self.isolated_probe('''
import json,pathlib,network_guard
alias=pathlib.Path('releases')/('sha256='+'a'*64)
alias.parent.mkdir()
alias.symlink_to('/Users/lowell/Projects/sec-edgar-local')
refused=[]
for releases in ((str(alias.absolute()),),('/Users/lowell/Projects/sec-edgar',)):
    try:network_guard.install_checkout_policy(releases)
    except ValueError:refused.append(True)
    else:refused.append(False)
if all(refused):
    network_guard.install_checkout_policy(())
    network_guard.install_checkout_policy(())
    try:network_guard.install_checkout_policy(('/tmp/releases/sha256='+'b'*64,))
    except ValueError:refused.append(True)
    else:refused.append(False)
print(json.dumps({'refused':refused}))
''')
        self.assertEqual(proof['refused'], [True, True, True])

    def test_policy_refuses_blanket_releases_or_cache_exception(self):
        proof = self.isolated_probe('''
import json,network_guard
refused=[]
for path in ('/Users/lowell/Projects/sec-edgar-local/releases',
             '/Users/lowell/Projects/sec-edgar-local/releases/artifact-cache'):
    try:network_guard.install_checkout_policy((path,))
    except ValueError:refused.append(True)
    else:refused.append(False)
print(json.dumps({'refused':refused}))
''')
        self.assertEqual(proof['refused'], [True, True])

    def test_directory_fd_opens_use_actual_directory_without_changing_storage_operations(self):
        proof = self.isolated_probe('''
import json,os,pathlib,network_guard
outside=pathlib.Path.cwd()
(outside/'locks').write_text('outside fixture')
allowed_fd=os.open(outside,os.O_RDONLY)
denied_fd=os.open('/Users/lowell/Projects/sec-edgar-local',os.O_RDONLY)
network_guard.install_checkout_policy(())
os.chdir('/Users/lowell/Projects/sec-edgar-local')
try:
    try:
        fd=os.open('locks',os.O_RDONLY,dir_fd=allowed_fd)
    except PermissionError:allowed=False
    else:allowed=os.read(fd,100)==b'outside fixture';os.close(fd)
    os.chdir(outside)
    try:
        fd=os.open('.git/HEAD',os.O_RDONLY,dir_fd=denied_fd)
    except PermissionError:denied=True
    else:denied=False;os.close(fd)
    print(json.dumps({'allowed':allowed,'denied':denied}))
finally:os.close(allowed_fd);os.close(denied_fd)
''')
        self.assertEqual(proof, {'allowed': True, 'denied': True})
