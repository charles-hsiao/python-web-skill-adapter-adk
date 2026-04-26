from __future__ import annotations

import argparse
import asyncio

from google.adk.runners import InMemoryRunner
from google.genai import types

from .agent import build_agent
from .config import load_settings


APP_NAME = "web_skill_adapter_cli"
USER_ID = "local_user"


async def run_cli(domain: str, model: str | None = None) -> None:
    agent = build_agent(domain=domain, model=model)
    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    session = await runner.session_service.create_session(app_name=APP_NAME, user_id=USER_ID)

    print(f"Loaded agent for domain: {domain}")
    print("Type 'exit' or 'quit' to stop.")

    while True:
        prompt = input("\nYou: ").strip()
        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit"}:
            break

        message = types.Content(role="user", parts=[types.Part(text=prompt)])
        response_parts: list[str] = []
        async for event in runner.run_async(user_id=USER_ID, session_id=session.id, new_message=message):
            if not event.content or not event.content.parts:
                continue
            if event.author != agent.name:
                continue
            for part in event.content.parts:
                if part.text:
                    response_parts.append(part.text)

        print(f"Agent: {''.join(response_parts).strip()}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the web skill adapter demo locally.")
    parser.add_argument("--domain", help="Domain used for skill discovery.")
    parser.add_argument("--model", help="Override the ADK model name.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings()
    domain = args.domain or settings.domain or input("Domain: ").strip()
    asyncio.run(run_cli(domain=domain, model=args.model or settings.model))


if __name__ == "__main__":
    main()