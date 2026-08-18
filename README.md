# ATLAS

Two independent bots live in this repo:

| Folder | Purpose |
|---|---|
| [`video-labeling-bot/`](video-labeling-bot/README.md) | Playwright + OpenRouter vision models — full browser automation |
| [`atlas-hybrid-bot/`](atlas-hybrid-bot/README.md) | Non-LLM hybrid pipeline — MediaPipe hands + regex draft surgery (no API keys) |

Each has its own `venv`, `.env`, tests, and entry point. They are not mixed.
