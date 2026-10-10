import argparse
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import uuid

from mcpcord import credentials
from mcpcord.live import boundary_id
from mcpcord.mcp_client import RegisteredSession
from mcpcord.reader import ReaderError
from mcpcord.setup import existing_registration, run_setup
from mcpcord.store import HistoryStore


def arguments(directory, **updates):
    data = dict(config_dir=directory, dry_run=False, no_register=True,
                no_token=True, accept_account_risk=True)
    return argparse.Namespace(**(data | updates))


class SetupTests(unittest.TestCase):
    def test_dry_run_does_not_create_directory_read_credential_or_register(self):
        with tempfile.TemporaryDirectory() as tmp, patch("subprocess.run") as run, patch("mcpcord.setup.store_credential") as auth:
            directory = Path(tmp) / "new"
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(run_setup(arguments(str(directory), dry_run=True, no_register=False, no_token=False)), 0)
            result = json.loads(output.getvalue())
            self.assertFalse(directory.exists())
            self.assertFalse(result["network_requested"])
            self.assertFalse(result["registration_changed"])
            auth.assert_not_called()
            run.assert_not_called()

    def test_credential_free_setup_preserves_valid_scope(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), patch("mcpcord.setup.store_credential") as auth:
            directory = Path(tmp) / "config"
            self.assertEqual(run_setup(arguments(str(directory))), 0)
            target = directory / "scope.json"
            before = target.read_bytes()
            self.assertEqual(run_setup(arguments(str(directory))), 0)
            self.assertEqual(target.read_bytes(), before)
            self.assertNotIn("token", before.decode().lower())
            auth.assert_not_called()

    def test_risk_acknowledgment_precedes_any_configuration(self):
        with tempfile.TemporaryDirectory() as tmp, patch("sys.stdin.isatty", return_value=False):
            directory = Path(tmp) / "new"
            with self.assertRaises(ReaderError):
                run_setup(arguments(str(directory), accept_account_risk=False))
            self.assertFalse(directory.exists())

    def test_registration_uses_local_interpreter_and_no_token_or_cache(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), patch("shutil.which", return_value="codex"), patch("mcpcord.setup.existing_registration", return_value=None), patch("subprocess.run", return_value=Mock(returncode=0)) as run:
            run_setup(arguments(str(Path(tmp) / "config"), no_register=False))
            command = run.call_args.args[0]
            self.assertEqual(command[:5], ["codex", "mcp", "add", "mcpcord", "--"])
            self.assertEqual(command[5], sys.executable)
            self.assertIn("--discover-accessible", command)
            self.assertNotIn("--history-store", command)
            self.assertNotIn("--enable-content-cache", command)

    def test_existing_registration_is_kept_without_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()), patch("shutil.which", return_value="codex"), patch("mcpcord.setup.existing_registration", return_value="discord_live_readonly"), patch("subprocess.run") as run:
            with patch("mcpcord.setup.store_credential") as auth:
                run_setup(arguments(str(Path(tmp) / "config"), no_register=False, no_token=False))
                auth.assert_not_called()
            run.assert_not_called()

    def test_disabled_or_unrelated_registration_fails_explicitly(self):
        for config in ({"enabled": False, "transport": {"args": ["-m", "mcpcord", "serve-live"]}},
                       {"enabled": True, "transport": {"args": ["unrelated"]}}):
            with patch("subprocess.run", return_value=Mock(returncode=0, stdout=json.dumps(config).encode())):
                with self.assertRaises(ReaderError):
                    existing_registration("codex")

    @unittest.skipIf(sys.platform == "win32", "POSIX symlink test")
    def test_broken_scope_symlink_is_rejected_without_following(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "scope.json").symlink_to(directory / "outside")
            with self.assertRaises(ReaderError):
                run_setup(arguments(str(directory)))
            self.assertFalse((directory / "outside").exists())

    def test_windows_memory_history_works_but_disk_is_rejected(self):
        with patch("sys.platform", "win32"):
            store = HistoryStore()
            store.close()
            with self.assertRaisesRegex(ReaderError, "macOS/Linux"):
                HistoryStore("unused.sqlite3", enable_persistence=True)

    def test_discord_epoch_is_valid_query_boundary(self):
        self.assertEqual(boundary_id("2015-01-01T00:00:00Z"), "0")


