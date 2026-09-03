"""Тул load_skill: справочник методик из core/skills."""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool


def build_load_skill_tool() -> BaseTool:
    """Тулза load_skill: справочник методик из core/skills."""
    from core.skills import load_skills, validate_requested_skills

    @tool
    def load_skill(skills: list[str]) -> str:
        """Загрузить справку по классам уязвимостей / технологиям в текущий ход.

        Зови перед проверкой конкретной техники, когда нужна точная методика
        (синтаксис, места, признаки). Содержимое приходит как справка, промпт
        не меняется.

        Args:
            skills: имена skills (например ["sql_injection", "authentication_jwt"]).
                Максимум 5. Каталог — в системном промпте.
        """
        err = validate_requested_skills(list(skills or []))
        if err:
            return f"load_skill: {err}"
        contents = load_skills(list(skills))
        if not contents:
            return "load_skill: nothing loaded"
        return "\n\n---\n\n".join(f"## Skill: {name}\n\n{body}" for name, body in contents.items())

    return load_skill
