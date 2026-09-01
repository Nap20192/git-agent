from typing import Any, TypedDict


class RepoState(TypedDict, total=False):
    repo_url: str
    checkout_ref: str  # пин коммита: scan делает checkout после clone (evals)
    scan: dict[str, Any]  # результат Скана: дерево, языки, ключевые файлы
    parse: dict[str, Any]  # результат Разбора: модули, зависимости, описание
    report: dict[str, Any]  # итоговый Отчёт
    error: str
