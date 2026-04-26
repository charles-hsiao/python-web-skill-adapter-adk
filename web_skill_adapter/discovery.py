from __future__ import annotations

import asyncio
import copy
import json
import re
from typing import Any
from urllib.parse import urljoin
from urllib.parse import urlparse

import httpx

from .models import JsonDict
from .models import SkillCatalog
from .models import SkillSpec


INDEX_PATH = "/.well-known/agent-skills/index.json"
SKILL_MD_TYPE = "skill-md"
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


def normalize_base_url(domain: str) -> str:
    raw_value = domain.strip()
    if not raw_value:
        raise ValueError("A domain is required for web skill discovery.")

    candidate = raw_value if "://" in raw_value else f"https://{raw_value}"
    parsed = urlparse(candidate)
    host = parsed.netloc or parsed.path
    if not host:
        raise ValueError(f"Invalid domain value: {domain!r}")

    scheme = parsed.scheme or "https"
    return f"{scheme}://{host}".rstrip("/")


def build_index_url(domain: str) -> str:
    return f"{normalize_base_url(domain)}{INDEX_PATH}"


async def discover_skill_catalog(domain: str, timeout: float = 20.0) -> SkillCatalog:
    base_url = normalize_base_url(domain)
    index_url = build_index_url(domain)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(index_url)
        response.raise_for_status()
        payload = response.json()

    raw_skills = _extract_raw_skills(payload)

    all_skills: list[SkillSpec] = []
    skill_md_contexts: list[str] = []
    use_markdown_negotiation = False

    skill_md_entries: list[tuple[int, dict]] = []
    other_entries: list[tuple[int, dict]] = []

    for index, raw_skill in enumerate(raw_skills, start=1):
        if not isinstance(raw_skill, dict):
            continue
        if raw_skill.get("type") == SKILL_MD_TYPE:
            skill_md_entries.append((index, raw_skill))
        else:
            other_entries.append((index, raw_skill))

    for index, raw_skill in other_entries:
        skill = _parse_plain_skill(raw_skill, base_url=base_url, default_index=index)
        if skill:
            all_skills.append(skill)

    if skill_md_entries:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            tasks = [
                _fetch_and_parse_skill_md(raw_skill, base_url, client)
                for _, raw_skill in skill_md_entries
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for (index, raw_skill), result in zip(skill_md_entries, results):
            if isinstance(result, Exception):
                skill = _parse_plain_skill(raw_skill, base_url=base_url, default_index=index)
                if skill:
                    all_skills.append(skill)
            else:
                specs, context, is_markdown_neg = result
                all_skills.extend(specs)
                if context:
                    skill_md_contexts.append(context)
                if is_markdown_neg:
                    use_markdown_negotiation = True

    # Site supports markdown negotiation → add Accept header to same-origin GET tools
    if use_markdown_negotiation:
        for skill in all_skills:
            if skill.method == "GET" and skill.url.startswith(base_url):
                skill.extra_headers.setdefault("Accept", "text/markdown")

    return SkillCatalog(
        domain=domain,
        base_url=base_url,
        index_url=index_url,
        skills=all_skills,
        source=payload,
        skill_md_contexts=skill_md_contexts,
        use_markdown_negotiation=use_markdown_negotiation,
    )


# ---------------------------------------------------------------------------
# SKILL.md fetching + parsing
# ---------------------------------------------------------------------------

async def _fetch_and_parse_skill_md(
    raw_skill: dict,
    base_url: str,
    client: httpx.AsyncClient,
) -> tuple[list[SkillSpec], str, bool]:
    """Fetch a SKILL.md and return (specs, static_context, is_markdown_negotiation)."""
    skill_name = raw_skill.get("name", "")
    skill_description = raw_skill.get("description", "")
    skill_url = raw_skill.get("url", "")

    if not skill_url:
        return [], "", False

    if skill_url.startswith("/"):
        md_url = f"{base_url}{skill_url}"
    elif not skill_url.startswith("http"):
        md_url = urljoin(f"{base_url}/", skill_url)
    else:
        md_url = skill_url

    response = await client.get(md_url, headers={"Accept": "text/markdown, text/plain, */*"})
    response.raise_for_status()
    content = response.text

    is_markdown_negotiation = "markdown-negotiation" in skill_name.lower()

    specs = _parse_skill_md_to_specs(skill_name, skill_description, content, base_url)
    static_context = _extract_static_context(skill_name, skill_description, content)

    return specs, static_context, is_markdown_negotiation


def _parse_skill_md_to_specs(
    skill_name: str,
    skill_description: str,
    content: str,
    base_url: str,
) -> list[SkillSpec]:
    """Extract callable HTTP endpoint SkillSpecs from a SKILL.md file."""
    specs: list[SkillSpec] = []
    code_block_pattern = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)

    for match in code_block_pattern.finditer(content):
        block_text = match.group(1).strip()
        endpoint = _try_parse_http_block(block_text)
        if not endpoint:
            continue

        section_heading = _find_nearest_heading(content, match.start())

        url: str = endpoint["url"]
        if url.startswith("/"):
            url = f"{base_url}{url}"

        path_params = re.findall(r"\{(\w+)\}", url)

        input_schema, parameter_locations = _build_endpoint_schema(
            path_params=path_params,
            body=endpoint.get("body"),
            method=endpoint["method"],
        )

        description = (
            f"{skill_description} ({section_heading})" if section_heading else skill_description
        )
        extra_headers: dict[str, str] = dict(endpoint.get("headers", {}))

        spec = SkillSpec(
            name=f"{skill_name} / {section_heading}" if section_heading else skill_name,
            description=description,
            method=endpoint["method"],
            url=url,
            input_schema=input_schema,
            parameter_locations=parameter_locations,
            source={"block": block_text, "section": section_heading, "skill": skill_name},
            extra_headers=extra_headers,
        )
        specs.append(spec)

    return specs


