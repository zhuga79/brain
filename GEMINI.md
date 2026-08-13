# Antigravity Overrides For Brain

These rules are specific to Google Antigravity/Gemini-style agents.

- Start by checking `brain-status` and the top open task in
  `./tasks/active.md`.
- Use Brain CLI commands for task lifecycle; do not rewrite task markdown
  directly for normal take/complete operations.
- Set `BRAIN_PATH=.` when working in this repository.
- Use Brain MCP when available, but fall back to the local Brain CLI if MCP is
  unavailable or the model backend is rate-limited.
- On HTTP 429 / `RESOURCE_EXHAUSTED`, do not repeatedly retry the same
  trajectory. Record the `Trajectory ID` and `TraceID`, wait for quota recovery
  or switch to another CLI/model. This is a provider quota/backend condition,
  not a Brain code failure.
- Keep prompts compact: reference task ids and files instead of pasting full
  wiki/task contents unless needed.

Current fallback priority for implementation tasks:

1. Gemini 3 Flash when quota is available.
2. Codex 5.3 medium.
3. Claude Sonnet 4.6.
