"""Build artifact smoke test from a clean environment outside the source checkout."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import venv


root = Path(__file__).resolve().parents[1]
version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
wheel = root / "dist" / f"mcpcord-{version}-py3-none-any.whl"
assert wheel.is_file(), "Build the current version before running the install smoke test."
with tempfile.TemporaryDirectory(prefix="mcpcord-install-") as tmp:
    work = Path(tmp)
    environment = work / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    binary = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    executable = environment / ("Scripts/mcpcord.exe" if os.name == "nt" else "bin/mcpcord")
    subprocess.run([str(binary), "-m", "pip", "install", "--disable-pip-version-check", str(wheel)], check=True, cwd=work)
    result = subprocess.run([str(executable), "setup", "--dry-run"], check=True, cwd=work, capture_output=True, text=True)
    dry = json.loads(result.stdout)
    assert not dry["network_requested"] and not dry["registration_changed"]
    assert Path(dry["server_command"][0]).parent.resolve() == binary.parent.resolve()
    subprocess.run([str(executable), "setup", "--no-token", "--no-register", "--accept-account-risk",
                    "--config-dir", str(work / "config")], check=True, cwd=work, capture_output=True)
    wire = "\n".join(json.dumps(frame) for frame in (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_channels", "arguments": {}}},
    )) + "\n"
    process = subprocess.run([str(executable), "--export", str(root / "fixtures/server.json"), "serve"],
                             input=wire, capture_output=True, text=True, cwd=work, timeout=10, check=True)
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    assert replies[0]["result"]["serverInfo"]["name"] == "mcpcord"
    assert replies[0]["result"]["serverInfo"]["version"] == version
    assert len(replies[1]["result"]["tools"]) == 4
    assert replies[2]["result"]["structuredContent"]["data"]["channels"]
    assert not process.stderr
print("Clean wheel install, credential-free setup and STDIO archive handshake passed.")
