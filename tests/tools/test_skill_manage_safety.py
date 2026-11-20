"""skill_manage can't escape its folder or inject TOML."""

from __future__ import annotations

import tomllib

from openjarvis.tools.skill_manage import SkillManageTool


def test_rejects_path_traversal(tmp_path):
    skills = tmp_path / "skills"
    target = tmp_path / "config.toml"
    target.write_text("[tools]\nenabled = []\n")
    tool = SkillManageTool(skills_dir=skills)
    for action in ("create", "load", "delete"):
        r = tool.execute(action=action, name="../config", description="x", steps=[])
        assert not r.success
    assert target.read_text() == "[tools]\nenabled = []\n"


def test_description_cannot_inject_toml(tmp_path):
    tool = SkillManageTool(skills_dir=tmp_path)
    evil = 'x"\n[tools]\nenabled = ["shell_exec"]\n#'
    assert tool.execute(action="create", name="ok", description=evil, steps=[]).success
    data = tomllib.loads((tmp_path / "ok.toml").read_text())
    assert data["skill"]["description"] == evil
    assert "tools" not in data
