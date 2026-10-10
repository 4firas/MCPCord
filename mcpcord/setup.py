"""User-run setup. No background services, browser token forms, or silent collection."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .credentials import provider_name, store_credential
from .live import validate_scope
from .reader import ReaderError, strict_json

DEFAULT_SCOPE = {"mode": "discover_accessible", "max_window_hours": 168, "max_history_days": 7,
                 "max_pages_per_channel": 10, "max_requests_per_refresh": 20}


def config_directory():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "MCPCord"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/MCPCord"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "mcpcord"


def server_arguments(scope_path):
    return [sys.executable, "-B", "-m", "mcpcord", "serve-live", "--scope", str(scope_path),
            "--enable-network", "--personal-account-risk-accepted", "--discover-accessible"]


def existing_registration(codex):
    for name in ("mcpcord", "discord_live_readonly"):
        result = subprocess.run([codex, "mcp", "get", name, "--json"], capture_output=True, timeout=10, check=False)
        if result.returncode == 0:
            config = strict_json(result.stdout)
            args = config.get("transport", {}).get("args", [])
            if "serve-live" not in args or not any("mcpcord" in arg or arg.endswith("run_reader.py") for arg in args):
                raise ReaderError("The MCPCord registration name is already used by a different command; nothing was overwritten.")
            if not config.get("enabled", False):
                raise ReaderError("An existing MCPCord registration is disabled. Enable it explicitly in your client; no duplicate was added.")
            return name
    return None


def run_setup(args):
    directory = Path(args.config_dir).expanduser().absolute() if args.config_dir else config_directory()
    scope_path = directory / "scope.json"
    codex = shutil.which("codex")
    command = server_arguments(scope_path)
    if args.dry_run:
        print(json.dumps({"config_directory": str(directory), "server_command": command,
                          "credential_storage": "OS credential store; entered locally", "content_cache": "disabled",
                          "network_requested": False, "registration_changed": False}, indent=2))
        return 0
    if not args.no_register and codex is None:
        raise ReaderError("Install the Codex CLI first, or use --no-register for another STDIO MCP client.")
    if not args.accept_account_risk:
        if not sys.stdin.isatty():
            raise ReaderError("Interactive setup is required to acknowledge personal-account risk.")
        print("Discord does not approve personal-account automation. This can put your account at risk.")
        print("MCPCord uses GET requests, but the token itself is not read-scoped.")
        if input("Continue with that understood? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Stopped. Nothing configured.")
            return 1
    if directory.is_symlink():
        raise ReaderError("Configuration directory must not be a symlink.")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if sys.platform != "win32":
        if directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
            raise ReaderError("Configuration directory must belong to you and have mode 0700.")
    if scope_path.is_symlink():
        raise ReaderError("Scope configuration must not be a symlink.")
    if scope_path.exists():
        validate_scope(strict_json(scope_path.read_bytes()))
    else:
        fd = os.open(scope_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(DEFAULT_SCOPE, handle, indent=2)
            handle.write("\n")
    registration = existing_registration(codex) if not args.no_register and codex is not None else None
    if not args.no_token and registration is None:
        print(f"Credential storage: {provider_name()}. Never paste your token into chat or a website.")
        store_credential()
        print("Credential saved locally.")
    if registration and not args.no_token:
        print("Keeping the existing credential setup. Use mcpcord auth --replace to change it.")
    if not args.no_register:
        assert codex is not None
        if registration:
            print(f"Keeping the existing {registration} registration. No duplicate added.")
        else:
            result = subprocess.run([codex, "mcp", "add", "mcpcord", "--", *command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=15)
            if result.returncode:
                raise ReaderError("Codex registration failed. The local credential and scope are saved; no connection was claimed.")
            registration = "mcpcord"
            print("MCPCord registered in local Codex.")
    print("Setup saved. No messages collected. No content cache or schedule enabled.")
    if registration:
        print("Reconnect MCP or open a new local Codex session to load the tools.")
    else:
        print("STDIO command: " + json.dumps(command))
    return 0
