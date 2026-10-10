"""Call the registered MCPCord server on demand. Input: one tool-call JSON per line."""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mcpcord.mcp_client import RegisteredSession
from mcpcord.reader import ReaderError, strict_json

try:
    with RegisteredSession() as session:
        for line in sys.stdin:
            request = strict_json(line)
            if set(request) - {"name", "arguments"} or not isinstance(request.get("name"), str):
                raise ReaderError("Provide a tool name and arguments only.")
            print(json.dumps(session.call(request["name"], request.get("arguments", {})), ensure_ascii=True), flush=True)
except (ReaderError, OSError):
    print('{"error":"Local MCPCord request failed; no raw configuration or credential was logged."}', file=sys.stderr)
    raise SystemExit(2) from None
