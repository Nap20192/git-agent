"""Подготовка Репозитория в Песочнице: clone + опциональный пин коммита.

Единственная реализация clone/checkout в проекте — её используют и профили
рантайма (prepare на каждой попытке), и scan-узел (fallback для прямого
запуска графа без prepare: тесты, demo).
"""

from __future__ import annotations

import shlex

from core.ports import Sandbox

CLONE_TIMEOUT_SECONDS = 180.0


async def prepare_repo(sandbox: Sandbox, repo_url: str, checkout_ref: str | None = None) -> None:
    """Клон + опциональный пин коммита.

    В durable-рантайме работает на КАЖДОЙ попытке (resume = свежая песочница,
    чекпоинт хранит только состояние графа) — без этого resumed-ран продолжается
    в пустой ФС. Полный sha после checkout верифицируется fail-loud: тихий дрейф
    на дефолтную ветку — ровно то, от чего защищается пин.
    """
    repo_dir = shlex.quote(sandbox.repo_dir)
    await sandbox.run(
        f"rm -rf {repo_dir} && git clone --depth 1 {shlex.quote(repo_url)} {repo_dir}",
        timeout_seconds=CLONE_TIMEOUT_SECONDS,
    )
    if checkout_ref:
        # depth-1 клон не содержит произвольный sha — дотягиваем точечно
        ref = shlex.quote(checkout_ref)
        await sandbox.run(
            f"git -C {repo_dir} fetch --depth 1 origin {ref}"
            f" && git -C {repo_dir} checkout --detach {ref}",
            timeout_seconds=CLONE_TIMEOUT_SECONDS,
        )
        if len(checkout_ref) == 40:
            head = (await sandbox.run(f"git -C {repo_dir} rev-parse HEAD")).strip()
            if head != checkout_ref:
                raise RuntimeError(f"checkout drift: HEAD {head} != pinned {checkout_ref}")
