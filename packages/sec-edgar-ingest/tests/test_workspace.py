import contextlib
import importlib.metadata
import io
import pathlib
import subprocess
import sys
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]


class WorkspaceTests(unittest.TestCase):
    def test_only_ingest_is_a_workspace_member(self):
        root = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(root["tool"]["uv"]["workspace"]["members"],
                         ["packages/sec-edgar-ingest"])
        self.assertFalse(root["tool"]["uv"]["package"])
        self.assertNotIn("scripts", root["project"])
        package = tomllib.loads(
            (ROOT / "packages/sec-edgar-ingest/pyproject.toml").read_text())
        self.assertEqual(package["project"]["name"], "sec-edgar-ingest")
        self.assertEqual(package['project']['version'], '0.2.0')
        self.assertEqual(package['project']['requires-python'], '>=3.14')
        self.assertEqual((ROOT / '.python-version').read_text().strip(), '3.14')
        self.assertEqual(package['project']['dependencies'], ['pyarrow==25.0.1', 'requests==2.34.2'])
        self.assertEqual(package['build-system'], {'requires': ['uv_build>=0.12.15,<0.13.0'], 'build-backend': 'uv_build'})
        self.assertEqual(package["project"]["scripts"]["sec-edgar-ingest"],
                         "sec_edgar_ingest.cli:main")


