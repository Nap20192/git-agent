# summarize-500k

## Why

Тред Экземпляра живёт вечно (События + чат), а продакшен-пресет `prod_v2` запускал суммаризацию с 800k токенов — на моделях с окном 128k–262k контекст переполнялся раньше компакции. Решение пользователя 2026-09-04: суммаризировать с 500 000 токенов.

## What Changes

- Новый пресет `prod_v3` = `prod_v2` с `summarization_trigger_tokens` 500 000 (остальное без изменений: structured_prefix, keep 50k, guard 900k, без context editing). `prod_v2` остаётся неизменным как исторический.
- `PRODUCTION_MEMORY_PRESET` = `prod_v3`; allowlist провайдеров тот же.
- Попутно: тул `task` подставляет близкое имя типа Сабагента («general» → «general-purpose») с пометкой в результате, вместо «Task Failed. Unknown subagent type» — локальные модели пишут тип по памяти.

## Capabilities

### Modified Capabilities

- `memory-presets`: продакшен-дефолт и порог суммаризации.
- `lead-delegation`: устойчивость к неточному имени типа Сабагента.

## Impact

- `agent/core/memory/presets.py`, `agent/core/subagents/registry.py`, `agent/core/tools/delegation/task.py`, тесты.
