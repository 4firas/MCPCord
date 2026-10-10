from datetime import timedelta
import os
import sys
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from mcpcord.discovery import DiscoveryReader
from mcpcord.live import api_to_export, boundary_id
from mcpcord.live_transport import LiveError
from mcpcord.reader import ReaderError, normalize_message, timestamp
from mcpcord.store import HistoryStore
from tests.test_discovery import GID, UID, guild, scope
from tests.test_live import CID, NOW, SINCE, UNTIL, Clock, message

META = {"id": CID, "guild_id": GID, "guild_name": "Synthetic guild", "name": "Synthetic", "type": "GuildTextChat"}


def norm(raw=None, observed=NOW):
    return normalize_message(api_to_export(raw or message(), META), META, timestamp(observed.isoformat()), "synthetic")


class StoreTests(unittest.TestCase):
    @unittest.skipIf(sys.platform == "win32", "Disk persistence is supported on POSIX only")
    def test_abrupt_process_exit_recovers_uncommitted_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crash.sqlite3"
            store = HistoryStore(path, enable_persistence=True, now=lambda: NOW)
            job = store.create_job({CID: META}, timestamp(SINCE), timestamp(UNTIL), True)
            store.close()
            script = """
import os, sys
from mcpcord.store import HistoryStore
from tests.test_history import NOW, CID, norm
store = HistoryStore(sys.argv[1], enable_persistence=True, now=lambda: NOW)
job = store.job(sys.argv[2])
original = store._upsert
def crash(row):
    original(row)
    os._exit(42)
store._upsert = crash
store.commit_page(job['job_id'], CID, job['channels'][0]['before_id'], norm()['id'], [norm()], False)
"""
            result = subprocess.run([sys.executable, "-B", "-c", script, str(path), job["job_id"]],
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 42)
            reopened = HistoryStore(path, enable_persistence=True, now=lambda: NOW)
            try:
                self.assertEqual(reopened.metric("count"), 0)
                self.assertEqual(reopened.job(job["job_id"])["channels"][0]["before_id"], job["channels"][0]["before_id"])
                reopened.commit_page(job["job_id"], CID, job["channels"][0]["before_id"], norm()["id"], [norm()], False)
                self.assertEqual(reopened.metric("count"), 1)
            finally:
                reopened.close()

    def setUp(self):
        self.store = HistoryStore(now=lambda: NOW)

    def tearDown(self):
        self.store.close()

    @unittest.skipIf(sys.platform == "win32", "Disk persistence is supported on POSIX only")
    def test_persistence_requires_explicit_flag_and_private_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "history.sqlite3"
            with self.assertRaises(ReaderError):
                HistoryStore(target, now=lambda: NOW)
            self.assertFalse(target.exists())
            disk = HistoryStore(target, enable_persistence=True, now=lambda: NOW)
            disk.close()
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            target.unlink()
            os.chmod(tmp, 0o755)  # noqa: S103 - verify insecure directories are rejected
            with self.assertRaises(ReaderError):
                HistoryStore(target, enable_persistence=True, now=lambda: NOW)
            self.assertFalse(target.exists())

    @unittest.skipIf(sys.platform == "win32", "Disk persistence is supported on POSIX only")
    def test_persistence_rejects_final_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "history.sqlite3"
            target.symlink_to(Path(tmp) / "elsewhere")
            with self.assertRaises(ReaderError):
                HistoryStore(target, enable_persistence=True, now=lambda: NOW)

    def test_repeated_ingest_deduplicates_and_cannot_rollback_edits(self):
        first = norm()
        self.store.ingest(META, [first])
        self.store.ingest(META, [first])
        edit = message(content="Edited")
        edit["edited_timestamp"] = "2026-10-09T13:00:00Z"
        self.store.ingest(META, [norm(edit, NOW + timedelta(seconds=1))])
        self.store.ingest(META, [norm(observed=NOW + timedelta(seconds=2))])
        result = self.store.query([CID], SINCE, UNTIL)
        self.assertEqual(self.store.metric("count"), 1)
        self.assertEqual(result["messages"][0]["content"], "Edited")

    def test_quota_failure_rolls_back_whole_page(self):
        self.store.max_messages = 1
        with self.assertRaises(ReaderError):
            self.store.ingest(META, [norm(message(sequence=1)), norm(message(sequence=2))])
        self.assertEqual(self.store.metric("count"), 0)
        self.assertEqual(self.store.metric("bytes"), 0)

    def test_exact_mentions_and_replies_resolve_from_index(self):
        original = norm()
        reply = message(sequence=2)
        reply["author"]["id"] = "99"
        reply.update({"type": 19, "message_reference": {"message_id": original["id"]}, "mentions": [{"id": UID}]})
        self.store.ingest(META, [original, norm(reply)])
        self.assertEqual(len(self.store.query([CID], SINCE, UNTIL, UID, "author")["messages"]), 1)
        for relationship in ("mention", "reply"):
            rows = self.store.query([CID], SINCE, UNTIL, UID, relationship)["messages"]
            self.assertEqual([r["author"]["id"] for r in rows], ["99"])
        self.assertEqual(self.store.analyze([CID], SINCE, UNTIL, UID, "reply")["visible_message_count"], 1)

    def test_keyset_pages_reject_changed_index(self):
        self.store.ingest(META, [norm(message(sequence=i)) for i in range(1, 4)])
        first = self.store.query([CID], SINCE, UNTIL, limit=1)
        second = self.store.query([CID], SINCE, UNTIL, limit=1, cursor=first["next_cursor"])
        self.assertNotEqual(first["messages"][0]["id"], second["messages"][0]["id"])
        self.store.ingest(META, [norm(message(sequence=4))])
        with self.assertRaises(ReaderError):
            self.store.query([CID], SINCE, UNTIL, limit=1, cursor=second["next_cursor"])

    def test_half_open_window_and_timezone_analysis(self):
        a = norm()
        b = norm(message(sequence=2))
        b["timestamp"] = timestamp(UNTIL)
        self.store.ingest(META, [a, b])
        self.assertEqual(len(self.store.query([CID], SINCE, UNTIL)["messages"]), 1)
        result = self.store.analyze([CID], SINCE, UNTIL, timezone="America/Los_Angeles")
        self.assertEqual(result["visible_message_count"], 1)
        self.assertEqual(result["timezone"], "America/Los_Angeles")

    def test_retention_uses_observation_age_and_removes_orphan_metadata(self):
        ancient = norm()
        ancient["timestamp"] = "2016-01-01T00:00:00.000000Z"
        self.store.ingest(META, [ancient])
        self.assertEqual(self.store.purge_expired(), 0)  # old messages freshly observed survive
        self.store.now = lambda: NOW + timedelta(days=15)
        self.assertEqual(self.store.purge_expired(), 1)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM channels").fetchone()[0], 0)

    @unittest.skipIf(sys.platform == "win32", "Disk persistence is supported on POSIX only")
    def test_crash_between_record_and_checkpoint_rolls_back_and_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.sqlite3"
            store = HistoryStore(path, enable_persistence=True, now=lambda: NOW)
            job = store.create_job({CID: META}, timestamp(SINCE), timestamp(UNTIL), False)
            jid = job["job_id"]
            before = job["channels"][0]["before_id"]
            original = store._upsert
            def interrupted(row):
                original(row)
                raise KeyboardInterrupt()
            with patch.object(store, "_upsert", side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
                store.commit_page(jid, CID, before, norm()["id"], [norm()], False)
            store.close()
            reopened = HistoryStore(path, enable_persistence=True, now=lambda: NOW)
            self.assertEqual(reopened.metric("count"), 0)
            self.assertEqual(reopened.job(jid)["channels"][0]["before_id"], before)
            reopened.commit_page(jid, CID, before, norm()["id"], [norm()], False)
            self.assertEqual(reopened.metric("count"), 1)
            with self.assertRaises(ReaderError):
                reopened.commit_page(jid, CID, before, norm()["id"], [norm()], False)
            reopened.close()


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.client = Clock(), Mock()
        self.reader = DiscoveryReader(scope(), client=self.client, now=lambda: NOW, monotonic=self.clock.mono)
        self.reader.channels[CID] = dict(META)
        self.reader.guilds[GID] = guild()

    def tearDown(self):
        if getattr(self.reader, "history_store", None):
            self.reader.history_store.close()

    def start(self, **kwargs):
        return self.reader.start_history_import(channel_ids=[CID], all_history=True, until=UNTIL, **kwargs)["data"]

    def test_start_never_fetches_and_requires_explicit_history_opt_in(self):
        with self.assertRaises(ReaderError):
            self.reader.start_history_import(channel_ids=[CID])
        job = self.start()
        self.assertEqual(job["request"]["since"], "2015-01-01T00:00:00.000000Z")
        self.assertFalse(job["network_requested"])
        self.assertFalse(job["restart_resumable"])
        self.client.messages.assert_not_called()

    def test_history_zero_one_hundred_and_hundred_one_messages(self):
        for count in (0, 1, 100, 101):
            rows = [message(sequence=i) for i in range(count, 0, -1)]
            pages = [rows[i:i + 100] for i in range(0, count, 100)] + [[]]
            self.client.messages.side_effect = pages
            job = self.start()
            result = self.reader.continue_history_import(job["job_id"], max_pages=5)["data"]
            self.assertEqual(result["state"], "traversed")
            self.assertFalse(result["exhaustive"])
            self.assertEqual(result["channels"][0]["observed_rows"], count)
            self.assertEqual(result["channels"][0]["pages"], len(pages))

    def test_short_page_continues_after_budget_pause(self):
        self.client.messages.side_effect = [[message()], []]
        job = self.start()
        first = self.reader.continue_history_import(job["job_id"], max_pages=1)["data"]
        self.assertEqual(first["state"], "paused")
        self.assertEqual(first["channels"][0]["before_id"], message()["id"])
        second = self.reader.continue_history_import(job["job_id"])["data"]
        self.assertEqual(second["state"], "traversed")

    def test_duplicate_or_stalled_page_keeps_checkpoint_and_reports_partial(self):
        job = self.start()
        for rows in ([message(), message()], [{**message(), "id": boundary_id(UNTIL)}]):
            self.client.messages.side_effect = None
            self.client.messages.return_value = rows
            result = self.reader.continue_history_import(job["job_id"])
            self.assertTrue(result["is_error"])
            self.assertEqual(result["data"]["channels"][0]["pages"], 0)
            self.assertEqual(result["data"]["stored_message_count"], 0)
            self.assertEqual(result["data"]["channels"][0]["before_id"], boundary_id(UNTIL))

    def test_cancel_stops_network_until_explicit_resume(self):
        self.client.messages.return_value = []
        job = self.start()
        self.reader.cancel_history_import(job["job_id"])
        with self.assertRaises(ReaderError):
            self.reader.continue_history_import(job["job_id"])
        self.client.messages.assert_not_called()
        result = self.reader.continue_history_import(job["job_id"], resume_cancelled=True)["data"]
        self.assertEqual(result["state"], "traversed")

    def test_access_denial_is_recorded_without_retries_or_complete_claim(self):
        self.client.messages.side_effect = LiveError("access_denied", "Denied")
        job = self.start()
        result = self.reader.continue_history_import(job["job_id"])["data"]
        self.assertEqual(result["state"], "partial")
        self.assertEqual(result["channels"][0]["error"], "access_denied")
        self.reader.continue_history_import(job["job_id"])
        self.client.messages.assert_called_once()

    def test_auth_failure_pauses_without_advancing(self):
        self.client.messages.side_effect = LiveError("authentication_failed", "Denied")
        job = self.start()
        result = self.reader.continue_history_import(job["job_id"])
        self.assertTrue(result["is_error"])
        self.assertEqual(result["data"]["state"], "paused")
        self.assertEqual(result["data"]["channels"][0]["pages"], 0)

    @unittest.skipIf(sys.platform == "win32", "Disk persistence is supported on POSIX only")
    def test_rate_limit_cooldown_survives_new_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.sqlite3"
            self.reader.history_store = HistoryStore(path, enable_persistence=True, now=lambda: NOW)
            self.client.messages.side_effect = LiveError("rate_limited", "Wait", 30.5)
            job = self.start()
            first = self.reader.continue_history_import(job["job_id"])["data"]
            self.assertIsNotNone(first["retry_at"])
            self.reader.history_store.close()
            self.reader.history_store = HistoryStore(path, enable_persistence=True, now=lambda: NOW)
            second = self.reader.continue_history_import(job["job_id"])["data"]
            self.assertIn("cooldown", second["continuation_blocked"])
            self.client.messages.assert_called_once()

    def test_restart_requires_rediscovery_not_cached_access_grants(self):
        job = self.start()
        self.reader.channels.clear()
        result = self.reader.continue_history_import(job["job_id"])["data"]
        self.assertIn("Rediscover", result["continuation_blocked"])
        self.client.messages.assert_not_called()

    def test_fixed_until_does_not_move_when_clock_advances(self):
        job = self.start()
        self.reader.now = lambda: NOW + timedelta(hours=1)
        self.client.messages.return_value = []
        self.reader.continue_history_import(job["job_id"])
        self.client.messages.assert_called_once_with(CID, boundary_id(UNTIL), 20)

    def test_server_job_captures_only_discovered_message_channels(self):
        job = self.reader.start_history_import(guild_id=GID, all_history=True)["data"]
        self.assertEqual(job["request"]["channel_ids"], [CID])
        self.assertIn("Undiscovered threads", job["request"]["coverage"])


if __name__ == "__main__":
    unittest.main()
