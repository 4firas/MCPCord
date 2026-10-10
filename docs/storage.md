# Storage is a choice

Default operation writes no Discord content to disk. Search results and bounded snapshots live in memory. Explicit history jobs use an in-memory SQLite index. Closing the process loses those jobs.

For restart-resumable collection, the operator can supply `--history-store /absolute/private/directory/history.sqlite3 --enable-content-cache --retention-days 14` to `serve-live`. This is disabled unless both launch arguments are present. No MCP tool can enable it, change the path, change retention, or enlarge quotas.

The operator must first approve the location and retention. Suggested scope: one local plaintext database; message text, IDs, names, timestamps, mention/reply IDs, source links, limited embed text and attachment metadata; channel metadata; job requests and checkpoints. No token, media body, attachment download, presence or location record is stored.

Limits: 250,000 messages, 128 MiB normalized message payload, 256 MiB SQLite database, 32 jobs and bounded per-call pages. A rollback journal can temporarily add up to roughly another database's size. Quota failures roll back the page and checkpoint together. Narrow the collection or remove retained data; the tool does not silently raise limits.

Persistence currently supports macOS/Linux: the containing directory must already exist, belong to the user and have mode `0700`; the file must be a private regular file with mode `0600`. Symlink files are rejected. Windows operation supports memory-only jobs until equivalent private-directory enforcement is implemented and verified.

Retention is based on **observation time**, not message creation time. A 2018 message collected today can remain for the chosen retention period. Re-observing it renews that period. Expired messages, jobs and orphan channel metadata are purged on startup/use. There is no timer or background service: an unused database remains on disk until the next run or manual removal. `secure_delete` clears deleted SQLite records, but filesystem snapshots, backups and SSD behavior prevent any promise of forensic erasure.

The latest observed version is retained. Older edits cannot roll it back. Missing rows never prove deletion. Refresh overlapping windows or re-run a collection to observe changes; there is no gateway watcher. A restarted job requires fresh discovery of pending channels before more requests. Stored IDs do not grant live access.

To remove retained data, stop the MCP process and delete the database and any adjacent journal. Remove the MCP registration separately if desired. Revoke the Discord credential separately; deleting a database or registration does not revoke it.
