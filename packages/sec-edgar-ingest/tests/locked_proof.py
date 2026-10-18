from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import json
import platform
import re
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path


def proof_catalog():
    """Read the closed, test-only catalog before any artifact or build effects."""
    import os
    raw = os.environ.get('SEC_LOCAL_PROOF_CATALOG')
    if not raw:
        return None
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate proof catalog field')
            value[key] = item
        return value
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError('proof catalog path must be absolute')
    value = json.loads(path.read_text(), object_pairs_hook=unique)
    if (not isinstance(value, dict)
            or set(value) != {'format_version', 'a_manifest', 'b_manifest', 'harness'}
            or value['format_version'] != 'sec-local-proof-catalog-v1'):
        raise ValueError('invalid proof catalog schema/version')
    for name in ('a_manifest', 'b_manifest', 'harness'):
        if not isinstance(value[name], str) or not Path(value[name]).is_absolute():
            raise ValueError('proof catalog paths must be absolute')
    return value


def proof_harness(default):
    """Select the catalog harness at a factory or proof-driver boundary."""
    catalog = proof_catalog()
    harness = Path(catalog['harness']) if catalog else Path(default)
    return explicit_proof_harness(harness)


def explicit_proof_harness(harness):
    """Validate an already selected harness without consulting the environment."""
    harness = Path(harness)
    if not harness.is_absolute() or not harness.is_dir():
        raise ValueError('proof harness must be an existing absolute directory')
    return harness


def normalized(name):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name):
        raise ValueError('invalid distribution name')
    return re.sub(r'[-_.]+', '-', name).lower()


def marker_environment():
    return {'implementation_name': sys.implementation.name,
            'platform_python_implementation': platform.python_implementation()}


def _marker(expression, environment):
    if not expression:
        return True
    tree = ast.parse(expression, mode='eval')

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Name):
            if node.id not in environment:
                raise ValueError('unknown accepted-lock marker environment name')
            return environment[node.id]
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            values = [evaluate(value) for value in node.values]
            if any(type(value) is not bool for value in values):
                raise ValueError('marker boolean operands must be comparisons')
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.Compare) and len(node.ops) == len(node.comparators) == 1:
            left, right = evaluate(node.left), evaluate(node.comparators[0])
            if not isinstance(left, str) or not isinstance(right, str):
                raise ValueError('accepted-lock marker comparison requires strings')
            if isinstance(node.ops[0], ast.Eq):
                return left == right
            if isinstance(node.ops[0], ast.NotEq):
                return left != right
        raise ValueError('unsupported expression in the accepted lock marker')

    result = evaluate(tree)
    if type(result) is not bool:
        raise ValueError('lock marker must evaluate to a boolean')
    return result


def requirement_blocks(export_text):
    records, parts, name = [], [], None
    for line in export_text.splitlines(keepends=True):
        match = re.match(r'^([A-Za-z0-9][A-Za-z0-9_.-]*)==', line)
        if match:
            if name is not None:
                records.append((name, ''.join(parts)))
            name, parts = normalized(match.group(1)), [line]
        elif name is not None:
            parts.append(line)
        elif line.strip() and not line.lstrip().startswith('#'):
            raise ValueError('unexpected directive before locked requirements')
    if name is not None:
        records.append((name, ''.join(parts)))
    return records


