"""OpenSandbox — адаптер порта core.ports.Sandbox."""

from datetime import timedelta

from opensandbox.config import ConnectionConfig
from opensandbox.models.execd import RunCommandOpts
from opensandbox.sandbox import Sandbox as _OpenSandbox

from core.config import settings
from core.ports import SandboxCommandError

# execd после execution_complete держит SSE-стрим ещё ApiGracefulShutdownTimeout
# (дефолт 1s) — это ~1s накладных на КАЖДУЮ команду. Ручка — env execd.
EXECD_ENV = {"EXECD_API_GRACE_SHUTDOWN": "100ms"}


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


def _connection_config(
    domain: str | None = None, api_key: str | None = None
) -> ConnectionConfig:
    return ConnectionConfig(
        domain=domain or settings.opensandbox_domain,
        api_key=api_key or settings.opensandbox_api_key or None,
    )


async def create_sandbox(
    image: str | None = None, *, domain: str | None = None, api_key: str | None = None
) -> OpenSandboxAdapter:
    """domain/api_key — переопределение endpoint'а (sandbox connection Сборки)."""
    sandbox = await _OpenSandbox.create(
        image or settings.sandbox_image,
        timeout=None,
        env=EXECD_ENV,
        connection_config=_connection_config(domain, api_key),
    )
    return OpenSandboxAdapter(sandbox)


async def connect_sandbox(
    external_id: str, *, domain: str | None = None, api_key: str | None = None
) -> OpenSandboxAdapter:
    """Переподключение к существующему сэндбоксу по id (для resume/kill)."""
    sandbox = await _OpenSandbox.connect(
        external_id,
        connection_config=_connection_config(domain, api_key),
        skip_health_check=True,
    )
    return OpenSandboxAdapter(sandbox)
