"""
Kagenti SkillsLoader — Parse CLAUDE.md + .claude/skills/ into an agent system prompt (Phase 4, C10)

Loads the same instruction files that Claude Code uses locally and converts
them into a system prompt that any LLM can consume via litellm.

Usage:
    from skills_loader import SkillsLoader
    loader = SkillsLoader("/workspace")
    system_prompt = loader.build_system_prompt()
    skills_index = loader.list_skills()
"""

import os
from pathlib import Path
from typing import Optional


class SkillsLoader:
    """Loads CLAUDE.md and .claude/skills/ from a repo workspace."""

    def __init__(self, workspace: str = "/workspace"):
        self.workspace = Path(workspace)
        self.claude_md: Optional[str] = None
        self.skills: dict[str, str] = {}
        self._load()

    def _load(self):
        """Load CLAUDE.md and all skill files."""
        # Load CLAUDE.md
        claude_md_path = self.workspace / "CLAUDE.md"
        if claude_md_path.exists():
            self.claude_md = claude_md_path.read_text(encoding="utf-8")

        # Load skills from .claude/skills/
        skills_dir = self.workspace / ".claude" / "skills"
        if skills_dir.is_dir():
            for skill_dir in sorted(skills_dir.iterdir()):
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        skill_name = skill_dir.name
                        self.skills[skill_name] = skill_file.read_text(encoding="utf-8")

    def list_skills(self) -> list[str]:
        """Return sorted list of available skill names."""
        return sorted(self.skills.keys())

    def get_skill(self, name: str) -> Optional[str]:
        """Get a specific skill's content by name."""
        return self.skills.get(name)

    def build_system_prompt(self, include_skills_index: bool = True) -> str:
        """Build a system prompt from CLAUDE.md and skills.

        Returns a prompt string that can be used with any LLM via litellm.
        """
        parts = []

        # Project instructions from CLAUDE.md
        if self.claude_md:
            parts.append("# Project Instructions\n")
            parts.append(self.claude_md)
            parts.append("\n")

        # Skills index
        if include_skills_index and self.skills:
            parts.append("# Available Skills\n\n")
            parts.append("The following guided workflows are available. ")
            parts.append("When a task matches a skill, follow its instructions.\n\n")
            for name in sorted(self.skills):
                # Extract the first line (description) from each skill
                first_line = self.skills[name].split("\n")[0].strip()
                if first_line.startswith("#"):
                    first_line = first_line.lstrip("# ").strip()
                parts.append(f"- **{name}**: {first_line}\n")
            parts.append("\n")

        return "".join(parts)

    def build_full_prompt_with_skill(self, skill_name: str) -> str:
        """Build system prompt with a specific skill's full content included."""
        base = self.build_system_prompt(include_skills_index=True)
        skill_content = self.get_skill(skill_name)
        if skill_content:
            base += f"\n# Active Skill: {skill_name}\n\n{skill_content}\n"
        return base


if __name__ == "__main__":
    import sys

    workspace = sys.argv[1] if len(sys.argv) > 1 else "/workspace"
    loader = SkillsLoader(workspace)

    print(f"Workspace: {workspace}")
    print(f"CLAUDE.md: {'found' if loader.claude_md else 'not found'}")
    print(f"Skills: {len(loader.skills)}")
    if loader.skills:
        print(f"  Available: {', '.join(loader.list_skills())}")

    print("\n--- System Prompt Preview (first 500 chars) ---")
    prompt = loader.build_system_prompt()
    print(prompt[:500])
    if len(prompt) > 500:
        print(f"... ({len(prompt)} chars total)")
