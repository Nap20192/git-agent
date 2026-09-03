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
    from infra.server.runner_api import api

    app = FastAPI(title="git-agent runner", lifespan=_lifespan)
    app.include_router(api)
    return app


app = create_runner_app()


def main() -> None:
    import uvicorn

    from core.config import settings

    uvicorn.run(app, port=settings.runner_port, timeout_graceful_shutdown=30)


if __name__ == "__main__":
    main()
