"""Точка входа: HTTP-gateway (FastAPI) над durable-рантаймом."""

from infra.server.app import create_app

app = create_app()


def main() -> None:
    import uvicorn

    from core.config import settings

    uvicorn.run(
        app,
        host=settings.server_host,
        port=settings.server_port,
        timeout_graceful_shutdown=30,
    )


if __name__ == "__main__":
    main()
