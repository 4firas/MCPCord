"""Synthetic-only bounded index benchmark. Never imports a credential provider value."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mcpcord.live import api_to_export, boundary_id
from mcpcord.reader import normalize_message, timestamp
from mcpcord.store import HistoryStore

count = int(sys.argv[1]) if len(sys.argv) > 1 else 50000
if not 100 <= count <= 100000:
    raise SystemExit("Choose 100-100000 synthetic messages.")
now = datetime(2026, 10, 10, tzinfo=timezone.utc)
start = datetime(2020, 1, 1, tzinfo=timezone.utc)
channels = [{"id": str(100 + i), "guild_id": "999", "name": f"Synthetic {i}",
             "guild_name": "Synthetic benchmark", "type": "GuildTextChat"} for i in range(10)]
store = HistoryStore(now=lambda: now)
began = time.perf_counter()
for base in range(0, count, 100):
    batches = {c["id"]: [] for c in channels}
    for index in range(base, min(base + 100, count)):
        channel = channels[index % 10]
        stamp = timestamp((start + timedelta(minutes=index)).isoformat())
        raw = {"id": str(int(boundary_id(stamp)) + 1), "channel_id": channel["id"], "timestamp": stamp,
               "author": {"id": str(1000 + index % 1000), "username": "Repeated display name"},
               "content": "Synthetic benchmark text, never a real conversation.", "type": 0,
               "mentions": [{"id": "1501"}] if index % 7 == 0 else []}
        batches[channel["id"]].append(normalize_message(api_to_export(raw, channel), channel, timestamp(now.isoformat()), "synthetic-benchmark"))
    for channel in channels:
        if batches[channel["id"]]:
            store.ingest(channel, batches[channel["id"]])
ingest_seconds = time.perf_counter() - began
ids = [c["id"] for c in channels]
since, until = timestamp(start.isoformat()), timestamp(now.isoformat())
measurements = {}
for relationship in ("author", "mention", "reply"):
    began = time.perf_counter()
    result = store.query(ids, since, until, "1501", relationship)
    measurements[relationship + "_first_page_seconds"] = time.perf_counter() - began
began = time.perf_counter()
summary = store.analyze(ids, since, until, timezone="America/New_York")
measurements["all_message_activity_seconds"] = time.perf_counter() - began
assert summary["visible_message_count"] == count
assert store.metric("count") == count
peak_mib = None
if sys.platform != "win32":
    import resource
    usage = resource.getrusage(resource.RUSAGE_SELF)
    peak_bytes = usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024
    peak_mib = peak_bytes / 1024**2
print(json.dumps({"synthetic_messages": count, "channels": 10, "authors": 1000,
                  "ingest_seconds": ingest_seconds, "messages_per_second": count / ingest_seconds,
                  **measurements, "peak_process_rss_mib": peak_mib,
                  "normalized_payload_mib": store.metric("bytes") / 1024**2,
                  "sqlite_pages_mib": store.db.execute("PRAGMA page_count").fetchone()[0] * store.db.execute("PRAGMA page_size").fetchone()[0] / 1024**2,
                  "network_requests": 0, "persistence": False}, indent=2))
store.close()
