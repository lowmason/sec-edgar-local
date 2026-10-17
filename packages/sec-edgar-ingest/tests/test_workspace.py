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
                                   ("--version", "0.1.0")):
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
            "pyarrow==25.0.1", "requests==2.34.2", "azure-identity==1.26.0",
            "azure-storage-blob==12.31.0", "azure-data-tables==12.7.0",
        })

    def test_module_and_console_invocations(self):
        console = pathlib.Path(sys.executable).parent / "sec-edgar-ingest"
        for invocation in ((sys.executable, "-m", "sec_edgar_ingest"),
                           (str(console),)):
            for argument, expected in (("--help", "usage: sec-edgar-ingest"),
                                       ("--version", "0.1.0")):
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
