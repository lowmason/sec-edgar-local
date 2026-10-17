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