class CliTests(unittest.TestCase):
    def test_main_without_arguments_prints_help(self):
        from sec_edgar_ingest.cli import main

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main([])
        self.assertEqual(result, 0)
        self.assertIn("usage: sec-edgar-ingest", output.getvalue())
        self.assertIn("discover", output.getvalue())
        self.assertIn("collect", output.getvalue())
        self.assertIn("transform", output.getvalue())
        self.assertIn("publish", output.getvalue())

    def test_main_help_and_version_exit_successfully(self):
        from sec_edgar_ingest.cli import main

        for argument, expected in (("--help", "usage: sec-edgar-ingest"),
                                   ("--version", "0.2.0")):
            with self.subTest(argument=argument):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    with self.assertRaises(SystemExit) as raised:
                        main([argument])
                self.assertEqual(raised.exception.code, 0)
                self.assertIn(expected, output.getvalue())

    def test_etl_commands_require_explicit_arguments(self):
        from sec_edgar_ingest.cli import main

        for command in ("transform", "publish"):
            with self.subTest(command=command):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        main([command])
                self.assertEqual(raised.exception.code, 2)

    def test_installed_distribution_exposes_the_cli(self):
        from sec_edgar_ingest import __version__
        from sec_edgar_ingest.cli import main

        distribution = importlib.metadata.distribution("sec-edgar-ingest")
        self.assertEqual(distribution.version, __version__)
        entry_points = [entry for entry in distribution.entry_points
                        if entry.group == "console_scripts"
                        and entry.name == "sec-edgar-ingest"]
        self.assertEqual(len(entry_points), 1)
        self.assertEqual(entry_points[0].value, "sec_edgar_ingest.cli:main")
        self.assertIs(entry_points[0].load(), main)
        requirements = set(distribution.requires or ())
        self.assertEqual(requirements, {
            "pyarrow==25.0.1", "requests==2.34.2",
        })

    def test_module_and_console_invocations(self):
        console = pathlib.Path(sys.executable).parent / "sec-edgar-ingest"
        for invocation in ((sys.executable, "-m", "sec_edgar_ingest"),
                           (str(console),)):
            for argument, expected in (("--help", "usage: sec-edgar-ingest"),
                                       ("--version", "0.2.0")):
                with self.subTest(invocation=invocation, argument=argument):
                    # Install the mandatory child guard before either installed entry point loads.
                    bootstrap = ("import sys; sys.path.insert(0, " + repr(str(pathlib.Path(__file__).parent)) + "); "
                                 "from network_guard import install; install(); import runpy; ")
                    if len(invocation) == 3:
                        bootstrap += "sys.argv=['sec_edgar_ingest', sys.argv[1]]; runpy.run_module('sec_edgar_ingest', run_name='__main__')"
                    else:
                        bootstrap += "sys.argv=[" + repr(str(console)) + ", sys.argv[1]]; runpy.run_path(sys.argv[0], run_name='__main__')"
                    result = subprocess.run([sys.executable, '-c', bootstrap, argument],
                                            capture_output=True, text=True,
                                            timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(expected, result.stdout)
                    self.assertEqual(result.stderr, "")


class OfflineCheckTests(unittest.TestCase):
    def test_complete_check_executes_every_declared_local_operation(self):
        import json
        import os
        import tempfile
        script = ROOT / 'scripts/check-sec-edgar-ingest.sh'
        self.assertTrue(script.is_file(), 'complete offline check entry point is absent')
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            log = root / 'commands.jsonl'
            shim = ('#!' + sys.executable + '\nimport json,os,sys\n'
                    'with open(os.environ["CHECK_LOG"],"a") as stream: '
                    'stream.write(json.dumps([os.path.basename(sys.argv[0]),*sys.argv[1:]])+"\\n")\n')
            for name in ('uv', 'git'):
                path = root / name
                path.write_text(shim)
                path.chmod(0o755)
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                       CHECK_LOG=str(log), SEC_LOCAL_PROOF_CACHE=str(root / 'cache'))
            done = subprocess.run(['sh', str(script)], cwd=root, env=env,
                                  capture_output=True, text=True, timeout=20)
            self.assertEqual(done.returncode, 0, done.stderr)
            commands = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(len(commands), 19)
            self.assertIn('network_guard.py', ' '.join(commands[0]))
            self.assertEqual(commands[0][-3:], ['-p', 'test_*.py', '-v'])
            build = next(argv for argv in commands if argv[:2] == ['uv', 'build'])
            self.assertIn('--require-build-hashes', build)
            helps = [argv[-2] for argv in commands if argv[-1] == '--help'
                     and argv[-3] == 'sec-edgar-ingest' and argv[-2] != 'sec-edgar-ingest']
            self.assertEqual(helps, ['discover', 'collect', 'transform', 'publish', 'backfill',
                'daily', 'reconcile', 'candidates', 'approve', 'history', 'rollback'])
            self.assertEqual(commands[-1], ['git', '-c', 'core.whitespace=cr-at-eol', 'diff', '--check'])

    def test_complete_check_preserves_guard_lock_and_explicit_backend_policy(self):
        script = ROOT / 'scripts/check-sec-edgar-ingest.sh'
        self.assertTrue(script.is_file(), 'complete offline check entry point is absent')
        body = script.read_text()
        self.assertTrue(body.startswith('#!/bin/sh\nset -eu\n'))
        self.assertIn("network_guard.py discover -s packages/sec-edgar-ingest/tests -p 'test_*.py' -v", body)
        self.assertNotIn('--frozen', body)
        for argument in ('--offline', '--locked', '--wheel --sdist', '--force-pep517',
                         '--require-build-hashes', '--preview-features build-dependency-hashes',
                         'compileall -q', 'diff --check'):
            self.assertIn(argument, body)
        self.assertIn('discover collect transform publish backfill daily reconcile candidates approve history rollback', body)
        for forbidden in ('genuine_live_driver', 'docker', 'bicep', 'az ', 'adf', 'stage-2'):
            self.assertNotIn(forbidden, body)

    def test_guard_is_active_before_discovered_test_import(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            probe = pathlib.Path(directory) / 'test_import_guard.py'
            probe.write_text("import socket,unittest\n"
                "with unittest.TestCase().assertRaises(AssertionError): socket.create_connection(('example.com',443))\n"
                "class GuardTest(unittest.TestCase):\n def test_import_was_guarded(self): pass\n")
            done = subprocess.run([sys.executable, str(ROOT / 'packages/sec-edgar-ingest/tests/network_guard.py'),
                'discover', '-s', directory, '-v'], capture_output=True, text=True, timeout=20)
            self.assertEqual(done.returncode, 0, done.stderr)
