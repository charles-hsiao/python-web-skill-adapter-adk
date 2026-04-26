# Web Skill Specification

This document defines the **Web Skill Discovery Protocol** used by the Python Web Skill Adapter.

---

## Overview

A **web skill** is an HTTP endpoint that an AI agent can call on behalf of a user. Skills are self-described: a website publishes a machine-readable index at a well-known URL, and any compatible agent can discover and use those skills automatically — no hardcoding required.

---

## Well-Known URL

Skills are discovered via:

```
GET https://{domain}/.well-known/agent-skills/index.json
```

The server must respond with `Content-Type: application/json`.

---

## Index Format

The response body is either:

- a **JSON array** of skill entries, or
- a **JSON object** with a `skills` key containing such an array.

```json
{
  "skills": [ <SkillEntry>, <SkillEntry>, ... ]
}
```

```json
[ <SkillEntry>, <SkillEntry>, ... ]
```

---

## Skill Entry Types

### Type 1 — Plain HTTP Skill

Describes a single callable HTTP endpoint directly.

```json
{
  "name": "search_posts",
  "description": "Search blog posts by keyword.",
  "method": "GET",
  "url": "https://www.example.com/api/posts",
  "parameters": [
    {
      "name": "q",
      "in": "query",
      "description": "The search term.",
      "schema": { "type": "string" }
    },
    {
      "name": "limit",
      "in": "query",
      "description": "Maximum number of results to return.",
      "schema": { "type": "integer" }
    }
  ]
}
```

#### Required fields

| Field | Type | Description |
|---|---|---|
| `name` | string | Human-readable skill name |
| `description` | string | What the skill does (shown to the model) |
| `method` | string | HTTP method (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`) |
| `url` | string | Absolute URL of the endpoint |

#### Optional fields

| Field | Type | Description |
|---|---|---|
| `parameters` | array | List of `ParameterSpec` objects (see below) |

#### ParameterSpec

| Field | Type | Values | Description |
|---|---|---|---|
| `name` | string | — | Parameter name |
| `in` | string | `query`, `path`, `header`, `body` | Where to place the parameter |
| `description` | string | — | Passed to the model as part of the tool schema |
| `schema` | object | JSON Schema | Type information (`type`, `enum`, `default`, …) |
| `required` | boolean | `true` / `false` | Whether the parameter is mandatory |

##### Parameter location behaviour

| `in` | Runtime behaviour |
|---|---|
| `query` | Added to the URL query string (`?name=value`) |
| `path` | Substituted into `{name}` or `:name` in the URL template |
| `header` | Added as an HTTP request header |
| `body` | Merged into a JSON request body |

---

### Type 2 — SKILL.md Pointer

Points to a Markdown file that describes multiple skills in prose + HTTP code blocks.

```json
{
  "type": "skill-md",
  "name": "blog-skills",
  "description": "Blog reading and search capabilities.",
  "url": "/skills/blog.md"
}
```

#### Required fields

| Field | Type | Description |
|---|---|---|
| `type` | string | Must be `"skill-md"` |
| `name` | string | Logical group name |
| `url` | string | Path (relative to domain root) or absolute URL of the Markdown file |

#### Optional fields

| Field | Type | Description |
|---|---|---|
| `description` | string | Overall description of the skill group |

---

## SKILL.md Format

A SKILL.md file is a standard Markdown document. The adapter extracts skills from **fenced code blocks** whose first line starts with an HTTP method.

````markdown
# My Site Skills

## Get Article

Fetches a single article by its slug.

```
GET /api/articles/{slug}
```

## Create Comment

Posts a new comment on an article.

```
POST /api/articles/{slug}/comments
Content-Type: application/json

{
  "author": "string",
  "body": "string"
}
```
````

### Code block parsing rules

1. The first non-empty line must be `METHOD /path` (e.g. `GET /api/foo`).
2. Header lines (`Key: Value`) immediately after the method line are captured as extra request headers.
3. A blank line followed by a JSON object is treated as the request body schema.
4. Path parameters are inferred from `{name}` or `:name` patterns in the URL.
5. Body fields are inferred from the JSON object keys.

### Static context

All non-code prose in the SKILL.md (headings, paragraphs) is embedded in the agent's system instructions as static knowledge about the site.

---

## Markdown Content Negotiation

If a `skill-md` entry's `name` contains the substring `markdown-negotiation`, the adapter:

1. Sets `use_markdown_negotiation = true` for the catalog.
2. Automatically adds `Accept: text/markdown` to all same-origin `GET` requests.

This allows the server to return rich Markdown responses instead of plain JSON.

---

## Error Handling

The adapter is intentionally tolerant:

- If `index.json` cannot be fetched, the agent boots and explains the configuration issue.
- If a `SKILL.md` cannot be fetched, the adapter falls back to parsing the entry as a plain HTTP skill (if `url` and `method` are present).
- Duplicate tool names are automatically de-duplicated by appending a numeric suffix.
- Skill entries that cannot be parsed are silently skipped.

---

## Security Considerations

- Skills are fetched over HTTPS. HTTP-only domains are not recommended for production.
- The adapter forwards user-supplied arguments directly to remote endpoints. Validate and sanitise inputs on the server side.
- Do not include API keys or credentials in `index.json` or SKILL.md files — these are publicly readable.
- Use `header` parameters combined with agent instructions if authentication is needed.
