"""Точка входа Раннера: `uv run uvicorn runner:app --port 8081` (или `task runner`).

Тонкий адаптер по образцу main.py: композиция — в deps.runner_deps(), роуты —
в infra/server/runner_api.py; lifespan лишь связывает их через app.state.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def _lifespan(app: FastAPI):
    from deps.container import runner_deps

    async with runner_deps() as deps:
        app.state.service = deps.service
        yield


def create_runner_app() -> FastAPI:
    from core.config import settings
    from infra.server.request_context import RequestContextMiddleware
    from infra.server.runner_api import install_api
    from pkg.dnsfix import install as install_dns

    install_dns(settings.dns_server)  # dev: обход сломанного системного резолвера
    app = FastAPI(title="git-agent runner", lifespan=_lifespan)
    app.add_middleware(RequestContextMiddleware)  # X-Trace-Id от hub → в лог-контекст
    install_api(app)
    return app


app = create_runner_app()


def main() -> None:
    import uvicorn

    from core.config import settings

    # log_config=None: uvicorn не переопределяет логирование — всё идёт через pkg.logger
    uvicorn.run(app, port=settings.runner_port, timeout_graceful_shutdown=30, log_config=None)


if __name__ == "__main__":
    main()
