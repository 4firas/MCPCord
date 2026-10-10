"""Explicit history jobs; each continuation does bounded work and then stops."""
from datetime import timedelta

from .live import LiveReader, api_to_export, as_time, live_envelope
from .live_transport import LiveError
from .reader import ReaderError, bounded_list, integer, normalize_message, snowflake, timestamp
from .store import HistoryStore


class HistoryMixin(LiveReader):
    guilds: dict[str, dict]

    def _history(self):
        if getattr(self, "history_store", None) is None:
            self.history_store = HistoryStore(now=self.now)
        return self.history_store

    def start_history_import(self, channel_ids=None, guild_id=None, since=None, until=None, all_history=False):
        if type(all_history) is not bool or (guild_id is None) == (channel_ids is None):
            raise ReaderError("Choose exactly one discovered guild or explicit channel list, and a boolean all_history opt-in.")
        if guild_id is not None:
            snowflake(guild_id)
            if guild_id not in self.guilds:
                raise ReaderError("Discover this guild and its readable channels first.")
            ids = [cid for cid, c in self.channels.items() if c["guild_id"] == guild_id]
        else:
            ids = sorted({snowflake(cid) for cid in bounded_list(channel_ids, 1000)}, key=int)
        if not ids or len(ids) > 1000 or any(cid not in self.channels for cid in ids):
            raise ReaderError("Select 1 to 1000 discovered message channels. Forum/media containers are not message channels.")
        if all_history:
            if since is not None:
                raise ReaderError("For all_history omit since; the fixed lower boundary is Discord's epoch.")
            since = "2015-01-01T00:00:00Z"
        elif since is None:
            raise ReaderError("Provide since or explicitly request all_history. No history import starts implicitly.")
        since = timestamp(since)
        until = timestamp(until or self.now().isoformat())
        if as_time(since).year < 2015 or since >= until or as_time(until) > self.now():
            raise ReaderError("Use a Discord-era window with since < until <= now.")
        result = self._history().create_job({cid: self.channels[cid] for cid in ids}, since, until, all_history)
        result["network_requested"] = False
        result["next_step"] = "Inspect this explicit channel snapshot, then call continue_history_import for bounded slices. Discover active and archived threads separately before starting a server job."
        return live_envelope(result)

    def history_import_status(self, job_id):
        self._history().purge_expired()
        return live_envelope(self._history().job(job_id))

    def cancel_history_import(self, job_id):
        store = self._history()
        job = store.job(job_id)
        store.set_job_state(job_id, "cancelled", job.get("retry_at"))
        return live_envelope(store.job(job_id))

    def continue_history_import(self, job_id, max_pages=3, resume_cancelled=False):
        integer(max_pages, 1, 10)
        if type(resume_cancelled) is not bool:
            raise ReaderError("resume_cancelled must be boolean.")
        store = self._history()
        store.purge_expired()
        job = store.job(job_id)
        if job["state"] == "cancelled" and not resume_cancelled:
            raise ReaderError("Job is cancelled. Set resume_cancelled only after an explicit request to resume it.")
        if job["state"] in ("traversed", "partial"):
            return live_envelope(job)
        if job.get("retry_at") and as_time(job["retry_at"]) > self.now():
            return live_envelope(dict(job, continuation_blocked="Stored retry cooldown is still active."))
        pending_channels = [c for c in job["channels"] if c["state"] in ("pending", "running")]
        if any(c["channel_id"] not in self.channels for c in pending_channels):
            return live_envelope(dict(job, continuation_blocked="Rediscover the pending channels/threads in this session before resuming; cached IDs do not grant access."))
        self.client.begin_refresh(self.scope["max_requests_per_refresh"])
        deadline = self.monotonic() + 20
        store.set_job_state(job_id, "running")
        pages = 0
        error = None
        try:
            while pages < max_pages and self.monotonic() < deadline:
                current = store.job(job_id)
                pending = next((c for c in current["channels"] if c["state"] in ("pending", "running")), None)
                if pending is None:
                    break
                cid, before = pending["channel_id"], pending["before_id"]
                try:
                    raw_page = bounded_list(self.client.messages(cid, before, deadline), 100)
                except LiveError as exc:
                    if exc.code in ("access_denied", "not_found"):
                        store.fail_channel(job_id, cid, exc.code)
                        pages += 1
                        continue
                    raise
                observed = timestamp(self.now().isoformat())
                normalized, seen = [], set()
                following = int(before)
                reached_start = False
                for raw in raw_page:
                    row = normalize_message(api_to_export(raw, self.channels[cid]), self.channels[cid], observed, "discord-history")
                    mid = int(row["id"])
                    if mid >= int(before) or mid in seen:
                        raise LiveError("invalid_response", "History page stalled or repeated a message identity; checkpoint was not advanced.")
                    seen.add(mid)
                    following = min(following, mid)
                    if row["timestamp"] < job["request"]["since"]:
                        reached_start = True
                    elif row["timestamp"] < job["request"]["until"]:
                        normalized.append(row)
                # Continue after short pages; an empty page or requested lower bound ends traversal.
                store.commit_page(job_id, cid, before, str(following), normalized, not raw_page or reached_start)
                pages += 1
        except (ReaderError, KeyboardInterrupt) as exc:
            if isinstance(exc, KeyboardInterrupt):
                store.set_job_state(job_id, "cancelled")
                raise
            code = exc.code if isinstance(exc, LiveError) else "validation_or_storage_error"
            delay = getattr(exc, "retry_after", None)
            retry_at = None
            if delay:
                try:
                    retry_at = timestamp((self.now() + timedelta(seconds=delay)).isoformat())
                except OverflowError:
                    retry_at = "9999-12-31T23:59:59.000000Z"
            store.set_job_state(job_id, "paused", retry_at)
            error = {"code": code, "message": str(exc), "retry_at": retry_at}
        current = store.job(job_id)
        if error is None:
            states = {c["state"] for c in current["channels"]}
            state = "paused" if states & {"pending", "running"} else ("partial" if "unavailable" in states else "traversed")
            store.set_job_state(job_id, state)
        result = store.job(job_id)
        result.update({"pages_this_slice": pages, "error": error,
                       "coverage_note": "Traversed means the requested pagination boundary was reached, not that all historical messages exist or are accessible. Short pages are continued; empty pages can still reflect permissions. Newer messages after the fixed until boundary require a new job."})
        return live_envelope(result, error=error is not None)

    def query_history(self, channel_ids, since, until, user_id=None, relationship="author", limit=25, cursor=None):
        return live_envelope(self._history().query(channel_ids, since, until, user_id, relationship, limit, cursor))

    def analyze_history(self, channel_ids, since, until, user_id=None, relationship="author", timezone="UTC", bucket="day"):
        return live_envelope(self._history().analyze(channel_ids, since, until, user_id, relationship, timezone, bucket))
