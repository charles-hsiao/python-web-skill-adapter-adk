# Tutorial: Python Web Skill Adapter

This guide walks you through setting up the project, understanding how web skills work, and running your first agent session.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Project Overview](#project-overview)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Running the Agent](#running-the-agent)
6. [How Web Skill Discovery Works](#how-web-skill-discovery-works)
7. [Creating Your Own Skill Index](#creating-your-own-skill-index)
8. [Advanced: SKILL.md Format](#advanced-skillmd-format)
9. [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Requirement | Minimum version |
|-------------|-----------------|
| Python      | 3.11            |
| uv          | any recent      |
| Google API Key | Gemini access |

Install `uv` if you don't already have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## Project Overview

```
User provides a domain (e.g. www.charles-hsiao.com)
  │
  ▼
Fetch https://{domain}/.well-known/agent-skills/index.json
  │
  ▼
Parse skill definitions (plain HTTP specs or SKILL.md pointers)
  │
  ▼
Dynamically create ADK tools from each skill
  │
  ▼
Boot ADK Agent with discovered tools
  │
  ▼
Interactive session (web UI or terminal)
```

The adapter never hardcodes skills. Every capability is discovered at startup from the remote domain.

---

## Installation

```bash
# Clone or enter the project directory
cd python-web-skill-adapter

# Create a virtual environment and install dependencies
uv venv --python 3.11
uv sync
```

---

## Configuration

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:

```env
GOOGLE_API_KEY=your-api-key-here
WEB_SKILL_DOMAIN=www.charles-hsiao.com
WEB_SKILL_MODEL=gemini-2.5-flash   # optional, defaults to gemini-2.5-flash
WEB_SKILL_TIMEOUT=20.0             # optional, HTTP timeout in seconds
```

> **Important:** `.env` is listed in `.gitignore`. Never commit your API key.

### Environment variable reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_API_KEY` | Yes | — | API key for the Gemini model |
| `WEB_SKILL_DOMAIN` | Yes | — | Domain to discover skills from |
| `WEB_SKILL_MODEL` | No | `gemini-2.5-flash` | ADK model identifier |
| `WEB_SKILL_TIMEOUT` | No | `20.0` | HTTP request timeout (seconds) |

---

## Running the Agent

### Option A — ADK web UI (recommended)

```bash
uv run adk web
```

Open your browser at `http://localhost:8000`. Select **web_skill_adapter** from the agent list and start chatting.

### Option B — Terminal UI

```bash
uv run adk run web_skill_adapter
```

### Option C — Local CLI helper

```bash
uv run python -m web_skill_adapter.cli --domain www.charles-hsiao.com
```

Omit `--domain` to be prompted interactively.

---

## How Web Skill Discovery Works

At startup the adapter:

1. Calls `GET https://{domain}/.well-known/agent-skills/index.json`
2. Parses the returned JSON (see formats below)
3. For each skill entry it creates a `DiscoveredSkillTool` that wraps the real HTTP endpoint
4. Passes all tools to the `Agent` constructor

The `Agent` then uses the Gemini model to decide which tool to call based on the conversation, just like any other ADK tool.

### Skill index format — plain HTTP

The simplest `index.json` is an array of skill objects:

```json
[
  {
    "name": "search_posts",
    "description": "Search blog posts by keyword.",
    "method": "GET",
    "url": "https://www.example.com/api/posts",
    "parameters": [
      {
        "name": "q",
        "in": "query",
        "description": "Search term",
        "schema": { "type": "string" }
      }
    ]
  }
]
```

Alternatively, the array can be nested under a `skills` key:

```json
{
  "skills": [ ... ]
}
```

### Parameter locations

| `in` value | Behaviour |
|---|---|
| `query` | Appended to the URL as a query parameter |
| `path` | Substituted into `{param}` or `:param` placeholders |
| `header` | Added as an HTTP request header |
| `body` | Included in the JSON request body |

---

## Creating Your Own Skill Index

Host a static JSON file at:

```
https://your-domain.com/.well-known/agent-skills/index.json
```

Minimal example that exposes one GET endpoint:

```json
[
  {
    "name": "get_weather",
    "description": "Returns current weather for a city.",
    "method": "GET",
    "url": "https://your-domain.com/api/weather",
    "parameters": [
      {
        "name": "city",
        "in": "query",
        "description": "City name",
        "schema": { "type": "string" }
      }
    ]
  }
]
```

Set the correct CORS and content-type headers on your server:

```
Content-Type: application/json
Access-Control-Allow-Origin: *  # only needed for browser clients
```

Point the adapter at your domain:

```bash
WEB_SKILL_DOMAIN=your-domain.com uv run adk web
```

---

## Advanced: SKILL.md Format

For richer skill descriptions you can point entries to a Markdown file (`SKILL.md`). This lets you include prose documentation alongside machine-readable HTTP blocks.

Add a `type: skill-md` entry in `index.json`:

```json
{
  "type": "skill-md",
  "name": "blog-skills",
  "description": "Blog reading and search capabilities.",
  "url": "/skills/blog.md"
}
```

The `SKILL.md` at that URL should contain fenced code blocks that describe HTTP calls:

````markdown
# Blog Skills

## Search Posts

```
GET /api/posts?q={query}
```

## Get Post by Slug

```
GET /api/posts/{slug}
```
````

The adapter will:

- Fetch the Markdown file
- Extract all HTTP code blocks
- Map each block to a `SkillSpec` and create a corresponding tool
- Embed non-code prose as static context in the agent's instructions

### Markdown content negotiation

If a `skill-md` entry's `name` contains `markdown-negotiation`, the adapter automatically adds `Accept: text/markdown` to all same-origin GET requests, enabling rich formatted responses.

---

## Troubleshooting

### Agent says "WEB_SKILL_DOMAIN is not configured"

The environment variable is missing. Make sure `.env` is in the project root and contains `WEB_SKILL_DOMAIN=...`, then restart the ADK process.

### Skill index returned no callable tools

The `index.json` was fetched successfully but the parser found no valid HTTP endpoint definitions. Check that:

- The JSON is either a top-level array or an object with a `skills` array.
- Each skill entry includes `method` and `url` fields.
- `SKILL.md` code blocks start with a valid HTTP method (`GET`, `POST`, …).

### HTTP timeout or connection errors

Increase `WEB_SKILL_TIMEOUT` in `.env`, or check that the domain is publicly accessible from your machine.

### `adk web` does not list `web_skill_adapter`

ADK discovers agents by looking for a Python package that exports `root_agent`. Make sure you are running `adk web` from the repository root and that the package is installed (`uv sync` was run).
