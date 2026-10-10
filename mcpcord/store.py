"""Bounded SQLite index. Disk persistence is opt-in at process launch only."""
from contextlib import contextmanager
from datetime import timedelta
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import sys

from .analysis import activity
from .live import boundary_id, utc_now
from .reader import ReaderError, canonical, fingerprint, integer, snowflake, timestamp

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
INSERT OR IGNORE INTO meta VALUES ('schema',2),('revision',0),('count',0),('bytes',0);
CREATE TABLE IF NOT EXISTS channels(id TEXT PRIMARY KEY, guild_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages(
 channel_id TEXT NOT NULL REFERENCES channels(id), id TEXT NOT NULL, sort_id TEXT NOT NULL,
 stamp TEXT NOT NULL, author_id TEXT NOT NULL, author_kind TEXT NOT NULL,
 edited TEXT, observed TEXT NOT NULL, reply_user TEXT, reply_channel TEXT, reply_message TEXT,
 is_reply INTEGER NOT NULL, payload TEXT NOT NULL, size INTEGER NOT NULL,
 PRIMARY KEY(channel_id,id));
CREATE INDEX IF NOT EXISTS message_channel_time ON messages(channel_id,stamp,sort_id);
CREATE INDEX IF NOT EXISTS message_author_time ON messages(author_id,stamp,channel_id,sort_id);
CREATE INDEX IF NOT EXISTS message_time ON messages(stamp,channel_id,sort_id);
CREATE INDEX IF NOT EXISTS message_observed ON messages(observed);
CREATE TABLE IF NOT EXISTS mentions(user_id TEXT NOT NULL, channel_id TEXT NOT NULL, message_id TEXT NOT NULL,
 PRIMARY KEY(user_id,channel_id,message_id), FOREIGN KEY(channel_id,message_id) REFERENCES messages(channel_id,id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, state TEXT NOT NULL, request TEXT NOT NULL, updated TEXT NOT NULL, retry_at TEXT);
CREATE TABLE IF NOT EXISTS checkpoints(job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
 channel_id TEXT NOT NULL REFERENCES channels(id), before_id TEXT NOT NULL, state TEXT NOT NULL,
 pages INTEGER NOT NULL DEFAULT 0, observed_rows INTEGER NOT NULL DEFAULT 0, error TEXT, page_evidence TEXT,
 PRIMARY KEY(job_id,channel_id));
"""


class HistoryStore:
    def __init__(self, path=None, *, enable_persistence=False, retention_days=14,
                 max_messages=250000, max_bytes=128 * 1024 * 1024, now=utc_now):
        self.now = now
        self.retention_days = integer(retention_days, 1, 30)
        self.max_messages, self.max_bytes = max_messages, max_bytes
        self.persistent = path is not None
        self.cursors = {}
        if self.persistent and not enable_persistence:
            raise ReaderError("Persistent message storage is inactive; approval and an explicit launch flag are required.")
        if path is not None:
            if sys.platform == "win32":
                raise ReaderError("Persistent content storage currently requires macOS/Linux private filesystem permissions. In-memory history works on Windows.")
            path = Path(path)
            if not path.is_absolute() or path.is_symlink() or not path.parent.is_dir():
                raise ReaderError("Choose an absolute database path in an existing private directory; symlinks are rejected.")
            parent = path.parent.stat()
            if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) & 0o077:
                raise ReaderError("The database directory must be owned by this user with mode 0700.")
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                os.close(fd)
            except FileExistsError:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                    raise ReaderError("Existing database must be a user-owned private regular file.") from None
        try:
            self.db = sqlite3.connect(str(path) if path is not None else ":memory:", timeout=2, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=DELETE")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA secure_delete=ON")
            self.db.execute("PRAGMA cache_size=-8192")
            self.db.execute("PRAGMA temp_store=MEMORY")
            page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
            self.db.execute(f"PRAGMA max_page_count={256 * 1024 * 1024 // page_size}")
            self.db.executescript(SCHEMA)
            if self.metric("schema") == 1:
                with self.transaction():
                    self.db.execute("ALTER TABLE checkpoints ADD COLUMN page_evidence TEXT")
                    self.db.execute("UPDATE meta SET value=2 WHERE key='schema'")
            if self.metric("schema") != 2:
                raise ReaderError("Unsupported MCPCord database schema.")
            self.purge_expired()
        except sqlite3.Error:
            raise ReaderError("MCPCord storage could not be opened; no database content was logged.") from None

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        try:
            self.db.execute("BEGIN IMMEDIATE")
            yield
            self.db.execute("COMMIT")
        except BaseException as exc:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            if isinstance(exc, sqlite3.Error):
                raise ReaderError("Storage operation failed or reached its size limit; the page and checkpoint were rolled back.") from None
            raise

    def metric(self, key):
        return self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()[0]

    def _change(self, key, delta):
        self.db.execute("UPDATE meta SET value=value+? WHERE key=?", (delta, key))

    def _channel(self, channel):
        old = self.db.execute("SELECT guild_id FROM channels WHERE id=?", (channel["id"],)).fetchone()
        if old and old[0] != channel["guild_id"]:
            raise ReaderError("A stored channel cannot change guild identity.")
        self.db.execute("INSERT INTO channels VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                        (channel["id"], channel["guild_id"], canonical(channel)))

    def _upsert(self, message):
        cid, mid = snowflake(message["channel_id"]), snowflake(message["id"])
        old = self.db.execute("SELECT stamp,author_id,edited,observed,payload,size FROM messages WHERE channel_id=? AND id=?", (cid, mid)).fetchone()
        if old:
            if (old["stamp"], old["author_id"]) != (message["timestamp"], message["author"]["id"]):
                raise ReaderError("Conflicting immutable stored message identity.")
            previous = (old["edited"] or old["stamp"], old["observed"])
            incoming = (message["edited_at"] or message["timestamp"], message["observed_at"])
            if incoming < previous:
                return
            if incoming == previous:
                older = json.loads(old["payload"])
                if {k: v for k, v in older.items() if k != "source_export_sha256"} != {k: v for k, v in message.items() if k != "source_export_sha256"}:
                    raise ReaderError("Conflicting stored message versions share an observation timestamp.")
                return
        payload = canonical(message)
        size = len(payload.encode())
        added = 0 if old else 1
        delta = size - (old["size"] if old else 0)
        if self.metric("count") + added > self.max_messages or self.metric("bytes") + delta > self.max_bytes:
            raise ReaderError("Local message index quota reached; narrow scope or explicitly purge retained data.")
        ref = message.get("reference") or {}
        self.db.execute("""INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(channel_id,id) DO UPDATE SET edited=excluded.edited,observed=excluded.observed,
            author_kind=excluded.author_kind,reply_user=excluded.reply_user,reply_channel=excluded.reply_channel,
            reply_message=excluded.reply_message,is_reply=excluded.is_reply,payload=excluded.payload,size=excluded.size""",
            (cid, mid, mid.zfill(20), message["timestamp"], message["author"]["id"], message.get("author_kind", "user"),
             message["edited_at"], message["observed_at"], message.get("reply_to_user_id"), ref.get("channelId") or cid,
             ref.get("messageId"), int(message.get("is_reply", False)), payload, size))
        self.db.execute("DELETE FROM mentions WHERE channel_id=? AND message_id=?", (cid, mid))
        self.db.executemany("INSERT INTO mentions VALUES (?,?,?)", [(u, cid, mid) for u in message.get("mention_ids", [])])
        self._change("count", added)
        self._change("bytes", delta)
        self._change("revision", 1)

    def ingest(self, channel, rows):
        with self.transaction():
            self._channel(channel)
            for row in rows:
                self._upsert(row)

    def purge_expired(self):
        cutoff = timestamp((self.now() - timedelta(days=self.retention_days)).isoformat())
        with self.transaction():
            count, size = self.db.execute("SELECT count(*),coalesce(sum(size),0) FROM messages WHERE observed<?", (cutoff,)).fetchone()
            self.db.execute("DELETE FROM messages WHERE observed<?", (cutoff,))
            self.db.execute("DELETE FROM jobs WHERE updated<?", (cutoff,))
            self.db.execute("DELETE FROM channels WHERE id NOT IN (SELECT channel_id FROM messages) AND id NOT IN (SELECT channel_id FROM checkpoints)")
            self._change("count", -count)
            self._change("bytes", -size)
            if count:
                self._change("revision", 1)
        return count

    def create_job(self, channels, since, until, all_history):
        if self.db.execute("SELECT count(*) FROM jobs").fetchone()[0] >= 32:
            raise ReaderError("At most 32 retained jobs are supported; expire or purge old jobs first.")
        jid = secrets.token_hex(16)
        request = {"channel_ids": sorted(channels, key=int), "since": since, "until": until, "all_history": all_history,
                   "coverage": "Only this explicit channel snapshot. Undiscovered threads, closed DMs, deleted messages and inaccessible history are excluded. An empty page is not proof of no historical messages."}
        with self.transaction():
            self.db.execute("INSERT INTO jobs VALUES (?,?,?,?,NULL)", (jid, "paused", canonical(request), timestamp(self.now().isoformat())))
            for cid, channel in channels.items():
                self._channel(channel)
                self.db.execute("INSERT INTO checkpoints(job_id,channel_id,before_id,state) VALUES (?,?,?,?)",
                                (jid, cid, boundary_id(until), "pending"))
        return self.job(jid)

    def job(self, jid):
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        if row is None:
            raise ReaderError("Unknown or expired history job.")
        checks = [dict(c) for c in self.db.execute("SELECT channel_id,before_id,state,pages,observed_rows,error,page_evidence FROM checkpoints WHERE job_id=? ORDER BY channel_id", (jid,))]
        for check in checks:
            check["page_evidence"] = json.loads(check["page_evidence"]) if check["page_evidence"] else None
        pending = sum(c["state"] in ("pending", "running") for c in checks)
        return {"job_id": jid, "state": row["state"], "request": json.loads(row["request"]), "channels": checks,
                "needs_continuation": bool(pending), "pending_channels": pending, "total_page_limit": None,
                "updated_at": row["updated"], "retry_at": row["retry_at"], "persistent": self.persistent,
                "restart_resumable": self.persistent, "retention_days": self.retention_days,
                "stored_message_count": self.metric("count"), "stored_payload_bytes": self.metric("bytes"),
                "exhaustive": False, "no_background_work": True}

    def set_job_state(self, jid, state, retry_at=None):
        self.job(jid)
        with self.transaction():
            self.db.execute("UPDATE jobs SET state=?,updated=?,retry_at=? WHERE id=?", (state, timestamp(self.now().isoformat()), retry_at, jid))

    def commit_page(self, jid, cid, expected_before, following, rows, exhausted, evidence=None):
        with self.transaction():
            checkpoint = self.db.execute("SELECT before_id,state FROM checkpoints WHERE job_id=? AND channel_id=?", (jid, cid)).fetchone()
            if checkpoint is None or checkpoint["before_id"] != expected_before or checkpoint["state"] not in ("pending", "running"):
                raise ReaderError("History checkpoint changed; restart this slice from current status.")
            for row in rows:
                self._upsert(row)
            self.db.execute("UPDATE checkpoints SET before_id=?,state=?,pages=pages+1,observed_rows=observed_rows+?,error=NULL,page_evidence=? WHERE job_id=? AND channel_id=?",
                            (following, "traversed" if exhausted else "running", len(rows), canonical(evidence) if evidence else None, jid, cid))
            self.db.execute("UPDATE jobs SET updated=? WHERE id=?", (timestamp(self.now().isoformat()), jid))

    def fail_channel(self, jid, cid, error):
        with self.transaction():
            self.db.execute("UPDATE checkpoints SET state='unavailable',error=? WHERE job_id=? AND channel_id=?", (error, jid, cid))

    def _where(self, channel_ids, since, until, user_id=None, relationship="author"):
        if not isinstance(channel_ids, list) or not 1 <= len(channel_ids) <= 1000:
            raise ReaderError("Select 1 to 1000 indexed channel IDs.")
        ids = sorted({snowflake(cid) for cid in channel_ids})
        since, until = timestamp(since), timestamp(until)
        if since >= until or relationship not in ("author", "mention", "reply"):
            raise ReaderError("Use since < until and an author/mention/reply relationship.")
        where = f"m.channel_id IN ({','.join('?' for _ in ids)}) AND m.stamp>=? AND m.stamp<?"
        args = [*ids, since, until]
        if user_id is not None:
            snowflake(user_id)
            if relationship == "author":
                where += " AND m.author_id=? AND m.author_kind!='webhook'"
            elif relationship == "mention":
                where += " AND EXISTS(SELECT 1 FROM mentions n WHERE n.user_id=? AND n.channel_id=m.channel_id AND n.message_id=m.id)"
            else:
                where += " AND m.is_reply=1 AND coalesce(m.reply_user,(SELECT p.author_id FROM messages p WHERE p.channel_id=m.reply_channel AND p.id=m.reply_message AND p.author_kind!='webhook'))=?"
            args.append(user_id)
        return where, args

    def query(self, channel_ids, since, until, user_id=None, relationship="author", limit=25, cursor=None):
        self.purge_expired()
        integer(limit, 1, 50)
        where, args = self._where(channel_ids, since, until, user_id, relationship)
        signature = fingerprint([where, args, self.metric("revision")])
        self.cursors = {k: v for k, v in self.cursors.items() if self.now() - v["created"] <= timedelta(minutes=10)}
        if cursor is not None:
            page = self.cursors.get(cursor)
            if page is None or page["signature"] != signature:
                raise ReaderError("Indexed-query cursor expired or the index changed; start a fresh query.")
            where += " AND (m.stamp,m.channel_id,m.sort_id)>(?,?,?)"
            args += page["last"]
        fetched = self.db.execute("SELECT m.payload,m.stamp,m.channel_id,m.sort_id FROM messages m WHERE " + where + " ORDER BY m.stamp,m.channel_id,m.sort_id LIMIT ?", (*args, limit + 1)).fetchall()  # noqa: S608 - fragments are fixed; every value is bound
        more = len(fetched) > limit
        selected = fetched[:limit]
        next_cursor = None
        if more:
            next_cursor = secrets.token_hex(24)
            if len(self.cursors) >= 32:
                del self.cursors[next(iter(self.cursors))]
            last = selected[-1]
            self.cursors[next_cursor] = {"created": self.now(), "signature": signature, "last": [last["stamp"], last["channel_id"], last["sort_id"]]}
        rows = []
        for item in selected:
            message = json.loads(item["payload"])
            message["content_truncated"] = len(message["content"]) > 1000
            message["content"] = message["content"][:1000]
            rows.append(message)
        return {"messages": rows, "next_cursor": next_cursor, "more_messages": more,
                "freshness": "retained_observations_only", "exhaustive": False,
                "coverage": "Local collected data only. Inspect the job manifest for unfinished or inaccessible channels. Observations are not current presence or a deletion audit."}

    def analyze(self, channel_ids, since, until, user_id=None, relationship="author", timezone="UTC", bucket="day"):
        self.purge_expired()
        activity([], timezone, user_id, relationship, bucket)
        where, args = self._where(channel_ids, since, until, user_id, relationship)
        rows = (json.loads(row[0]) for row in self.db.execute("SELECT m.payload FROM messages m WHERE " + where + " ORDER BY m.stamp,m.channel_id,m.sort_id", args))  # noqa: S608 - fixed fragments; bound values
        # SQL already resolves reply targets against indexed originals.
        result = activity(rows, timezone, None, relationship, bucket)
        result.update({"user_id": user_id, "since": timestamp(since), "until": timestamp(until),
                       "freshness": "retained_observations_only", "exhaustive": False,
                       "coverage": "Activity in collected observations only; use job coverage before drawing conclusions. Deleted, inaccessible, uncollected and expired messages are absent."})
        return result
