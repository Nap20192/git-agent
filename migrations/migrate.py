"""Применяет migrations/*.sql по порядку + создаёт таблицы чекпоинтов LangGraph.

Запуск: uv run python migrations/migrate.py
"""

from pathlib import Path

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver

from core.config import settings
from pkg.logger import get_logger

log = get_logger("migrate")


def main() -> None:
    with psycopg.connect(settings.database_url) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        applied = {v for (v,) in conn.execute("SELECT version FROM schema_migrations")}
        for sql_file in sorted(Path(__file__).parent.glob("*.sql")):
            if sql_file.name in applied:
                continue
            conn.execute(sql_file.read_text())
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (sql_file.name,))
            log.info("migration applied", version=sql_file.name)

    # Таблицы чекпоинтов LangGraph (setup идемпотентен)
    with PostgresSaver.from_conn_string(settings.database_url) as saver:
        saver.setup()
    log.info("checkpointer tables ready")


if __name__ == "__main__":
    main()
