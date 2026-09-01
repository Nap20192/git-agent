"""Герметичность тестов: внешний трейсинг принудительно выключен.

.env разработчика (через load_dotenv() в core.config, импортируемом частью
тестов) кладёт LANGSMITH_TRACING=true в os.environ всего pytest-процесса.
Тогда langchain авто-трейсит каждый ран, а langsmith сериализует inputs
pydantic-ом (mode="json") — это ВЫПИВАЕТ iterator-поля фейковых моделей
(GenericFakeChatModel.messages, общий скрипт лида и сабагента) и шлёт
реальные сетевые запросы в LangSmith. Симптом: тесты сабагентов падали
StopIteration→RuntimeError, но только когда до них успевал импортироваться
core.config (порядко-зависимо).

Ставим явный "false" на этапе импорта conftest — до импорта тестовых модулей;
load_dotenv(override=False) его не перезапишет. Тесты трейсинга
(tests/unit/test_tracing.py) управляют env сами через monkeypatch.
"""

import os

for _var in (
    "LANGSMITH_TRACING",
    "LANGCHAIN_TRACING_V2",
    "LANGCHAIN_TRACING",
    "LANGFUSE_TRACING",
):
    os.environ[_var] = "false"
