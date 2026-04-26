# Python Web Skill Adapter

## Project Goal

Build a demo application based on ADK (Agent Development Kit) that:
1. Accepts a Web domain from the user
2. Discovers available web skills by fetching `{domain}/.well-known/agent-skills/index.json`
3. Dynamically loads and registers the discovered skills as ADK tools
4. Provides an interactive demo showing the agent using those web skills

## Web Skill Discovery Protocol

Skills are discovered via a well-known URL:
```
https://{domain}/.well-known/agent-skills/index.json
```

Example: `https://www.charles-hsiao.com/.well-known/agent-skills/index.json`

The index.json describes available skills (endpoints, parameters, descriptions) that the agent can call.

## Tech Stack

- **Runtime**: Python 3.11+
- **Agent Framework**: Google ADK (Agent Development Kit) — `google-adk` package
- **HTTP Client**: `httpx` for async HTTP requests to web skills
- **CLI/UI**: ADK's built-in web UI or terminal runner

## Architecture

```
User provides domain
  → fetch /.well-known/agent-skills/index.json
  → parse skill definitions
  → dynamically create ADK tools from skill specs
  → instantiate ADK Agent with discovered tools
  → run interactive session (ADK web UI or terminal)
```

## Development Guidelines

- Use `google-adk` patterns: `Agent`, `tool` decorator, `Runner`
- Keep skill discovery async-first
- Skill specs should map cleanly to ADK `FunctionTool` definitions
- Each web skill HTTP call should handle errors gracefully (timeout, 4xx, 5xx)
- Do not hardcode domains — always discover dynamically at runtime

## Running the App

```bash
# Install dependencies
pip install -e .

# Run with ADK web UI
adk web

# Or run in terminal
adk run agent
```