def _extract_static_context(skill_name: str, skill_description: str, content: str) -> str:
    """Return a capped summary of the SKILL.md for embedding in agent instructions."""
    cleaned = re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, flags=re.DOTALL).strip()
    if len(cleaned) > 1500:
        cleaned = cleaned[:1497] + "…"
    return f"### {skill_name}\n{skill_description}\n\n{cleaned}"


# ---------------------------------------------------------------------------
# HTTP block parser
# ---------------------------------------------------------------------------

def _try_parse_http_block(block: str) -> dict[str, Any] | None:
    """Try to parse a fenced code block as an HTTP request. Returns None if not HTTP."""
    lines = [ln for ln in block.splitlines() if ln.strip()]
    if not lines:
        return None

    first = lines[0].strip()
    parts = first.split(None, 1)
    if not parts or parts[0].upper() not in HTTP_METHODS:
        return None

    method = parts[0].upper()
    url: str | None = parts[1] if len(parts) > 1 else None
    headers: dict[str, str] = {}
    body: Any = None

    i = 1
    if url is None and i < len(lines):
        candidate = lines[i].strip()
        if candidate.startswith("http") or candidate.startswith("/"):
            url = candidate
            i += 1

    if not url:
        return None

    in_body = False
    body_lines: list[str] = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if in_body:
            body_lines.append(line)
        elif stripped.startswith("{") or stripped.startswith("["):
            in_body = True
            body_lines.append(line)
        elif ":" in stripped and not stripped.startswith("http"):
            header_name, _, header_val = stripped.partition(":")
            headers[header_name.strip()] = header_val.strip()
        i += 1

    if body_lines:
        try:
            body = json.loads("\n".join(body_lines))
        except json.JSONDecodeError:
            body = "\n".join(body_lines)

    return {"method": method, "url": url, "headers": headers, "body": body}


def _find_nearest_heading(content: str, before_pos: int) -> str:
    pattern = re.compile(r"^#{2,3}\s+(.+)$", re.MULTILINE)
    last = ""
    for m in pattern.finditer(content[:before_pos]):
        last = m.group(1).strip()
    return last


def _build_endpoint_schema(
    path_params: list[str],
    body: Any,
    method: str,
) -> tuple[JsonDict, dict[str, str]]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    parameter_locations: dict[str, str] = {}

    for param in path_params:
        properties[param] = {
            "type": "string",
            "description": f"Value for the {{{param}}} path segment.",
        }
        required.append(param)
        parameter_locations[param] = "path"

    if isinstance(body, dict):
        for key, value in body.items():
            if isinstance(value, str) and "YOUR-" in value:
                param_type = "string"
                desc = f"Replace template placeholder for {key!r}."
            else:
                param_type = _json_type(value)
                desc = f"Body field: {key}"
            properties[key] = {"type": param_type, "description": desc}
            required.append(key)
            parameter_locations[key] = "body"

    schema: JsonDict = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = sorted(set(required))

    return schema, parameter_locations


