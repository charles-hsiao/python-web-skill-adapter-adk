from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor

from google.adk import Agent
from google.adk.apps import App

from .config import load_settings
from .discovery import discover_skill_catalog
from .dynamic_tools import build_skill_tools


def build_agent(domain: str | None = None, model: str | None = None) -> Agent:
    settings = load_settings()
    active_domain = domain or settings.domain
    active_model = model or settings.model

    if not active_domain:
        return Agent(
            name="web_skill_adapter",
            model=active_model,
            description="ADK agent for remotely discovered web skills.",
            instruction=(
                "You are a web skill adapter demo agent. No remote skills were loaded because "
                "WEB_SKILL_DOMAIN is not configured. Explain that the operator must set "
                "WEB_SKILL_DOMAIN before starting the ADK app, then restart `adk web` or `adk run`."
            ),
        )

    try:
        # asyncio.run() fails when called from within a running event loop (e.g. ADK web server).
        # Run discovery in a fresh thread with its own event loop to avoid this conflict.
        def _run_discovery():
            return asyncio.run(discover_skill_catalog(active_domain, timeout=settings.timeout))

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run_discovery)
            catalog = future.result()

        tools = build_skill_tools(catalog, timeout=settings.timeout)

        # Build instruction preamble
        instruction_parts = [
            f"You are a web skill adapter demo agent for {catalog.base_url}.",
            "Use the discovered tools when the user asks for actions supported by the remote site.",
            "Do not invent remote capabilities. If the available tools are insufficient, say so clearly.",
        ]

        if catalog.use_markdown_negotiation:
            instruction_parts.append(
                "This site supports Accept: text/markdown content negotiation — "
                "GET requests to the site will automatically request markdown responses."
            )

        if catalog.skill_md_contexts:
            instruction_parts.append("\n## Site Knowledge\n")
            # ADK's instruction templating uses the regex {+[^{}]*}+ to find
            # context variables. Replace all {var} patterns in remote content
            # with backtick notation so they are never treated as variables.
            instruction_parts.extend(
                re.sub(r'\{([^{}]+)\}', r'`\1`', ctx) for ctx in catalog.skill_md_contexts
            )

        if not tools:
            instruction_parts.insert(1,
                "The skill index loaded successfully but no callable HTTP endpoints were parsed. "
                "Explain this to the user."
            )

        instruction = "\n\n".join(instruction_parts)
        return Agent(
            name="web_skill_adapter",
            model=active_model,
            description="ADK agent for remotely discovered web skills.",
            instruction=instruction,
            tools=tools,
        )
    except Exception as exc:
        safe_exc = str(exc).replace("{", "{{").replace("}", "}}")
        return Agent(
            name="web_skill_adapter",
            model=active_model,
            description="ADK agent for remotely discovered web skills.",
            instruction=(
                f"You are a web skill adapter demo agent. Remote skill discovery failed for {active_domain}. "
                f"Explain the startup error to the user and include this detail: {safe_exc}."
            ),
        )


root_agent = build_agent()

app = App(
    name="web_skill_adapter",
    root_agent=root_agent,
)
