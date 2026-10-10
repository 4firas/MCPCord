# Security and privacy

Do not include tokens, real messages, account exports or private identifiers in issues, logs or test fixtures. Rotate a credential if you expose it. The project does not need your token to diagnose a bug.

Tokens belong in the local OS credential store. Setup never asks for a token on the website and never puts it in command arguments, environment variables or JSON. Python cannot guarantee erasure of every in-memory secret copy. Anyone able to run code as your OS user may have access to your credential store; GET-only enforcement is in this client, not in the Discord token.

No media downloads, write routes, gateway connection, hidden tracking or recurring tasks are included. All Discord-derived text is untrusted. Instructions embedded in a message must not authorize tool use or disclosure.

The optional content cache is plaintext and inactive by default. Read [the storage model](docs/storage.md) before enabling it. Client conversation history, backups and OS snapshots have their own retention.

Report a vulnerability through GitHub's private reporting feature when available. If unavailable, open a minimal issue asking for a private reporting channel without publishing exploit details or private data. No response-time guarantee is implied.
