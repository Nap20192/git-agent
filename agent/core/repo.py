"""Подготовка Репозитория в Песочнице: clone + опциональный пин коммита."""

from __future__ import annotations

import asyncio
import os
import shlex

from core.ports import Sandbox, SandboxCommandError
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


async def repo_present(sandbox: Sandbox) -> bool:
    """Репозиторий уже склонирован в песочнице? (песочницу создаёт юзер, не раннер)"""
    repo_dir = shlex.quote(sandbox.repo_dir)
    out = await sandbox.run(f"[ -d {repo_dir}/.git ] && echo yes || echo no")
    return out.strip().endswith("yes")


async def advance_repo(sandbox: Sandbox, checkout_ref: str) -> None:
    """Продвинуть УЖЕ склонированный репозиторий на ref без переклона (reuse песочницы)."""
    repo_dir = shlex.quote(sandbox.repo_dir)
    ref = shlex.quote(checkout_ref)
    await sandbox.run(
        f"git -C {repo_dir} fetch --depth 2 origin {ref}"
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
            f"git -C {repo_dir} fetch --depth 2 origin {ref}"
            f" && git -C {repo_dir} checkout --detach {ref}",
            timeout_seconds=CLONE_TIMEOUT_SECONDS,
        )
        if len(checkout_ref) == 40:
            head = (await sandbox.run(f"git -C {repo_dir} rev-parse HEAD")).strip()
            if head != checkout_ref:
                raise RuntimeError(f"checkout drift: HEAD {head} != pinned {checkout_ref}")


async def _has_commit(sandbox: Sandbox, sha: str) -> bool:
    repo_dir = shlex.quote(sandbox.repo_dir)
    try:
        await sandbox.run(f"git -C {repo_dir} cat-file -e {shlex.quote(sha)}^{{commit}}")
    except SandboxCommandError:
        return False
    return True


async def ensure_commits(
    sandbox: Sandbox, shas: list[str], *, merge_base_of: tuple[str, str] | None = None
) -> str | None:
    """Догрузить в shallow-клон коммиты скоупа События; вернуть merge-base пары (PR).

    Каждый отсутствующий sha фетчится по хэшу (`fetch --depth 1 origin <sha>` — GitHub/GitLab
    отдают reachable-коммиты по sha); для двухточечного diff истории не нужно. Для PR
    (`merge_base_of`) merge-base требует связной истории: не нашёлся — `fetch --unshallow`
    (один раз на песочницу) и повтор. Провалы — warning, не исключение: агент получит
    подсказку в тексте ошибки git_diff и сможет дофетчить сам.
    """
    repo_dir = shlex.quote(sandbox.repo_dir)
    for sha in dict.fromkeys(s for s in shas if s):
        if await _has_commit(sandbox, sha):
            continue
        try:
            await sandbox.run(
                f"git -C {repo_dir} fetch --depth 1 origin {shlex.quote(sha)}",
                timeout_seconds=CLONE_TIMEOUT_SECONDS,
            )
        except SandboxCommandError as exc:
            log.warning("commit fetch failed", sha=sha, stderr=exc.stderr[:200])
    if not merge_base_of:
        return None
    base, head = (shlex.quote(s) for s in merge_base_of)
    try:
        return (await sandbox.run(f"git -C {repo_dir} merge-base {base} {head}")).strip() or None
    except SandboxCommandError:
        pass
    try:
        await sandbox.run(
            f"git -C {repo_dir} fetch --unshallow origin || git -C {repo_dir} fetch origin",
            timeout_seconds=CLONE_TIMEOUT_SECONDS,
        )
        return (await sandbox.run(f"git -C {repo_dir} merge-base {base} {head}")).strip() or None
    except SandboxCommandError as exc:
        log.warning("merge-base unavailable", base=merge_base_of[0], stderr=exc.stderr[:200])
        return None