def locked_requirements(lock_body, export_text, environment):
    lock = tomllib.loads(lock_body.decode('utf-8'))
    packages = {}
    for package in lock['package']:
        name = normalized(package['name'])
        if name in packages:
            raise ValueError('accepted lock contains ambiguous package alternatives')
        packages[name] = package
    if 'sec-edgar-ingest' not in packages:
        raise ValueError('lock lacks the reviewed distribution')
    active, visited, queue = {}, set(), ['sec-edgar-ingest']
    while queue:
        name = queue.pop()
        if name in visited:
            continue
        visited.add(name)
        package = packages[name]
        if name != 'sec-edgar-ingest':
            if 'registry' not in package['source']:
                raise ValueError('offline locked dependencies must retain registry artifact authority')
            active[name] = package['version']
        for dependency in package.get('dependencies', ()):
            if _marker(dependency.get('marker'), environment):
                target = normalized(dependency['name'])
                if target not in packages:
                    raise ValueError('locked dependency target is absent')
                queue.append(target)
    exported = {}
    for name, block in requirement_blocks(export_text):
        logical = ' '.join(line.rstrip().removesuffix('\\').strip()
            for line in block.splitlines() if line.strip() and not line.lstrip().startswith('#'))
        head, *hash_parts = logical.split('--hash=')
        match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s;]+)(?:\s*;\s*(.*))?\s*', head)
        if match is None or normalized(match.group(1)) != name:
            raise ValueError('export entry is not an exact pinned requirement')
        version, marker = match.group(2), match.group(3)
        if name not in packages or version != packages[name]['version']:
            raise ValueError('export version differs from accepted lock')
        hashes = set()
        for value in hash_parts:
            value = value.strip()
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', value):
                raise ValueError('export must retain only exact SHA256 artifact hashes')
            hashes.add(value)
        package = packages[name]
        expected_hashes = {artifact['hash'] for artifact in package.get('wheels', ())}
        if package.get('sdist'):
            expected_hashes.add(package['sdist']['hash'])
        if not hashes or hashes != expected_hashes:
            raise ValueError('export artifact hashes differ from accepted lock')
        if _marker(marker, environment):
            if name in exported:
                raise ValueError('duplicate active export entry')
            exported[name] = version
    if exported != active:
        raise ValueError('export dependency set differs from complete applicable lock graph')
    return dict(sorted(active.items()))


def installed_inventory():
    inventory = {}
    for distribution in importlib.metadata.distributions():
        name = normalized(distribution.metadata['Name'])
        if name in inventory:
            raise ValueError('duplicate installed distribution identity')
        inventory[name] = distribution.version
    return dict(sorted(inventory.items()))


def assert_inventory(expected, actual, distribution_version):
    wanted = {normalized(name): version for name, version in expected.items()}
    wanted['sec-edgar-ingest'] = distribution_version
    installed = {normalized(name): version for name, version in actual.items()}
    if installed != wanted:
        raise ValueError('installed dependency set differs: ' + json.dumps({
            'expected': wanted, 'actual': installed}, sort_keys=True))


def digest(path):
    body = Path(path).read_bytes()
    return {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}


def inventory(root):
    root = Path(root)
    return {path.relative_to(root).as_posix(): digest(path)
            for path in sorted(root.rglob('*')) if path.is_file() and path != root / 'sha256.json'}


def verify_inventory(root):
    root = Path(root)
    saved = json.loads((root / 'sha256.json').read_text())
    actual = inventory(root)
    if set(saved) != set(actual):
        raise ValueError('proof inventory membership differs')
    if saved != actual:
        raise ValueError('proof inventory bytes differ')


