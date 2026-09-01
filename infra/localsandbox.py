"""Local-«песочница»: команды выполняются на хосте в отдельной директории.

БЕЗ ИЗОЛЯЦИИ — недоверенный код (git-хуки и т.п.) может исполниться на хосте.
Только для своих репозиториев и офлайн-отладки.
"""

import asyncio
import shutil
import tempfile
from pathlib import Path

from core.ports import SandboxCommandError
from pkg.logger import get_logger

log = get_logger(__name__)


class LocalSandbox:
    def __init__(self, base_dir: str) -> None:
        Path(base_dir).mkdir(parents=True, exist_ok=True)
        self._dir = Path(tempfile.mkdtemp(prefix="run-", dir=base_dir))
        log.warning("local sandbox: NO isolation, host execution", dir=str(self._dir))

    @property
    def repo_dir(self) -> str:
        return str(self._dir / "repo")

    async def run(self, command: str, *, timeout_seconds: float | None = None) -> str:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._dir,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout_seconds)
        if proc.returncode != 0:
            raise SandboxCommandError(command, proc.returncode, stderr.decode())
        return stdout.decode()

    async def close(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)
