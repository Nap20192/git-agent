"""Герметичность тестов: трейсинг выключен + вся работа с БД — в тестовой БД.

Тестовые Экземпляры/События/чекпоинты пишутся в отдельную БД (`<db>_test`), а не в
рабочую. Настройка на импорте conftest (до сбора тестов), чтобы `_pg_available`
интеграционных тестов видел уже созданную тестовую БД. PG недоступен → остаёмся
на рабочем URL, интеграционные/e2e тесты скипаются сами.
"""

import contextlib
import os

for _var in (
    "LANGSMITH_TRACING",
    "LANGCHAIN_TRACING_V2",
    "LANGCHAIN_TRACING",
    "LANGFUSE_TRACING",
):
    os.environ[_var] = "false"

from core.config import settings  # noqa: E402


def _swap_db(url: str, suffix: str = "_test") -> str:
    base, _, tail = url.rpartition("/")
    name, sep, query = tail.partition("?")
    return f"{base}/{name}{suffix}{sep}{query}"


_MAIN_URL = settings.database_url
_TEST_URL = os.environ.get("TEST_DATABASE_URL") or _swap_db(_MAIN_URL)


def _setup_test_db() -> bool:
    import psycopg

    name = _TEST_URL.rsplit("/", 1)[-1].split("?")[0]
    try:
        with psycopg.connect(_MAIN_URL, autocommit=True, connect_timeout=2) as conn:
            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
            ).fetchone()
            if not exists:
                conn.execute(f'CREATE DATABASE "{name}"')
    except Exception:
        return False
    return True


def _reset_test_db() -> None:
    """Чистый старт: снести чекпоинты (hub.* чистят сами интеграционные тесты)."""
    import psycopg

    with psycopg.connect(_TEST_URL, autocommit=True, connect_timeout=2) as conn:
        conn.execute("TRUNCATE checkpoints, checkpoint_writes, checkpoint_blobs")


if _setup_test_db():
    settings.database_url = _TEST_URL
    from migrations.migrate import main as _migrate

    with contextlib.suppress(Exception):
        _migrate()
        _reset_test_db()
