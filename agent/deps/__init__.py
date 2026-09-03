"""Композиционный корень: сборка и graceful-разбор зависимостей приложения."""

from deps.container import AppDeps, RunnerDeps, app_deps, runner_deps

__all__ = ["AppDeps", "RunnerDeps", "app_deps", "runner_deps"]
