from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx
from google.adk.tools import BaseTool
from google.adk.tools import ToolContext
from google.genai import types

from .models import SkillCatalog
from .models import SkillSpec


def build_skill_tools(catalog: SkillCatalog, timeout: float) -> list[BaseTool]:
    tools: list[BaseTool] = []
    seen_names: set[str] = set()

    for skill in catalog.skills:
        tool_name = uniquify_tool_name(skill.name, seen_names)
        seen_names.add(tool_name)
        skill.tool_name = tool_name
        tools.append(DiscoveredSkillTool(skill=skill, timeout=timeout))

    return tools


def uniquify_tool_name(raw_name: str, seen_names: set[str]) -> str:
    sanitized = sanitize_tool_name(raw_name)
    candidate = sanitized
    suffix = 2
    while candidate in seen_names:
        candidate = f"{sanitized}_{suffix}"
        suffix += 1
    return candidate


def sanitize_tool_name(raw_name: str) -> str:
    output = []
    for character in raw_name.lower():
        if character.isalnum() or character == "_":
            output.append(character)
        else:
            output.append("_")
    name = re.sub(r"_+", "_", "".join(output)).strip("_")
    if not name:
        name = "web_skill"
    if name[0].isdigit():
        name = f"web_skill_{name}"
    if not name.startswith("web_skill_"):
        name = f"web_skill_{name}"
    return name


class DiscoveredSkillTool(BaseTool):
    def __init__(self, skill: SkillSpec, timeout: float):
        # Escape braces in the URL so ADK's templating engine does not try to
        # resolve path-parameter placeholders (e.g. {slug}) as context variables.
        safe_url = skill.url.replace("{", "{{").replace("}", "}}")
        description = f"{skill.description} Uses {skill.method} {safe_url}"
        super().__init__(name=skill.tool_name, description=description)
        self._skill = skill
        self._timeout = timeout
        self._declaration = types.FunctionDeclaration(
            name=skill.tool_name,
            description=description,
            parameters_json_schema=skill.input_schema,
        )

    def _get_declaration(self) -> types.FunctionDeclaration:
        return self._declaration

    async def run_async(
        self,
        *,
        args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict[str, Any]:
        del tool_context
        return await invoke_remote_skill(self._skill, args=args, timeout=self._timeout)


async def invoke_remote_skill(
    skill: SkillSpec,
    *,
    args: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    request_url = skill.url
    query_params: dict[str, Any] = {}
    headers: dict[str, str] = {}
    body_payload: Any = None
    body_args: dict[str, Any] = {}

    for arg_name, arg_value in args.items():
        location = skill.parameter_locations.get(arg_name)
        if location == "path":
            request_url = request_url.replace(f"{{{arg_name}}}", quote(str(arg_value), safe=""))
            request_url = request_url.replace(f":{arg_name}", quote(str(arg_value), safe=""))
        elif location == "header":
            headers[arg_name] = str(arg_value)
        elif location == "body":
            body_args[arg_name] = arg_value
        elif location == "query":
            query_params[arg_name] = arg_value
        elif skill.method in {"GET", "DELETE"}:
            query_params[arg_name] = arg_value
        else:
            body_args[arg_name] = arg_value

    if body_args:
        if set(body_args) == {"body"} and isinstance(body_args["body"], dict):
            body_payload = body_args["body"]
        else:
            body_payload = body_args

    # Merge per-skill static headers (e.g. Accept: text/markdown) with per-call headers
    merged_headers: dict[str, str] = dict(skill.extra_headers)
    merged_headers.update(headers)

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.request(
                method=skill.method,
                url=request_url,
                params=query_params or None,
                headers=merged_headers or None,
                json=body_payload,
            )
            response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        parsed_body: Any
        if "application/json" in content_type:
            parsed_body = response.json()
        else:
            parsed_body = response.text

        return {
            "status": "success",
            "skill": skill.name,
            "method": skill.method,
            "url": request_url,
            "response": parsed_body,
        }
    except httpx.HTTPStatusError as exc:
        response_text = exc.response.text if exc.response is not None else ""
        return {
            "status": "error",
            "skill": skill.name,
            "method": skill.method,
            "url": request_url,
            "error": f"HTTP {exc.response.status_code}",
            "response": response_text,
        }
    except httpx.RequestError as exc:
        return {
            "status": "error",
            "skill": skill.name,
            "method": skill.method,
            "url": request_url,
            "error": str(exc),
        }
