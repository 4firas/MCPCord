/* Public release facts only. Never put credentials here. */
window.MCPCORD_RELEASE = Object.freeze({
  "repository": "https://github.com/fourfiras/MCPCord",
  "docsPath": "#readme",
  "installCommand": "uv tool install git+https://github.com/fourfiras/MCPCord.git && mcpcord setup",
  "platformLabel": "macOS · Windows · Linux",
  "prerequisites": "Requires uv, Git and the Codex CLI; Python 3.11+ can be supplied by uv. Linux also needs secret-tool and an unlocked desktop keyring. On PowerShell 5, run the two commands separately.",
  "connectionDetails": "Acknowledge the personal-account risk, then enter your token in a hidden local prompt. It is stored in macOS Keychain, Windows Credential Manager or Linux Secret Service. Setup keeps an existing MCPCord registration and collects no messages.",
  "clientDetails": "Local Codex over STDIO MCP is verified. Reconnect MCP or open a new local session after setup. Other local STDIO clients can use mcpcord setup --no-register and configure the printed command; they have not been individually verified. No native cloud/dot attachment or scheduling is included."
});
