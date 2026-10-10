# Validation

Tests use fabricated IDs, messages and credentials. They do not connect to Discord. The Windows credential test creates a uniquely named synthetic test item, reads it back, and deletes it; it never reads MCPCord's real credential item.

Coverage includes exact author/mention/reply identity, missing content, timezone/DST boundaries, pagination drift, rate limits and indexing delays, authorization failures, scope checks, duplicate/edited messages, retention and quotas, cancellation, and crash recovery. A synthetic history test follows 12,007 messages across 122 pages back to 2016, pausing and resuming between slices. Additional regressions cover premature empty pages, oldest-first verification, short/unsorted pages, cursor stalls, inclusive lower boundaries, time budgets, legacy date-cap configurations and database migration. A subprocess test exits abruptly during a SQLite page transaction and checks that both the page and checkpoint recover together.

The CI matrix runs Python 3.11 and 3.14 on macOS, Windows and Linux. POSIX-only disk-permission and crash tests are skipped on Windows, where persistent history storage is explicitly unavailable. The Windows-native credential roundtrip runs only on Windows. All platforms run memory-history and mocked provider tests. This is not live Discord compatibility testing on every platform.

The package smoke test installs a built wheel into a new virtual environment and runs outside the checkout. It exercises the executable, credential-free setup and an offline STDIO MCP handshake. Local Codex's registered STDIO connection and bounded live reads have also been checked on macOS. Other MCP clients require their own integration checks.

## Synthetic scale measurement

One macOS/Python 3.14 run of `python scripts/benchmark.py 100000` measured:

| Measurement | Result |
| --- | ---: |
| Messages / channels / authors | 100,000 / 10 / 1,000 |
| Ingestion | 21.88 s |
| Exact-author first page | 0.00043 s |
| Mention first page | 0.0465 s |
| Reply first page | 0.0208 s |
| Whole-index activity aggregation | 0.742 s |
| Peak process RSS | 270 MiB |
| Normalized payload / SQLite pages | 73.7 / 126.3 MiB |

No network requests or persistent content cache were used. These are local index measurements, not promises about Discord latency, full-account import time, or other hardware. RAM includes Python and SQLite overhead and is not bounded by the payload quota alone. Serial network reads and Discord cooldowns dominate live collection.

The history store stops at 250,000 messages, 128 MiB of normalized payload, or 256 MiB of SQLite pages, whichever is reached first. Short tests and one scale measurement do not prove every possible account or malformed response behaves correctly.
