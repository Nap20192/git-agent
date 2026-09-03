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

    @property
    def id(self) -> str | None:
        return self._sandbox.id

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
        await self._sandbox.close()

    async def kill(self) -> None:
        await self._sandbox.destroy()


def _connection_config() -> ConnectionConfig:
    return ConnectionConfig(
        domain=settings.opensandbox_domain,
        api_key=settings.opensandbox_api_key or None,
    )


async def create_sandbox(image: str | None = None) -> OpenSandboxAdapter:
    sandbox = await _OpenSandbox.create(
        image or settings.sandbox_image,
        timeout=None,
        connection_config=_connection_config(),
    )
    return OpenSandboxAdapter(sandbox)


async def connect_sandbox(external_id: str) -> OpenSandboxAdapter:
    """Переподключение к существующему сэндбоксу по id (для resume/kill)."""
    sandbox = await _OpenSandbox.connect(
        external_id,
        connection_config=_connection_config(),
        skip_health_check=True,
    )
    return OpenSandboxAdapter(sandbox)
