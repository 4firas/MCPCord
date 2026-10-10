# How MCPCord works

A local STDIO MCP server sits between the assistant and a fixed-origin GET-only transport. Credentials are read lazily from the user's OS store. Startup, tool listing, offline exports and setup dry-runs do not authenticate.

## Three reading paths

1. **Fresh windows:** refresh selected channels, then return a paginated in-memory snapshot. Ordinary reads default to seven days of lookback and at most 168 hours per query. Continuations expire after ten minutes.
2. **Discord-index search:** one server or discovered conversation, one exact user-ID relationship, one bounded API page. Handles indexing-pending responses and server-directed cooldowns. Short result pages do not end pagination; reported totals are advisory. Replies without a verifiable target are excluded, with a count.
3. **Explicit history collection:** capture selected channel IDs and a fixed `[since, until)` boundary, then collect at most ten pages per continuation. New records and their checkpoint commit in one transaction. Short history pages continue until an empty page or the requested lower boundary. Nothing runs between calls.

Message IDs stay decimal strings. Date filters use normalized UTC timestamps with explicit offsets. Activity summaries use the requested IANA timezone; repeated DST hours include their offsets. Source links use validated guild/channel/message IDs, with `@me` for direct conversations.

## State and failures

History states distinguish paused, cancelled, partial and traversed. “Traversed” describes pagination, not complete historical coverage. Permission-denied channels become unavailable, authentication failure pauses work, and rate-limit cooldowns can be checkpointed. A killed process rolls back an uncommitted page. Cancellation between slices retains earlier observations; resuming a cancelled job requires an explicit option.

SQLite indexes cover channel/time, author/time, mentions and message identity. Local query cursors use a keyset and index revision, so a changed index invalidates old pages instead of silently mixing snapshots. Analysis streams indexed rows. Resource quotas bound stored payload, database pages, group counts, response sizes and request sizes.

## Network boundary

All requests target `https://discord.com/api/v10`. Allowed routes cover current identity, current DMs, guild membership/permissions, channel metadata, channel message history, exact-ID message search and per-parent thread search. There is no generic HTTP tool. Redirects are rejected, credentials are not passed to another host, and raw transport errors are not returned.

Requests are serial, normally at least one second apart. Each refresh has a twenty-second budget, each socket operation at most five seconds, and each GET at most three attempts. Retries count against the request budget. Fractional rate-limit delays and reset headers are honored conservatively. Invalid authentication stops further authentication attempts in that process. Permission failures latch per route/channel. No alternate-route bypass is attempted.

The server is synchronous: cancellation stops future slices; it cannot interrupt an in-flight socket via a queued MCP call. Stop the process for immediate interruption. Socket/OS scheduling means timing limits are not hard real-time guarantees.

## Scope gaps

The current DM list does not guarantee all closed conversations. Forum/media containers hold threads, not messages. Active/archived thread pages must be requested separately; moving rows can produce duplicates or omissions. Private-thread visibility remains Discord's decision. An inaccessible parent can prevent local discovery even when a child might be otherwise accessible. No ID guessing, recipient probing, join or unarchive is used.

A local Codex registration does not attach tools to a remote/cloud chat. The optional local client opens the existing registered command on demand; the Mac/PC, credentials and network must be available. No background relay is installed.
