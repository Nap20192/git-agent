"""Делегирование: тул `task` — единственный вход в систему сабагентов (core/subagents)."""

from core.tools.delegation.task import build_task_tool

__all__ = ["build_task_tool"]
