# Python Web Skill Adapter

This project discovers agent skills from a remote domain and exposes them as ADK tools.

## What it does

1. Reads a domain from configuration.
2. Fetches `/.well-known/agent-skills/index.json`.
3. Parses discovered skill definitions.
4. Converts each skill into an ADK tool.
5. Boots an ADK agent that can call those remote skills.

## Requirements

- Python 3.11+
- `uv` for environment and dependency management
- A model configured for ADK, for example `GOOGLE_API_KEY`

## Install

```bash
uv python install 3.11
uv venv --python 3.11
uv sync
```

If you prefer not to use `uv`, editable install with `pip` still works:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

## Configure

The ADK agent is created at startup, so the target domain must be known before launching `adk web` or `adk run`.

```bash
export WEB_SKILL_DOMAIN=www.charles-hsiao.com
export GOOGLE_API_KEY=your-api-key
```

Optional settings:

```bash
export WEB_SKILL_MODEL=gemini-2.5-flash
export WEB_SKILL_TIMEOUT=20.0
```

## Run with ADK

From the repository root:

```bash
uv run adk web
```

Or run in the terminal UI:

```bash
uv run adk run web_skill_adapter
```

The agent package is `web_skill_adapter`, so ADK can discover it automatically.

## Run with the local CLI

```bash
uv run python -m web_skill_adapter.cli --domain www.charles-hsiao.com
```

If `--domain` is omitted, the CLI prompts for it.

## Notes

- The discovery parser is intentionally tolerant of slightly different skill index shapes.
- Request parameters are mapped by location when provided (`path`, `query`, `header`, `body`).
- If a skill index cannot be loaded at startup, the agent still boots and explains the configuration problem.