class CredentialTests(unittest.TestCase):
    def test_invalid_values_are_rejected_without_echoing(self):
        for value in ("", "has whitespace", "line\nbreak", "é", "x" * 2049, None):
            with self.assertRaises(ReaderError):
                credentials.validate_secret(value)

    def test_noninteractive_entry_never_accepts_piped_token(self):
        with patch("mcpcord.credentials.provider_name", return_value="test"), patch("sys.stdin.isatty", return_value=False), patch("getpass.getpass") as prompt:
            with self.assertRaises(ReaderError):
                credentials.store_credential()
            prompt.assert_not_called()

    def test_mac_prompt_has_no_token_argument(self):
        with patch("sys.platform", "darwin"), patch("sys.stdin.isatty", return_value=True), patch("subprocess.run", return_value=Mock(returncode=0)) as run:
            credentials.store_credential(replace=True)
            command = run.call_args.args[0]
            self.assertEqual(command[-1], "-w")
            self.assertIn("-U", command)
            self.assertEqual(command[command.index("-T") + 1], "")
            self.assertNotIn("input", run.call_args.kwargs)

    def test_linux_prompt_passes_secret_only_via_stdin(self):
        with patch("sys.platform", "linux"), patch("shutil.which", return_value="/synthetic/secret-tool"), patch("sys.stdin.isatty", return_value=True), patch("getpass.getpass", return_value="fabricated-value"), patch("subprocess.run", return_value=Mock(returncode=0)) as run:
            credentials.store_credential()
            self.assertNotIn("fabricated-value", run.call_args.args[0])
            self.assertEqual(run.call_args.kwargs["input"], b"fabricated-value")
            self.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_linux_missing_store_fails_without_authentication(self):
        with patch("sys.platform", "linux"), patch("shutil.which", return_value=None), patch("subprocess.run") as run:
            with self.assertRaises(ReaderError):
                credentials.read_credential()
            run.assert_not_called()

    def test_windows_mock_does_not_put_secret_in_subprocess(self):
        with patch("sys.platform", "win32"), patch("sys.stdin.isatty", return_value=True), patch("getpass.getpass", return_value="fabricated-value"), patch("mcpcord.credentials._windows_write") as write, patch("subprocess.run") as run:
            credentials.store_credential()
            write.assert_called_once_with("fabricated-value")
            run.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "Windows native credential-store roundtrip")
    def test_windows_native_roundtrip_uses_unique_synthetic_item_and_cleans_up(self):
        from ctypes import wintypes
        target = "MCPCord-Test/" + uuid.uuid4().hex
        with patch("mcpcord.credentials.WINDOWS_TARGET", target):
            api, _ = credentials._windows_api()
            api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
            api.CredDeleteW.restype = wintypes.BOOL
            try:
                credentials._windows_write("synthetic-test-only")
                self.assertEqual(credentials.read_credential(), "synthetic-test-only")
            finally:
                api.CredDeleteW(target, 1, 0)


class ClientTests(unittest.TestCase):
    def test_initialization_failure_closes_spawned_process(self):
        process = Mock()
        config = {"name": "mcpcord", "enabled": True, "transport": {"type": "stdio", "command": "python", "args": ["-m", "mcpcord", "serve-live"]}}
        with patch("mcpcord.setup.existing_registration", return_value="mcpcord"), patch("subprocess.run", return_value=Mock(stdout=json.dumps(config).encode())), patch("subprocess.Popen", return_value=process), patch("threading.Thread"), patch.object(RegisteredSession, "request", side_effect=ReaderError("handshake failed")):
            with self.assertRaises(ReaderError):
                RegisteredSession(codex="codex")
            process.terminate.assert_called_once()
            process.stdin.close.assert_called_once()
            process.stdout.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
