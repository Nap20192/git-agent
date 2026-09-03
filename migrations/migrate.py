"""Единый мигратор: применяет agent/*.sql и backend/*.sql по порядку
+ создаёт таблицы чекпоинтов LangGraph."""

from pathlib import Path

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver

from core.config import settings
from pkg.logger import get_logger

log = get_logger("migrate")

# сервис -> таблица учёта версий (имена версий — голые имена файлов)
SERVICES = {"agent": "schema_migrations", "backend": "hub.schema_migrations"}


def _apply(conn: psycopg.Connection, subdir: str, table: str) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {table} ("
        "version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    applied = {v for (v,) in conn.execute(f"SELECT version FROM {table}")}
    for sql_file in sorted((Path(__file__).parent / subdir).glob("*.sql")):
        if sql_file.name in applied:
            continue
        conn.execute(sql_file.read_text())
        conn.execute(f"INSERT INTO {table} (version) VALUES (%s)", (sql_file.name,))
        log.info("migration applied", service=subdir, version=sql_file.name)


def main() -> None:
    with psycopg.connect(settings.database_url) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS hub")
        for subdir, table in SERVICES.items():
            _apply(conn, subdir, table)

    with PostgresSaver.from_conn_string(settings.database_url) as saver:
        saver.setup()
    log.info("checkpointer tables ready")


if __name__ == "__main__":
    main()