def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


# ---------------------------------------------------------------------------
# Fallback parser for non-skill-md index entries
# ---------------------------------------------------------------------------

def _parse_plain_skill(raw_skill: dict, base_url: str, default_index: int) -> SkillSpec | None:
    name = _first_str(raw_skill, "name", "id", "title") or f"skill_{default_index}"
    description = _first_str(raw_skill, "description", "summary") or f"Remote web skill {name}."

    endpoint = raw_skill.get("endpoint")
    method = (
        _first_str(raw_skill, "method", "http_method", "httpMethod")
        or (_first_str(endpoint, "method") if isinstance(endpoint, dict) else None)
        or "GET"
    ).upper()

    raw_url = _first_str(raw_skill, "url", "href") or ""
    raw_path = _first_str(raw_skill, "path", "route") or ""
    if isinstance(endpoint, dict):
        raw_url = raw_url or _first_str(endpoint, "url", "href") or ""
        raw_path = raw_path or _first_str(endpoint, "path", "route") or ""
    elif isinstance(endpoint, str):
        raw_url = raw_url or endpoint
    if not raw_url and raw_path:
        raw_url = urljoin(f"{base_url}/", raw_path.lstrip("/"))

    if not raw_url:
        return None

    input_schema, parameter_locations = _build_plain_input_schema(raw_skill)
    return SkillSpec(
        name=name,
        description=description,
        method=method,
        url=raw_url,
        input_schema=input_schema,
        parameter_locations=parameter_locations,
        source=raw_skill,
    )


def _build_plain_input_schema(raw_skill: dict) -> tuple[JsonDict, dict[str, str]]:
    schema: JsonDict = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    required: list[str] = []
    parameter_locations: dict[str, str] = {}

    explicit = _first_map(raw_skill, "input_schema", "inputSchema", "request_schema", "schema")
    if explicit:
        schema = _normalize_object_schema(explicit)
        for prop in schema.get("properties", {}):
            parameter_locations[prop] = "body"

    parameters = _first_list(raw_skill, "parameters", "params", "arguments")
    top_required = raw_skill.get("required")
    if isinstance(parameters, list):
        for raw_param in parameters:
            if not isinstance(raw_param, dict):
                continue
            pname = _first_str(raw_param, "name", "id")
            if not pname:
                continue
            schema.setdefault("properties", {})[pname] = _build_property_schema(raw_param)
            parameter_locations[pname] = _first_str(raw_param, "in", "location") or "query"
            if raw_param.get("required") is True or (
                isinstance(top_required, list) and pname in top_required
            ):
                required.append(pname)

    if required:
        schema["required"] = sorted(set(required))
    return schema, parameter_locations


def _normalize_object_schema(raw: JsonDict) -> JsonDict:
    schema = copy.deepcopy(raw)
    if "properties" in schema:
        schema.setdefault("type", "object")
    elif schema.get("type") != "object":
        schema = {
            "type": "object",
            "properties": {"body": schema},
            "required": ["body"],
            "additionalProperties": False,
        }
    schema.setdefault("properties", {})
    schema.setdefault("additionalProperties", False)
    return schema


def _build_property_schema(raw_param: dict) -> JsonDict:
    nested = _first_map(raw_param, "schema")
    prop: JsonDict = copy.deepcopy(nested) if nested else {
        "type": _first_str(raw_param, "type") or "string"
    }
    desc = _first_str(raw_param, "description", "summary")
    if desc:
        prop["description"] = desc
    enums = raw_param.get("enum")
    if isinstance(enums, list) and enums:
        prop["enum"] = enums
    items = raw_param.get("items")
    if isinstance(items, dict):
        prop["items"] = items
    default = raw_param.get("default")
    if default is not None:
        prop["default"] = default
    return prop


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def _extract_raw_skills(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("skills", "tools", "endpoints", "functions"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _first_str(source: Any, *keys: str) -> str | None:
    if not isinstance(source, dict):
        return None
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_map(source: Any, *keys: str) -> JsonDict | None:
    if not isinstance(source, dict):
        return None
    for key in keys:
        value = source.get(key)
        if isinstance(value, dict):
            return value
    return None


def _first_list(source: Any, *keys: str) -> list[Any] | None:
    if not isinstance(source, dict):
        return None
    for key in keys:
        value = source.get(key)
        if isinstance(value, list):
            return value
    return None
