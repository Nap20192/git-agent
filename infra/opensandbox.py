"""OpenSandbox — адаптер порта core.ports.Sandbox."""

from datetime import timedelta

from opensandbox.config import ConnectionConfig
from opensandbox.models.execd import RunCommandOpts
from opensandbox.sandbox import Sandbox as _OpenSandbox

from core.config import settings
from core.ports import SandboxCommandError


class OpenSandboxAdapter:
    repo_dir = "/repo"

    def __init__(self, sandbox: _OpenSandbox) -> None:
        self._sandbox = sandbox

    async def run(self, command: str, *, timeout_seconds: float | None = None) -> str:
        opts = (
            RunCommandOpts(timeout=timedelta(seconds=timeout_seconds))
            if timeout_seconds is not None
            else None
        )
        execution = await self._sandbox.commands.run(command, opts=opts)
        stdout = "\n".join(line.text.rstrip("\n") for line in execution.logs.stdout)
        stderr = "\n".join(line.text.rstrip("\n") for line in execution.logs.stderr)
        if execution.exit_code not in (0, None):
            raise SandboxCommandError(command, execution.exit_code, stderr or stdout)
        return stdout

    async def close(self) -> None:
        await self._sandbox.kill()


async def create_sandbox(image: str | None = None) -> OpenSandboxAdapter:
    sandbox = await _OpenSandbox.create(
        image or settings.sandbox_image,
        connection_config=ConnectionConfig(
            domain=settings.opensandbox_domain,
            api_key=settings.opensandbox_api_key or None,
        ),
    )
    return OpenSandboxAdapter(sandbox)
