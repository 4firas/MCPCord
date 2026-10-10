"""Temporary localhost preview around the browser checks; always stops the server."""
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen


root = Path(__file__).resolve().parents[1]
node = shutil.which("node")
if node is None:
    raise SystemExit("Node.js 20+ is needed for website development checks.")
server = subprocess.Popen([sys.executable, "-m", "http.server", "4173", "--bind", "127.0.0.1",
                           "--directory", str(root / "website")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        if server.poll() is not None:
            raise SystemExit("The localhost preview could not start; check port 4173.")
        try:
            with urlopen("http://127.0.0.1:4173/", timeout=1):  # noqa: S310 - fixed localhost HTTP URL
                break
        except OSError:
            time.sleep(0.1)
    else:
        raise SystemExit("The localhost preview did not become ready.")
    subprocess.run([node, str(root / "scripts/browser_check.cjs")], check=True, cwd=root)
finally:
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait()