def package_inventory(source_root):
    source_root = Path(source_root)
    package = source_root / 'sec_edgar_ingest'
    if not package.is_dir():
        raise ValueError('production package directory is missing')
    return {path.relative_to(source_root).as_posix(): digest(path)
        for path in sorted(package.rglob('*'))
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'}


def assert_release_inventory(verified):
    """Independently compare a real installation with the full accepted lock graph."""
    import subprocess
    identity = verified.manifest['identity']
    expected = locked_requirements((verified.directory / 'uv.lock').read_bytes(),
        (verified.directory / 'runtime-requirements.txt').read_text(), marker_environment())
    code = ('import importlib.metadata as m,json,re; '
            'print(json.dumps({re.sub(r"[-_.]+","-",d.metadata["Name"]).lower():d.version '
            'for d in m.distributions()}))')
    from sec_edgar_ingest.runtime import native_python_argv
    result = subprocess.run([*native_python_argv(verified.python), '-c', code], check=True, capture_output=True, text=True)
    assert_inventory(expected, json.loads(result.stdout), identity['application']['version'])
    declared = {item['name']: item['version'] for item in identity['dependencies']}
    if declared != expected:
        raise ValueError('release artifact inventory differs from full transitive lock graph')


def verify_native_release(verified, harness, evidence):
    """Run the selected installed application with independently copied offline support."""
    import os
    import shutil
    import subprocess
    import tempfile
    from workflow_proof import harness_files
    from sec_edgar_ingest.runtime import isolated_environment, native_python_argv
    harness, evidence = explicit_proof_harness(harness), Path(evidence)
    if not evidence.is_absolute():
        raise ValueError('native verifier evidence must be absolute')
    evidence.mkdir(parents=True, exist_ok=False)
    environment = isolated_environment()
    with tempfile.TemporaryDirectory(prefix='sec-native-verifier-') as directory:
        outside = Path(directory)
        copied = outside / 'harness'
        copied.mkdir()
        for source in harness_files(harness):
            destination = copied / source.relative_to(harness)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        for source, name in ((verified.directory / 'uv.lock', 'accepted-uv.lock'),
                             (verified.directory / 'runtime-requirements.txt', 'requirements.txt')):
            shutil.copy2(source, copied / name)
        script = copied / 'verify_installed.py'
        script.write_text('''from network_guard import install
install()
import hashlib,json,os,pathlib,sys,subprocess
from locked_proof import locked_requirements,marker_environment,installed_inventory,assert_inventory,package_inventory
from sec_edgar_ingest.runtime import preflight_current
import sec_edgar_ingest
from workflow_proof import sequence
root=pathlib.Path(__file__).parent
release=preflight_current(pathlib.Path(sys.argv[1]))
expected=locked_requirements((root/'accepted-uv.lock').read_bytes(),(root/'requirements.txt').read_text(),marker_environment())
actual=installed_inventory()
assert_inventory(expected,actual,release.manifest['identity']['application']['version'])
base=pathlib.Path(sec_edgar_ingest.__file__).resolve().parent.parent
payload=package_inventory(base)
if {name:item['sha256'] for name,item in payload.items()} != {item['path']:item['sha256'] for item in release.manifest['identity']['package_files']}:
    raise ValueError('installed package payload differs from verified release')
if 'site-packages' not in base.parts: raise ValueError('application import outside installed release')
from sec_edgar_ingest.runtime import native_python_argv,isolated_environment,native_console_script
command_help={}
console=release.directory/'venv/bin/sec-edgar-ingest'
if console.read_bytes()!=native_console_script(release.python): raise ValueError('installed console bootstrap differs')
for command in ('discover','collect','transform','publish','backfill','daily','reconcile','candidates','approve','history','rollback'):
    bootstrap='from network_guard import install;install();import runpy,sys;sys.argv=["sec_edgar_ingest",*sys.argv[1:]];runpy.run_module("sec_edgar_ingest",run_name="__main__")'
    bootstrap='import sys;sys.path.insert(0,'+repr(str(root))+');'+bootstrap
    done=subprocess.run([*native_python_argv(release.python),'-c',bootstrap,command,'--help'],cwd=root.parent,env=isolated_environment(),capture_output=True,text=True,timeout=20)
    if done.returncode or 'usage:' not in done.stdout: raise ValueError('installed command help failed: '+command)
    command_help[command]={'exit':done.returncode,'stdout':done.stdout,'stderr':done.stderr,'entrypoint':'guarded installed module; exact console bootstrap verified'}
sequence_output=pathlib.Path(sys.argv[2])/'sequence'
sequence_output.mkdir()
report=sequence(sequence_output, release_manifest=release.directory/'release.json')
print(json.dumps({'exit':0,'pid':os.getpid(),'python':sys.executable,'import_root':str(base),'pythonpath_present':'PYTHONPATH' in os.environ,'release_id':release.release_id,'dependencies':actual,'payload':payload,'sequence':report,'command_help':command_help},sort_keys=True))
''')
        bootstrap = ('import runpy,sys;sys.path.insert(0,' + repr(str(copied)) + ');'
                     'sys.argv=[' + repr(str(script)) + ',*sys.argv[1:]];'
                     'runpy.run_path(' + repr(str(script)) + ',run_name="__main__")')
        argv = [*native_python_argv(verified.python), '-c', bootstrap,
                str(verified.directory / 'release.json'), str(evidence)]
        done = subprocess.run(argv, cwd=outside, env=environment, capture_output=True, text=True, timeout=600)
        (evidence / 'command.json').write_text(json.dumps({'argv': argv, 'cwd': str(outside),
            'exit': done.returncode, 'stdout': done.stdout, 'stderr': done.stderr}, indent=2) + '\n')
        if done.returncode:
            raise RuntimeError('native installed verifier failed: ' + done.stderr)
        report = json.loads(done.stdout)
        (evidence / 'report.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
        return report


def verify_wrong_transitive(verified, harness, evidence):
    """Reject real transitive drift in a fresh disposable retained-artifact installation."""
    import shutil
    import subprocess
    import tempfile
    from sec_edgar_ingest.release import reconstruct_release
    from sec_edgar_ingest.runtime import isolated_environment, native_python_argv, preflight
    harness, evidence = explicit_proof_harness(harness), Path(evidence)
    if not evidence.is_absolute():
        raise ValueError('transitive probe evidence must be absolute')
    evidence.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='sec-wrong-transitive-') as directory:
        outside = Path(directory)
        rebuilt = reconstruct_release(verified.directory / 'release.json', outside / 'releases',
                                      python=Path(sys.executable))
        disposable = preflight(rebuilt / 'release.json')
        site = next((rebuilt / 'venv/lib').glob('python*/site-packages'))
        metadata = next(site.glob('urllib3-*.dist-info/METADATA'))
        before = digest(metadata)
        original = metadata.read_bytes()
        altered, count = re.subn(rb'(?m)^Version: [^\r\n]+', b'Version: 0.0.0', original)
        if count != 1 or altered == original:
            raise AssertionError('probe must change exactly one transitive distribution version')
        metadata.write_bytes(altered)
        after = digest(metadata)
        copied = outside / 'harness'
        copied.mkdir()
        for name in ('network_guard.py', 'locked_proof.py'):
            shutil.copy2(harness / name, copied / name)
        code = ('import sys;sys.path.insert(0,' + repr(str(copied)) + ');'
                'from network_guard import install;install();'
                'import json,pathlib;from locked_proof import installed_inventory,assert_inventory;'
                'actual=installed_inventory();print(json.dumps(actual,sort_keys=True),flush=True);'
                'release=json.loads(pathlib.Path(sys.argv[1]).read_text());'
                'expected={item["name"]:item["version"] for item in release["identity"]["dependencies"]};'
                'assert_inventory(expected,actual,release["identity"]["application"]["version"])')
        argv = [*native_python_argv(disposable.python), '-c', code, str(rebuilt / 'release.json')]
        done = subprocess.run(argv, cwd=outside, env=isolated_environment(),
                              capture_output=True, text=True, timeout=60)
        probe = {'argv': argv, 'cwd': str(outside), 'exit': done.returncode,
                 'stdout': done.stdout, 'stderr': done.stderr}
        (evidence / 'inventory-command.json').write_text(json.dumps(probe, indent=2) + '\n')
        actual = json.loads(done.stdout)
        expected = {item['name']: item['version'] for item in verified.manifest['identity']['dependencies']}
        wanted = {**expected, 'sec-edgar-ingest': verified.manifest['identity']['application']['version']}
        if (done.returncode == 0 or 'installed dependency set differs' not in done.stderr
                or actual != {**wanted, 'urllib3': '0.0.0'}):
            raise AssertionError('isolated installed inventory did not reject only transitive drift')
        direct = {name: actual[name] for name in ('requests', 'pyarrow')}
        if direct != {'requests': '2.34.2', 'pyarrow': '25.0.1'}:
            raise AssertionError('wrong-transitive probe changed a required direct pin')
        try:
            verify_native_release(disposable, harness, evidence / 'native-verifier')
        except RuntimeError:
            native = json.loads((evidence / 'native-verifier/command.json').read_text())
        else:
            raise AssertionError('native verifier accepted the wrong installed transitive version')
        if native['exit'] == 0 or 'installed dependency inventory differs' not in native['stderr']:
            raise AssertionError('native verifier failed for a reason other than transitive inventory drift')
        report = {'exit': 0, 'outcome': 'refused', 'release_id': verified.release_id,
                  'disposable_python': str(disposable.python), 'metadata': str(metadata),
                  'metadata_before': before, 'metadata_after': after, 'direct_pins': direct,
                  'expected_transitive': expected['urllib3'], 'actual_transitive': actual['urllib3'],
                  'actual_inventory': actual, 'inventory_probe': probe, 'native_verifier': native}
        (evidence / 'report.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        return report
