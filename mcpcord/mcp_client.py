"""On-demand client for the existing local registration; no daemon or token access."""
import json
from pathlib import Path
import queue
import shutil
import threading
import subprocess
import time
from typing import Any

from .reader import ReaderError, strict_json

REGISTRATION = "mcpcord"
ROOT = Path(__file__).resolve().parents[1]


class RegisteredSession:
    def __init__(self, codex=None, timeout=35):
        self.timeout = timeout
        self.process = None
        self.responses: queue.Queue[dict[str, Any] | ReaderError] = queue.Queue(maxsize=4)
        self.counter = 0
        try:
            from .setup import existing_registration
            codex = codex or shutil.which("codex")
            if codex is None:
                raise ReaderError("Codex CLI is unavailable.")
            registration = existing_registration(codex)
            if registration is None:
                raise ReaderError("Run mcpcord setup first.")
            result = subprocess.run([codex, "mcp", "get", registration, "--json"],
                                    capture_output=True, timeout=10, check=True)
            config = strict_json(result.stdout)
            transport = config["transport"]
            command, args = transport["command"], transport["args"]
            if (config.get("name") != registration or not config.get("enabled")
                    or transport.get("type") != "stdio" or transport.get("env") or transport.get("env_vars")
                    or "serve-live" not in args):
                raise ReaderError("MCPCord registration differs from the reviewed local command; inspect it before use.")
            self.process = subprocess.Popen([command, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, cwd=transport.get("cwd") or ROOT)
            threading.Thread(target=self._read_responses, daemon=True).start()
            self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                       "clientInfo": {"name": "mcpcord-local-client", "version": "1"}})
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except ReaderError:
            self.close()
            raise
        except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError):
            self.close()
            raise ReaderError("Could not open the existing MCPCord registration; no raw configuration/error was logged.") from None

    def _send(self, frame):
        payload = (json.dumps(frame, ensure_ascii=True) + "\n").encode()
        if len(payload) > 65536:
            raise ReaderError("MCP request exceeds the local size limit.")
        process = self.process
        if process is None or process.stdin is None:
            raise ReaderError("MCPCord process is not open.")
        process.stdin.write(payload)
        process.stdin.flush()

    def request(self, method, params=None):
        self.counter += 1
        ident = self.counter
        self._send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}})
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                reply = self.responses.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                break
            if isinstance(reply, ReaderError):
                raise reply
            if reply.get("id") == ident:
                if "error" in reply:
                    raise ReaderError("MCPCord rejected the MCP request.")
                return reply["result"]
        raise ReaderError("MCPCord did not reply within the request deadline; no result claimed.")

    def _read_responses(self):
        try:
            process = self.process
            if process is None or process.stdout is None:
                return
            while True:
                line = process.stdout.readline(4 * 1024 * 1024 + 1)
                if not line:
                    self.responses.put(ReaderError("MCPCord process ended."), timeout=1)
                    break
                if len(line) > 4 * 1024 * 1024:
                    self.responses.put(ReaderError("MCP response exceeds the local size limit."), timeout=1)
                    break
                reply = strict_json(line)
                if not isinstance(reply, dict):
                    raise ReaderError("MCP response must be an object.")
                self.responses.put(reply, timeout=1)
        except (OSError, ValueError, ReaderError, queue.Full):
            try:
                self.responses.put_nowait(ReaderError("MCPCord returned an invalid response."))
            except queue.Full:
                pass  # The foreground request will time out; never print raw data.

    def call(self, name, arguments=None):
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})

    def close(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            for stream in (self.process.stdin, self.process.stdout):
                if stream is not None:
                    stream.close()
            self.process = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
