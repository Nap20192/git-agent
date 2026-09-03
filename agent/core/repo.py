"""Подготовка Репозитория в Песочнице: clone + опциональный пин коммита."""

from __future__ import annotations

import asyncio
import os
import shlex

from core.ports import Sandbox
from pkg.logger import get_logger

log = get_logger(__name__)

CLONE_TIMEOUT_SECONDS = 180.0


async def resolve_commit_sha(repo_url: str) -> str:
    """HEAD-коммит без clone: ls-remote для URL, rev-parse для локального пути."""
    args = (
        ["git", "-C", repo_url, "rev-parse", "HEAD"]
        if os.path.isdir(repo_url)
        else ["git", "ls-remote", repo_url, "HEAD"]
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        token = out.decode().split()[0] if out.split() else ""
        return token or "unknown"
    except Exception:
        log.warning("commit sha resolution failed; using 'unknown'", repo_url=repo_url)
        return "unknown"


async def advance_repo(sandbox: Sandbox, checkout_ref: str) -> None:
    """Продвинуть УЖЕ склонированный репозиторий на ref без переклона (reuse песочницы)."""
    repo_dir = shlex.quote(sandbox.repo_dir)
    ref = shlex.quote(checkout_ref)
    await sandbox.run(
        f"git -C {repo_dir} fetch --depth 1 origin {ref}"
        f" && git -C {repo_dir} checkout --detach {ref}",
        timeout_seconds=CLONE_TIMEOUT_SECONDS,
    )


async def prepare_repo(sandbox: Sandbox, repo_url: str, checkout_ref: str | None = None) -> None:
    """Клон + опциональный пин коммита."""
    repo_dir = shlex.quote(sandbox.repo_dir)
    await sandbox.run(
        f"rm -rf {repo_dir} && git clone --depth 1 {shlex.quote(repo_url)} {repo_dir}",
        timeout_seconds=CLONE_TIMEOUT_SECONDS,
    )
    if checkout_ref:
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
