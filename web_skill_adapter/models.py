from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any


JsonDict = dict[str, Any]


@dataclass(slots=True)
class SkillSpec:
    name: str
    description: str
    method: str
    url: str
    input_schema: JsonDict
    parameter_locations: dict[str, str]
    source: JsonDict
    tool_name: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class SkillCatalog:
    domain: str
    base_url: str
    index_url: str
    skills: list[SkillSpec]
    source: JsonDict | list[Any]
    skill_md_contexts: list[str] = field(default_factory=list)
    use_markdown_negotiation: bool = False
