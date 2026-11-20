"""SkillManageTool — create, list, load, or delete agent-authored skills."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, List, Optional

from openjarvis.core.paths import get_config_dir
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_SAFE_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
# A skill the assistant writes for itself may only chain harmless tools: no
# reading files, no memory writes, no other skills.
SKILL_STEP_TOOLS = frozenset({"calculator", "think", "web_search", "memory_search"})
MAX_SKILL_STEPS = 8


@ToolRegistry.register("skill_manage")
class SkillManageTool(BaseTool):
    """Manage agent-authored procedural skills."""

    def __init__(self, skills_dir: Path | str | None = None) -> None:
        if skills_dir is None:
            skills_dir = get_config_dir() / "skills"
        self._skills_dir = Path(skills_dir).expanduser()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="skill_manage",
            description="Create, list, load, or delete agent-authored skills.",
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "list", "load", "delete"],
                        "description": "Action to perform.",
                    },
                    "name": {
                        "type": "string",
                        "description": "Skill name (for create/load/delete).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Skill description (for create).",
                    },
                    "steps": {
                        "type": "array",
                        "description": (
                            "List of step dicts with tool_name and optional"
                            " arguments_template (for create)."
                        ),
                    },
                },
                "required": ["action"],
            },
            category="skill",
        )

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "list")
        name = params.get("name", "")
        if action == "create":
            return self._create(
                name, params.get("description", ""), params.get("steps", [])
            )
        elif action == "list":
            return self._list()
        elif action == "load":
            return self._load(name)
        elif action == "delete":
            return self._delete(name)
        return ToolResult(
            tool_name=self.spec.name,
            success=False,
            content=f"Unknown action: {action}",
        )

    def _skill_path(self, name: str) -> Optional[Path]:
        """``<skills_dir>/<name>.toml`` for a safe *name*, else None.

        Names are plain identifiers, so a skill can never be written, read or
        deleted outside the skills folder (e.g. ``../config``).
        """
        if not _SAFE_NAME.fullmatch(name or ""):
            return None
        path = (self._skills_dir / f"{name}.toml").resolve()
        if path.parent != self._skills_dir.resolve():
            return None
        return path

    def _bad_name(self, name: str) -> ToolResult:
        return ToolResult(
            tool_name=self.spec.name,
            success=False,
            content=(f"Invalid skill name: {name!r} (use letters, numbers, - or _)."),
        )

    def _create(self, name: str, description: str, steps: List[dict]) -> ToolResult:
        if not name:
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content="Skill name is required.",
            )
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        path = self._skill_path(name)
        if path is None:
            return self._bad_name(name)
        steps = list(steps or [])
        bad = [
            str(st.get("tool_name", "")) if isinstance(st, dict) else str(st)
            for st in steps
            if not isinstance(st, dict) or st.get("tool_name") not in SKILL_STEP_TOOLS
        ]
        if bad or len(steps) > MAX_SKILL_STEPS:
            allowed = ", ".join(sorted(SKILL_STEP_TOOLS))
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=(
                    f"Skills may use at most {MAX_SKILL_STEPS} steps and only "
                    f"these tools: {allowed}. Not allowed: {', '.join(bad) or '-'}"
                ),
            )
        # json.dumps gives a valid, fully escaped TOML basic string, so a
        # description can't inject new TOML tables or keys.
        lines = [
            "[skill]",
            f"name = {json.dumps(name)}",
            f"description = {json.dumps(str(description or ''))}",
            "",
        ]
        for step in steps:
            lines.append("[[skill.steps]]")
            lines.append(f"tool_name = {json.dumps(str(step.get('tool_name', '')))}")
            if "arguments_template" in step:
                template = str(step["arguments_template"])
                lines.append(f"arguments_template = {json.dumps(template)}")
            if "output_key" in step:
                lines.append(f"output_key = {json.dumps(str(step['output_key']))}")
            lines.append("")
        path.write_text("\n".join(lines))
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Created skill: {name}",
        )

    def _list(self) -> ToolResult:
        if not self._skills_dir.exists():
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                content="No skills directory found.",
            )
        skills = []
        for f in sorted(self._skills_dir.glob("*.toml")):
            skills.append(f.stem)
        if not skills:
            return ToolResult(
                tool_name=self.spec.name,
                success=True,
                content="No skills found.",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content="Available skills:\n" + "\n".join(f"- {s}" for s in skills),
        )

    def _load(self, name: str) -> ToolResult:
        path = self._skill_path(name)
        if path is None:
            return self._bad_name(name)
        if not path.exists():
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Skill not found: {name}",
            )
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=path.read_text(),
        )

    def _delete(self, name: str) -> ToolResult:
        path = self._skill_path(name)
        if path is None:
            return self._bad_name(name)
        if not path.exists():
            return ToolResult(
                tool_name=self.spec.name,
                success=False,
                content=f"Skill not found: {name}",
            )
        path.unlink()
        return ToolResult(
            tool_name=self.spec.name,
            success=True,
            content=f"Deleted skill: {name}",
        )
