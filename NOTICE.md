# Sources and attribution

MCPCord is an original Python implementation. It does not include, install or invoke DiscordChatExporter or discord.py-self, and it is not affiliated with Discord or OpenAI.

- [DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter), by Tyrrrz and contributors, was consulted for its JSON export format and personal-account thread discovery behavior. No exporter code or binary is bundled. Its upstream license is MIT.
- [discord.py-self](https://github.com/dolfies/discord.py-self) was consulted to verify the personal-account conversation search route. No library code is bundled.
- [Discord API documentation](https://docs.discord.com/developers/resources/message), [channel documentation](https://docs.discord.com/developers/resources/channel), [permissions](https://docs.discord.com/developers/topics/permissions), and [rate limits](https://docs.discord.com/developers/topics/rate-limits) inform the protocol and coverage limits.
- [Codex MCP documentation](https://developers.openai.com/codex/mcp) describes local STDIO registration.
- On Windows, the optional runtime dependency `tzdata` supplies IANA timezone data and carries its own upstream licensing. The package installer retains that dependency's license metadata.

Consulting an endpoint or file format does not make undocumented personal-account APIs stable or officially supported. Upstream account-policy warnings still apply.
