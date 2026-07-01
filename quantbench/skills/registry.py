from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class Skill:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., Any]


class SkillRegistry:
    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": skill.name,
                    "description": skill.description,
                    "parameters": skill.parameters,
                },
            }
            for skill in self._skills.values()
        ]

    def execute(self, name: str, args: dict[str, Any]) -> Any:
        if name not in self._skills:
            return {"error": f"unknown tool: {name}"}
        return self._skills[name].fn(**args)
