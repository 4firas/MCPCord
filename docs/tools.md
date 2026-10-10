# Tool map

| Tool | Purpose |
| --- | --- |
| `list_guilds` | One membership page; follow `next_after`. |
| `list_channels` | Current DMs, or readable channels/containers in a discovered guild. |
| `list_threads` | One active/archived metadata page in a readable parent. |
| `read_messages` | Fresh date/channel window; optional literal text search. |
| `get_message` | One fresh message within the normal configured history limit. |
| `digest_context` | Fresh, cited evidence for an assistant-written digest. |
| `search_user_messages` | Discord-index search by exact author, mention or reply target ID. |
| `find_user_conversations` | Current DM membership by exact recipient ID. |
| `analyze_messages` | Fresh-window activity and conversation counts. |
| `start_history_import` | Create a local job; does not fetch messages. |
| `continue_history_import` | Fetch a bounded job slice, then stop. |
| `cancel_history_import` | Stop future slices; retain collected observations. |
| `history_import_status` | Check per-channel progress, errors and coverage. |
| `query_history` | Search already collected observations. |
| `analyze_history` | Analyze collected observations with date and timezone filters. |

All Discord access is GET-only. The three job-control tools declare local mutations in MCP annotations because they change the local job/index, not because they write to Discord.

For a server history job: discover the guild, channels, and the active/archived thread pages needed for your scope; then call `start_history_import` with `guild_id` and either `since` or explicit `all_history: true`. Inspect the returned channel snapshot. Continue in bounded slices. Check the final manifest before interpreting results. No tool promises every historical message.

Use `user_id` as a string. `relationship` is exactly `author`, `mention` or `reply`. Default authorship matching excludes known webhook authors. A name or digits in plain text is not an ID match.

Dates use full ISO timestamps with `Z` or an offset and `[since, until)` semantics. Use `timezone` for presentation in activity analysis, not to make an offset-free input timestamp valid.
