# Почему Лид и Сабагенты «перегружают модель» и откуда битые ссылки — эмпирика на наших логах + первичные источники 2024–2026

Дата: 2026-09-04. Состояние кода — `main` (`8e28bf0`), пути относительно `agent/`, если не сказано иное. Метод: Блок А — одноразовый скрипт по `logs/info.jsonl` (события `TurnTracer`: `llm call` / `tool call` / `tool done` / `turn summary`, группировка по `trace_id`) и по БД hub (`hub.findings`, `hub.reports`, `hub.activity`); ссылки прогнаны `curl -sL -m 15` плюс проверка содержимого для SPA-страниц (NVD/OSV) через `api.osv.dev`. Блок Б — WebSearch → WebFetch первичного источника; цитаты и числа только из того, что реально прочитано, недоступное помечено. Предыдущий обзор — [`agent-improvements-2026-09.md`](agent-improvements-2026-09.md) (верификация, SAST-гибриды, threat model, память) — здесь не повторяется; пересечения помечены «→ пред. отчёт §».

---

## 1. TL;DR

1. **Сабагенты — главный потребитель, а не главный источник результата.** За 9 ходов по Событиям Сабагенты сожгли 10,87 M из 11,72 M входных токенов (93 %), сделали 695 из 820 тул-вызовов, а из 44 запусков Сабагентов Находки дал только ≈ 1 из 14 в самом дорогом ходе (8,83 M токенов → 8 Находок, все из одного deps-Сабагента) и часть из 10 в ходе на qwen (18 Находок). ≥ 34 из 44 запусков (77 %) закончились без единой Находки.
2. **Оба хода, которые дошли до `processed` и записали Отчёт, — те, где Сабагентов не было** (`9385d6de`: 9 LLM-вызовов, 99 k токенов; `b89a516f`: 8 вызовов, 82 k). Все ходы с делегированием либо остановлены пользователем, либо упали (402, JSON-парсинг qwen, БД).
3. **21 % тул-вызовов — точные дубли** (173 из 820: тот же тул + те же аргументы в одном ходе). Рекорд — `read_file('/repo/app/routes/profile.js')` 8 раз за ход: каждый Сабагент заново читает те же файлы, потому что карта репо Лида ему не передаётся, а `read_file` без `offset` не помечается как «уже читал».
4. **Разведка вместо поиска: `list_dir`+`read_file` — 510 вызовов, `grep_code`+`git_diff`+`git_blame` — 96 (5,3 : 1).** У Сабагентов `read_file` — 389 из 695 (56 %). Это ровно «analysis paralysis» из «Danger of Overthinking» (arXiv 2502.08235) и FM-1.3 «Step repetition» (15,7 %) из MAST.
5. **Лимит `max_turns=50` Сабагента режет работу, а не заканчивает её.** В `7ab11450` 4 из 6 Сабагентов первой волны упали `Reached max_turns=50` с нулём Находок, пятый «Succeeded (capped)» с текстом «Writing the final report» — и отчёта не написал. Turn-cap без принудительного финального ответа = деньги в никуда.
6. **`load_skill` — скрытый пожиратель контекста:** один вызов возвращает 29–36 k символов (≈ 8–9 k токенов), 37 вызовов за 9 ходов, `xss` грузили 3 раза в одном ходе. Это ≈ 300 k токенов чистой справки, повторно оплаченной в каждом следующем LLM-вызове Сабагента.
7. **Битые ссылки — от памяти модели, не от тулов.** 11 из 48 URL в `hub.findings.references` (23 %) → 404. Все 11 — из хода на qwen, где ссылки писались «по памяти» (OWASP-слаги вроде `attacks/NoSQL_Injection`, `Top10/A1-2021-…` вместо `A01_2021`, несуществующий `MongoDB_Security_Cheatsheet`, ссылка на `uv.h` как «референс» для eval-инъекции): 11 из 28 таких URL (39 %) битые. Все 20 URL из deps-Сабагента на deepseek, который вытащил их из ответа `api.osv.dev` в Песочнице, — живые (0 %). Точно та же картина у arXiv 2604.03173: 3–13 % URL сфабрикованы, программная проверка + самокоррекция даёт «6–79× reduction».
8. **Локальная модель (qwen3.8-27b) не тянет этот граф:** медиана LLM-вызова 36–147 с (p90 396 с, максимум 27,6 мин на 50 k входа), три `run_failed` подряд с `Failed to parse tool call arguments as JSON … missing closing quote` (обрезанные аргументы), 6 делегаций подряд с выдуманным типом `general` (до фикса в `b71ea71`). На deepseek медиана 4–5 с.
9. **Источники сходятся: мульти-агент оправдан только на параллелизуемых независимых поверхностях с центральной верификацией.** Kim et al. (2512.08296): от +80,8 % на декомпозируемых задачах до −70 % на последовательных; Anthropic: 15× токенов и «scale effort to complexity» (простой запрос — 1 агент, 3–10 вызовов); Cognition: «single-threaded linear agent», Сабагенты Claude Code — только отвечают на вопросы. Наш промпт делает обратное: заставляет Лида делегировать *всё* («Even "just a quick look" … delegate it») по чек-листу из 8 классов независимо от размера scope.
10. **Ответ на вопрос «нужны ли Сабагенты»: по умолчанию — нет.** Для `push`/`pull_request`/`manual` (диапазон коммитов, обычно < 30 файлов) — single-agent Лид с todo-списком и жёстким бюджетом действий; делегирование включать только для `full_scan` и только по *файловым* поверхностям (не по классам уязвимостей), ≤ 3 Сабагента, каждый с картой репо на входе, `read_file`-кэшем и обязательным финальным отчётом при исчерпании лимита.
11. **Дообучать модель сейчас — не стоит; позже — только на «поведение агента», не на «знание уязвимостей».** SFT 7–32B на ~5 k отфильтрованных траекторий сильного учителя даёт +10–20 п.п. на SWE-bench Verified (SWE-Gym, SWE-smith 40,2 %, Skywork-SWE 38 %, Kimi-Dev 48,6 %), RL с наградой за корректный tool-use учит «меньше и точнее вызовов» (ToolRL: +15 % над SFT, «fewer and more proactive tool invocations»), но SWE-дообученные модели показывают ≤ 2 % на security-задачах CyberGym против 17,9–22 % у фронтир-моделей, а LoRA на детекции уязвимостей — «calibration without comprehension» (52,1 % = +2,1 п.п. над случайным). У нас 9 ходов и 2 успешные траектории — обучать не на чем; 77 % траекторий — примеры того, что закреплять нельзя. Сначала R1–R9 (промпты/тулы/лимиты), потом сбор ≥ 500 верифицированных батареей траекторий, потом QLoRA-пилот на qwen 27B (26 GB VRAM по таблице Unsloth) с метриками «дубли, токены/Находку, валидность JSON, битые URL» — §3.6, R13–R15.

---

## 2. Блок А — что показывают наши логи и БД

### 2.1 Данные

- `logs/info.jsonl` — 17 279 строк, из них с `trace_id` и `instance_id` — 24 хода с LLM-вызовами: 9 по Событиям и 15 чатов. Чаты (1–4 LLM-вызова, ≤ 61 k токенов, один с 5 делегациями) ниже не считаются, кроме оговорённых мест. Скрипт: `scratchpad/analyze_turns.py` (не в репо).
- Модели: `deepseek-v4-flash` (API) и `qwen3.8-27b-uncensored` (локальный сервер `192.168.242.74:8080`). Модель хода определена по `HTTP Request: POST …/chat/completions` внутри `trace_id`.
- БД hub: 26 Находок, 3 Отчёта, 1 055 записей `hub.activity`.

### 2.2 Ходы по Событиям

| trace | инст/событие | модель | LLM-вызовов (Лид/Саб) | Сабагентов | тул-вызовов | токены in / out | `report_finding` | дубли вызовов | исход |
|---|---|---|---|---|---|---|---|---|---|
| `1492b95e` | 17/19 | deepseek | 44 (6/38) | 4 | 112 | 759 k / 39 k | 0 | 30 (27 %) | cancelled (stop) |
| `9385d6de` | 21/22 | deepseek | 9 (9/0) | 0 | 11 | 99 k / 4,8 k | 0 + `write_report` | 0 | **processed** |
| `7ab11450` | 1/2 `full_scan` | deepseek | 181 (8/173) | 14 | 381 | **8 830 k / 154 k** | 8 | 50 (13 %) | run_failed: 402 Insufficient Balance |
| `520430a1` | 5/4 | deepseek | 5 (5/0) | 0 | 6 | 53 k / 2 k | 0 | 0 | cancelled |
| `b89a516f` | 7/5 `manual` | qwen | 8 (8/0) | 0 | 7 | 82 k / 2,4 k | 0 + `write_report` | 0 | **processed** |
| `5ea99a68` | 7/6 `manual`, 4 попытки | qwen | 87 (11/76) | 10 | 215 | 1 692 k / 58 k | 18 | 82 (38 %) | 3× run_failed (stop; `OperationalError`; 500 JSON parse), Отчёт записан на 4-й попытке, ход продолжался ещё час и остановлен |
| `b5c455f4` | 23/13 | qwen | 9 (5/4) | 4 | 37 | 83 k / 5 k | 0 | 1 | cancelled |
| `e933526b` | 35/21 | qwen | 13 (4/9) | 12 (6 дублей) | 49 | 106 k / 7 k | 0 | 10 | cancelled |
| `0c341c8f` | 35/22 | qwen | 1 | 0 | 2 | 18 k / 0,3 k | 0 | 0 | без исхода |
| **Итого** | | | 357 | **44** | **820** | **11 721 k / 272 k** | **26** | **173 (21 %)** | 2 processed / 5 cancelled / 2 failed |

Стоимостной срез: `7ab11450` — 8,83 M входных токенов на 8 Находок = **1,1 M токенов на Находку**, причём все 8 из одного Сабагента (deps/CVE), остальные 13 запусков дали ноль. `5ea99a68` — 94 k токенов/Находку. Соотношение input : output = 43 : 1 в среднем (Manus репортит ~100 : 1 как норму для агентов, но там KV-кэш; у нас `SubagentTokenCollector` кэш-хиты не считает вовсе).

### 2.3 Распределение вызовов по тулам

| агент | `task` | `sandbox_run` | `read_file` | `list_dir` | `grep_code` | `git_diff` | `load_skill` | `report_finding` | `web_search` | `write_report` |
|---|---|---|---|---|---|---|---|---|---|---|
| Лид (125) | 44 | 32 | 26 | 14 | 0 | 7 | 0 | 0 | 0 | 2 |
| Сабагенты (695) | — | 65 | **389** | 81 | 89 | 0 | 37 | 26 | 5 | 3 |

- Лид **сам** делает 26 `read_file` и 14 `list_dir` (в `b5c455f4` — 11 чтений подряд), хотя промпт запрещает ему аудит; `grep_code` Лид не вызвал ни разу.
- `git_diff` — 7 вызовов, все Лидом; ни один Сабагент не смотрел диф События: scope хода до детей не доходит.
- Разведка (`list_dir`+`read_file`) : поиск (`grep`/`diff`/`blame`) = **510 : 96**. В `1492b95e` — 65 : 0, в `5ea99a68` — 148 : 21.
- Анализаторы: в `7ab11450` один Сабагент проверил `command -v semgrep bandit …`, написал три python-скрипта к `api.osv.dev` в `/tmp` и один раз запустил `semgrep --config p/owasp-top-ten` — это и есть единственный Сабагент с Находками. Остальные 43 запуска анализаторами не пользовались (→ пред. отчёт §2.4).

### 2.4 Повторы и бесполезные цепочки (примеры из логов)

1. **Один файл — восемь раз.** `5ea99a68`, Сабагенты: `read_file('/repo/app/routes/profile.js')` ×8, `session.js` ×7, `index.js` ×6, `profile-dao.js` ×6, `allocations.js` ×6, `contributions.js` ×6 — 119 `read_file` на 45 уникальных путей; только 11 вызовов с `offset` (постраничность не используется). `list_dir('/repo', depth=2)` ×4 — каждый Сабагент строит карту заново.
2. **Делегация в никуда ×6, потом ещё ×6.** `e933526b` (qwen): в 07:54:20 Лид выпускает 6 `task` с `subagent_type='general'` → все за 5 мс возвращают `Task Failed. Unknown subagent type 'general'`; в 07:56:18 те же 6 промптов повторно. 12 тул-вызовов и 2 LLM-вызова по 86 с ушли на опечатку (починено в `b71ea71` резолвером имени — но это симптом «выдуманного типа», см. Б-5).
3. **Вторая волна после банкротства.** `7ab11450`: после первой волны (6 Сабагентов, 143–314 с, 5 из 6 без Находок) Лид тратит 45 с LLM-вызов на 5,9 k выходных токенов промптов и выпускает **8 новых** Сабагентов; все 8 умирают за 8–13 с с `402 Insufficient Balance`. Никакого гейта «а есть ли бюджет/смысл продолжать» между волнами нет.
4. **Turn-cap без результата.** Та же первая волна: `call_02`, `call_03`, `call_00`, `call_04` — `Task Failed (capped: turn budget). Reached max_turns=50`, 0 Находок, 0 текста; `call_01` — `Task Succeeded (capped)` с телом «Analysis is complete. Every SQL sink and exec site in scope has been traced. Writing the final report.» — отчёт так и не написан. ≈ 25 LLM-шагов × ~45 k входа каждый (p50 входа Сабагента в этом ходе — 44 k, максимум 134 k) выброшены.
5. **Справка, оплаченная 25 раз.** `load_skill(['xss'])` ×3 в одном ходе, `load_skill` 12 раз в `7ab11450` по 29–36 k символов: каждый последующий LLM-вызов этого Сабагента несёт ≈ 9 k токенов справки; 13 из 380 тул-ответов > 20 k символов.
6. **Широкий grep до потолка.** `5ea99a68`: `grep_code(pattern='crypto', glob='**/*.js', path='/repo')` и ещё два — по 50 016 символов, то есть срезаны `SANDBOX_OUTPUT_MAX_CHARS`; в контекст ушло ~12 k токенов мусора (включая `node_modules`) на один запрос.
7. **Лид «быстрая карта» = 7 LLM-вызовов.** `7ab11450`: до первого `task` Лид сделал 6 `sandbox_run` + 5 `read_file` + 3 `list_dir` (34 k входа на последнем шаге), в том числе `find … | xargs grep -ln 'http\.\|ServeHTTP'` — а потом Сабагенты повторили `list_dir('/repo/backend', depth=3)` ×3.

### 2.5 Сабагенты: сколько и чем закончились

| ход | запусков | завершились с Находками | без Находок | причины «без Находок» |
|---|---|---|---|---|
| `1492b95e` | 4 | 0 | 4 | ход остановлен пользователем (Сабагенты не успели) |
| `7ab11450` | 14 | 1 (8 Находок) | 13 | 4 `max_turns=50`, 1 capped без отчёта, 8 × HTTP 402 |
| `5ea99a68` | 10 | ≤ 10 (18 Находок, 4 `task_finished`) | ≥ 0 | остальные — 3 падения хода |
| `b5c455f4` | 4 | 0 | 4 | остановлен |
| `e933526b` | 12 | 0 | 12 | 6 × неверный тип, 6 × остановлен |
| **итого** | **44** | **≤ 10** | **≥ 34 (77 %)** | |

Плюс 349 предупреждений `delegation limit applied` в `warning.jsonl` (`SubagentLimitMiddleware` вырезает лишние `task` из одного сообщения — модель регулярно просит больше `maxSubagents=3`) и 108 `receipt stamping failed`.

### 2.6 Токены и латентность LLM-вызовов

| модель | ходов | медиана вызова | p90 | максимум | медиана входа Сабагента |
|---|---|---|---|---|---|
| deepseek-v4-flash | 4 | 2,8–5,0 с | ~20 с | 52 с | 44 k (макс. 134 k) |
| qwen3.8-27b (локально) | 5 | **36–147 с** | 396 с | **1 656 с** (27,6 мин) | 17,5 k (макс. 50 k) |

Для локальной модели вход 17–50 k токенов на каждом шаге ReAct-цикла (промпт Лида + каталог скиллов + справки + сырые файлы) — это prefill-доминируемая нагрузка; при 76 вызовах Сабагентов ход `5ea99a68` длился 5 часов (04:34 → 09:33).

### 2.7 Падения и остановки

Исходы `event handled` по всему логу (включая тесты): processed 255, dropped 132, cancelled 65, forwarded 64, skipped_no_commit 55, duplicate 34. Среди 9 реальных ходов по Событиям: 5 остановлены пользователем (`turn cancelled by stop`) — все пять с Сабагентами; `run_failed` из `hub.activity`: `402 Insufficient Balance` (×2, deepseek), `OpenAIAPIError 500 Failed to parse tool call arguments as JSON … missing closing quote` (×3, qwen, события 6/9/10 — обрезанный JSON аргументов), `OperationalError: cannot enter pipeline mode, connection not idle` (×1, psycopg под отменой), `SandboxNotProvisionedError` (×2), `ConnectionError` к локальной модели (×1). Общие счётчики `warning.jsonl`: `loop_detection HARD STOP` 159, `token_budget HARD STOP` 107, `terminal_response empty final` 159 — в основном из тестов, но механизмы те же, что срабатывают в проде.

### 2.8 Битые ссылки

Собрано 51 URL из `hub.findings.references` (jsonb) и `hub.reports.structured`; 3 из них — не ссылки, а плейсхолдеры в evidence (`127.0.0.1:PORT`, `169.254.169.256`, `attacker.tld`). Из 48 реальных: **37 → 200, 11 → 404 (23 %)**. Для «200» на SPA (NVD, OSV, go.dev) проверено содержимое: все 7 GHSA/GO-идентификаторов и 5 CVE-2026-* подтверждены `api.osv.dev` (CVE-2026-56855 и CVE-2026-78662 — алиасы GO-2026-6355/6354). В `hub.reports.summary` URL нет.

| источник ссылки | URL | битых | доля |
|---|---|---|---|
| Сабагент deepseek, Находки 1–8 (deps; URL взяты из ответа `api.osv.dev`/GHSA, полученного `sandbox_run`) | 20 | 0 | **0 %** |
| Сабагенты qwen, Находки 9–26 (URL «по памяти»: `web_search` вызывался 3 раза и только по CVE) | 28 | 11 | **39 %** |

Паттерны выдуманных ссылок: (а) правдоподобные OWASP-слаги — `www-community/attacks/NoSQL_Injection`, `…/Open_Redirect_Vulnerability`, `…/Server_Side_JavaScript_Injection`, `…/Server_Side_Request_Forgery_(SSRF)` (реальная страница — без суффикса), `www-community/Secure_Design/Secret_Management`, `www-community/Session_management#…`; (б) неверный формат Top 10 — `Top10/A1-2021-Broken_Access_Control/` вместо `A01_2021`; (в) несуществующие cheat sheets — `MongoDB_Security_Cheatsheet.html` (есть `NoSQL_Security_Cheat_Sheet`); (г) нерелевантный «референс» — `github.com/nodejs/node/blob/master/deps/uv/include/uv/uv.h` для eval-инъекции; (д) устаревшие докс-якоря — `paularmstrong.github.io/swig.js/#autoescaping`. Ссылки на `cwe.mitre.org/data/definitions/N.html` живые все (шаблон детерминирован) — это подсказка для решения (§4, R8).

---

## 3. Блок Б — первичные источники по пяти темам

### 3.1 Когда мульти-агент/Сабагенты вредят

**Источники.**
- Cognition, «Don't Build Multi-Agents» (2025): два принципа — «Share context, and share full agent traces, not just individual messages» и «Actions carry implicit decisions, and conflicting decisions carry bad results»; параллельные Сабагенты в примере Flappy Bird «cannot see what the other was doing and so their work ends up being inconsistent»; рекомендация — «single-threaded linear agent», для длинных задач — отдельная модель, «whose key purpose is to compress a history of actions & conversation into key details»; про Claude Code: Сабагенты «only answer questions», потому что «the subtask agent lacks context from the main agent».
- Anthropic, «How we built our multi-agent research system» (2025): «agents typically use about 4× more tokens than chat interactions, and multi-agent systems use about 15× more tokens than chats»; токены объясняют 80 % дисперсии на BrowseComp; правило «scale effort to query complexity»: «Simple fact-finding: 1 agent with 3–10 tool calls; Direct comparisons: 2–4 subagents with 10–15 calls each; Complex research: more than 10 subagents»; не подходит там, где «most coding tasks involve fewer truly parallelizable tasks than research» и где «all agents [need to] share the same context»; ранние отказы — «spawning 50 subagents for simple queries, scouring the web endlessly for nonexistent sources».
- Kim et al., «Towards a Science of Scaling Agent Systems» (arXiv 2512.08296, 260 конфигураций, 5 архитектур, 3 семейства моделей): «Relative performance change compared to single-agent baseline ranges from +80.8% on decomposable financial reasoning to −70.0% on sequential planning»; «tool-heavy tasks appear to incur multi-agent overhead»; «robust capability-saturation effect»; «architectures without centralized verification tend to propagate errors more than those with centralized coordination»; предиктивная модель угадывает лучшую архитектуру в 87 % held-out конфигураций.
- Cemri et al., «Why Do Multi-Agent LLM Systems Fail?» (MAST, arXiv 2503.13657, 1 600+ трасс, 7 фреймворков, κ = 0,88): 14 режимов отказа; самые частые — FM-1.3 Step repetition 15,7 %, FM-2.6 Reasoning-action mismatch 13,2 %, FM-1.5 Unaware of stopping conditions 12,4 %, FM-1.1 Disobey task specification 11,8 %, FM-3.3 Incorrect verification 9,1 %, FM-3.2 No/incomplete verification 8,2 %; вмешательство «high-level task objective verification» дало +15,6 % на ChatDev без смены модели.

**Что у нас.** `LEAD_SYSTEM_PROMPT` (`core/lead/graph.py`) — «ROOT ORCHESTRATOR, not a hands-on auditor … Even "just a quick look" at a suspicious file is not your role: delegate it» и чек-лист из 8 классов «delegate every relevant one to its own subagent» — вне зависимости от типа События и размера диапазона. Докстринг `task` (`core/tools/delegation/task.py`) говорит обратное («Do NOT delegate merely because a task is complex»), т. е. модель получает два противоречащих указания. Сабагент (`core/subagents/registry.py`) получает только текст `prompt` — ни карты репо, ни диапазона коммитов, ни списка уже прочитанных файлов; результат — self-report, который Лид «не обязан принимать на веру», но проверять ему нечем, кроме квитанций.

**Чего не хватает.** Правила масштабирования по сложности (Anthropic) — для `push`/`pull_request` с диапазоном в десятки файлов декомпозиция по 8 классам заведомо «mismatched coordination» (Kim et al.). Разделения по *поверхностям* (файлы/директории), а не по классам — сейчас 6 Сабагентов читают одни и те же `routes/*.js` под разными шляпами (Injection, XSS, Authn…) — это и есть 8× `read_file`. Центральной верификации результатов Сабагентов (Kim et al., MAST FM-3.x) — Лид не имеет инструмента проверить Находку кроме повторного чтения (которое ему запрещено промптом).

### 3.2 «Overthinking», лишние действия и «когда остановиться»

**Источники.**
- Cuadron et al., «The Danger of Overthinking: Examining the Reasoning-Action Dilemma in Agentic Tasks» (arXiv 2502.08235, 4 018 траекторий SWE-bench): три паттерна — Analysis Paralysis, Rogue Actions, Premature Disengagement; «Selecting the solution with the lower overthinking score, can improve model performance by almost 30% while reducing computational costs by 43%»; «reasoning models exhibiting stronger tendencies toward overthinking compared to non-reasoning models»; лечение — «leveraging native function-calling capabilities and selective reinforcement learning».
- Qian et al., «SMART: Self-Aware Agent for Tool Overuse Mitigation» (arXiv 2502.11435, ACL 2025 Findings): «Tool Overuse, where models unnecessarily rely on external tools for tasks solvable with parametric knowledge»; −24 % использования тулов при +37 % качества; на OOD-наборах — та же точность при 1/5 тул-вызовов; 7B-модели догоняют 70B и GPT-4o.
- «Scores Are Not Decisions: Cost-Aware Stopping for Tool Acquisition in LLM Agents» (arXiv 2607.27083): «acquiring too few tools leaves the task under-informed, while too many adds cost, context load, and privacy exposure»; CAM-DF — «lightweight pre-execution plugin», «exposes the agent to 37% fewer tools than full access while maintaining comparable task success».
- Anthropic, «Task budgets» (документация): «Task budgets let you tell Claude how many tokens it has for a full agentic loop … The model sees a running countdown and uses it to prioritize work and finish gracefully»; «soft hint, not a hard cap»; «A budget that is too small for the task can cause refusal-like behavior»; правило — измерить p99 реального расхода и от него отталкиваться. (Только Claude API; для deepseek/qwen — как паттерн для собственной middleware.)
- MAST: «Unaware of stopping conditions» 12,4 %, «Premature termination» 6,2 %.

**Что у нас.** `LoopDetectionMiddleware` (`core/middleware/loop_detection.py`, окно 20, hard stop по идентичным вызовам/частоте тула) и `TokenBudgetMiddleware` (`core/middleware/token_budget.py`, дефолт 1 M, warn 80 %) — оба реагируют *после* факта; `SubagentConfig.max_turns=50` — рекурсивный лимит LangGraph без «грациозного финиша» (см. §2.4-4); `PERSISTENCE: do not stop at surface checks — continue until…` в промпте Лида толкает в сторону Analysis Paralysis. Нет ни бюджета действий на Сабагента, ни обратного отсчёта, видимого модели, ни «прочитанного» кэша.

**Чего не хватает.** Видимый модели счётчик («осталось N тул-вызовов / M токенов, при 0 — пиши отчёт по тому, что есть») вместо молчаливого `GraphRecursionError`; правило Anthropic 3–10 вызовов для простого scope как *дефолт*, а не «persistence»; отбор по «overthinking score» на evals (Cuadron: дешёвый прокси — доля шагов без нового инструмента/файла).

### 3.3 Дизайн интерфейса агента и тулов

**Источники.**
- Yang et al., SWE-agent (arXiv 2405.15793): Agent-Computer Interface — «interface design affects the performance of language model agents»; ACI «significantly enhances an agent's ability to create and edit code files, navigate entire repositories»; pass@1 12,5 % на SWE-bench (2024).
- mini-SWE-agent (репозиторий): «Does not have any tools other than bash — it doesn't even need to use the tool-calling interface of the LMs»; «Has a completely linear history — every step of the agent just appends to the messages»; «Scores >74% on the SWE-bench verified benchmark»; «Instead of implementing custom tools for every specific thing the agent might want to do, the focus is fully on the LM utilizing the shell to its full potential».
- OpenHands (arXiv 2407.16741): действия `CmdRunAction`/`IPythonRunCellAction`/`BrowserInteractiveAction` в песочнице; «the event stream, which is a chronological collection of past actions and observations»; делегирование — `AgentDelegateAction` только для узких специализаций (BrowsingAgent).
- Anthropic, «Writing tools for agents»: «a few thoughtful tools targeting specific high-impact workflows», «tools can consolidate functionality»; «return only high signal information»; `response_format: concise | detailed` (72 vs 206 токенов); Claude Code «restricts responses to 25,000 tokens by default» с подсказкой сузить запрос; «Even small refinements to tool descriptions can yield dramatic improvements».
- Anthropic, «Building effective agents»: «find the simplest solution possible, and only increasing complexity when needed»; orchestrator-workers — когда «subtasks cannot be predetermined»; агенты — «higher costs, and the potential for compounding errors»; на SWE-bench «invested more effort optimizing tools than the overall prompt» (абсолютные пути вместо относительных).
- Claude Code, «Subagents» (документация): использовать, когда «a side task would flood your main conversation with search results, logs, or file contents you won't reference again»; главный разговор — когда «Multiple phases share significant context», «Latency matters. A subagent that isn't a fork starts fresh and may need time to gather context»; встроенный Explore — «read-only tools; Write and Edit are denied».
- Deep Agents (LangChain, документация): «an opt-in `write_todos` tool for structured task tracking»; файловая система — «Persistent storage in the virtual filesystem carries information across threads»; Сабагенты — «Heavy subtask work stays isolated and is compressed into a compact result», для «isolated, long-running, multi-step, or parallel tasks».
- Chroma, «Context Rot» (18 моделей): «model performance varies significantly as input length changes, even on simple tasks»; один дистрактор уже роняет качество, эффект «amplifies as input length grows»; «models perform better on shuffled haystacks than on logically structured ones»; «what matters more is how that information is presented».
- Manus, «Context Engineering for AI Agents»: «KV-cache hit rate is the single most important metric for a production-stage AI agent» (0,30 vs 3 USD/MTok — 10×); «average input-to-output token ratio is around 100:1»; «avoid dynamically adding or removing tools mid-iteration» — маскировать логиты; «file system as the ultimate context»; `todo.md`, который агент «update[s] step-by-step» — рецитация против lost-in-the-middle; «leave the wrong turns in the context»; ≈ 50 тул-вызовов на задачу.

**Что у нас.** 8 сэндбокс-тулов + `load_skill` + `report_finding` + `write_report` + `task` + deferred MCP; `read_file` постраничный, но Сабагенты читают без `offset` (11 из 119 с offset); `grep_code` без исключения `node_modules`/vendor и с потолком 50 k символов (`SANDBOX_OUTPUT_MAX_CHARS`) — против 25 k токенов у Claude Code; `load_skill` возвращает 29–36 k символов и не дедуплицируется; каталог скиллов вклеен в системный промпт Лида; между ходами ничего не переживает, кроме чекпоинта (→ пред. отчёт §2.3 про заметки/threat model); todo-списка нет; кэш промпта не измеряется. Хорошее: `ToolResultSanitizationMiddleware`, квитанции, `git_diff(stat=true)` как старт scope.

**Чего не хватает.** Меньше тулов и «толще» каждый (Anthropic, mini-SWE-agent): `read_file` с дедупом «уже читал (см. вызов #N)», `grep_code` с дефолтным `--glob '!node_modules'` и `concise`-режимом (имя файла:строка), `load_skill` как одноразовая вставка с идемпотентностью; todo/план в состоянии (Deep Agents, Manus); стабильный префикс промпта для KV-кэша (у нас `mcp_section`/каталог скиллов внутри системного промпта — стабильны, но `HumanMessage` задания и скиллы — нет).

### 3.4 Галлюцинированные ссылки и grounding

**Источники.**
- «LLM hallucinations in the wild: Large-scale evidence from non-existent citations» (arXiv 2605.07723): «111 million references across 2.5 million papers in arXiv, bioRxiv, SSRN, and PubMed Central»; консервативно «146,932 hallucinated citations in 2025 alone»; «a sharp rise in non-existent references following widespread LLM adoption».
- «Detecting and Correcting Reference Hallucinations in Commercial LLMs and Deep Research Agents» (arXiv 2604.03173): «3–13% hallucinated URLs», «5–18% non-resolving overall across 10 models»; на ExpertQA 8,22 % non-resolving из 168 021 URL; различает *stale* (ушедшие) и *hallucinated* (без записи в Wayback); инструмент `urlhealth` (HEAD + Wayback → LIVE/DEAD/LIKELY_HALLUCINATED); агентная самокоррекция — «6–79× reduction», < 1 % после исправления; рекомендация — «programmatic URL verification as a standard post-generation step».
- Anthropic, Citations API: «Ground Claude's responses in your source documents. Citations return the exact passages that support each claim, so you can verify answers» — цитаты привязаны к позициям переданных документов, а не к URL из памяти.
- Anthropic, Claude Code Security: «Claude re-examines each result, attempting to prove or disprove its own findings and filter out false positives»; «Claude also provides a confidence rating for each finding» — о ссылках-референсах не говорится ничего.
- Semgrep, rule syntax: `metadata:` — «Provide additional information for a rule with the `metadata:` key, such as a related CWE, likelihood, or OWASP» — референсы курируются автором правила, а не генерируются в момент срабатывания.
- OpenAI Aardvark — страница `openai.com/index/introducing-aardvark/` недоступна для fetch (403); по индексу поиска: валидация «in an isolated, sandboxed environment», 92 % recall на «golden» репо (→ пред. отчёт §2.2, где источник читался).

**Что у нас.** `report_finding.references: list[str]` (`core/tools/security/report_finding.py`) — свободный список URL, не проверяется ни при записи (`core/tools/security/hub.py`), ни при рендере Отчёта; промпт Сабагента прямо просит «references (URLs)», промпт Лида — «references (advisory/CWE/doc URLs)». `browse`/`web_search` есть, но не увязаны с `references`: модель может сослаться на страницу, которую не открывала. Итог §2.8: 0 % битых там, где URL пришёл из вывода тула, 39 % — где из памяти.

**Чего не хватает.** Правила «цитировать только то, что вернул тул» (`web_search`/`browse`/`sandbox_run` к OSV) и детерминированных ссылок из идентификаторов (`cwe` → `cwe.mitre.org/data/definitions/<N>.html`, `cve`/GHSA → `osv.dev/vulnerability/<ID>`), программной проверки (HEAD + для OSV/NVD — API) до персиста с пометкой `unverified`/удалением.

### 3.5 Выбор модели и режимов

**Источники.**
- Anthropic, «Effort»: «The effort parameter affects all tokens in the response, including … Tool calls and function arguments»; «Lower effort also means fewer and terser tool calls»; на низком effort модель «Combine[s] multiple operations into fewer tool calls, Make[s] fewer tool calls»; `low` — «Simpler tasks that need the best speed and lowest costs, such as subagents»; менять effort внутри кэшированного диалога — ломает кэш. (У deepseek/qwen такого параметра нет; аналог — отключаемый thinking и промпт-бюджет.)
- Belcak et al., «Small Language Models are the Future of Agentic AI» (arXiv 2506.02153, NVIDIA): «SLMs are sufficiently powerful, inherently more suitable, and necessarily more economical for many invocations in agentic systems»; агентные задачи — «a small number of specialized tasks repetitively and with little variation»; гетерогенные системы (большая модель для разговорной части).
- SMART (см. 3.2): 7B c обучением на «когда тул не нужен» = 70B/GPT-4o.
- Cuadron et al.: reasoning-модели overthink'ают сильнее не-reasoning.
- Локальные Qwen и tool-calling: vLLM #21026 — Qwen3-32B с `tool_choice="required"` «continues to choose to call the same tool again, resulting in an infinite loop» (LangChain 0.3.25, vLLM 0.9.2, без резолюции); Ollama #14570 — «qwen3 tool call parsing failed … failed to parse JSON: unexpected end of JSON input» при упоре в `num_predict`/контекст, ожидаемое поведение — вернуть `done_reason: "length"`; PR #14835 в работе.

**Что у нас.** Две Сборки: `deepseek-v4-flash` и `qwen3.8-27b-uncensored`. На qwen наблюдаемые сбои совпадают с вышеописанными один в один: `500 Failed to parse tool call arguments as JSON … missing closing quote` ×3 (обрезка аргументов — судя по `column 1356`, длинный `prompt` для `task` или `evidence` для `report_finding`), выдуманный `subagent_type='general'` ×6, медиана LLM-вызова 36–147 с при 17–50 k входа. При этом ход `b89a516f` на qwen **без Сабагентов** прошёл за 8 вызовов и записал Отчёт. Параметров `params` в `hub.llm_connections` под thinking/temperature/`max_tokens` ход не использует осознанно.

**Чего не хватает.** Разных режимов для Лида и Сабагента (большая модель координирует, малая — исполняет узкие проверки — NVIDIA/SMART/Anthropic `low` для Сабагентов); на локальной модели — короткие аргументы тулов (передавать Сабагенту scope как список путей, а не абзац), `max_tokens` достаточный для JSON аргументов и обработка `finish_reason=length` как «повтори короче», а не 500; отключение делегирования по умолчанию для моделей без надёжного tool-calling (`limits.subagent=false` в Сборке).

### 3.6 Дообучение модели под агента

Вопрос пользователя: можно ли дообучить локальную qwen3 27B (llama.cpp, окно 262 k) и/или использовать DeepSeek как учителя, чтобы агент делал меньше бесполезных действий и не выдумывал ссылки.

**(1) SFT на траекториях агентов — что даёт для 7–32B.**

| работа | данные | ученик | результат на SWE-bench Verified |
|---|---|---|---|
| SWE-Gym (arXiv 2412.21139, ICML 2025) | 2 438 задач с исполняемыми окружениями; траектории OpenHands | Qwen2.5-Coder 7B/32B | «up to 19% absolute gains»; 32,0 % с верификатором на сэмплированных траекториях |
| OpenHands LM 32B (блог OpenHands) | траектории, «generated by OpenHands itself» на SWE-Gym | Qwen2.5-Coder-Instruct-32B | 37,2 %; «can be run locally on … a single 3090 GPU»; ограничения — «repetitive steps», «sensitivity to quantization» |
| SWE-smith (arXiv 2504.21798) | 50 k задач из 128 репо; **5 016 траекторий Claude 3.7 Sonnet**, rejection sampling: только решённые, ≤ 3 траектории на задачу | Qwen2.5-Coder-32B → SWE-agent-LM-32B | **40,2 %**; «easier instances … degraded model performance»; рост ~логарифмический от числа репозиториев |
| R2E-Gym (arXiv 2504.07164) | 8,7 k задач (SYNGEN: back-translation из коммитов) | 32B | 34,4 % SFT-only; 51 % с гибридными верификаторами |
| Skywork-SWE (arXiv 2506.19290) | 10 169 задач, > 8 000 runtime-валидированных траекторий | Qwen2.5-Coder-32B (OpenHands) | 38,0 % (47,0 % с TTS); «continues to improve as the data size increases, showing no signs of saturation» |
| Kimi-Dev (arXiv 2509.23045) | agentless-RL как «skill prior», затем SFT на **5 000 публичных траекторий** | — | 48,6 % pass@1 агентно (60,4 % agentless) |
| Nemotron-SWE-v1 (HF, NVIDIA) | **59 k траекторий OpenHands**, учитель Qwen3-Coder-480B-A35B, задачи из SWE-Gym/R2E-Gym; CC BY 4.0 | — | на карточке датасета метрик нет (цифра «Pass@1 49,9» из поискового индекса — первичным источником не подтверждена) |
| Nemotron-Agentic-v1 (HF, NVIDIA) | 335 122 синтетических tool-calling траекторий (316 k tool calling + 19 k interactive), учителя Qwen3-235B/GPT-OSS-120B; CC BY 4.0 | — | метрик на карточке нет |

Общий вывод: для моделей 7–32B рабочий рецепт — **~5 k отфильтрованных по успеху траекторий сильного учителя → +10–20 п.п.**; все цифры — про «починить issue с тестами», а не «найти уязвимость», и фильтр успеха везде — исполняемые тесты.

**(2) RL для tool-use — единственный метод, который напрямую учит «меньше и точнее действий».**
- ToolRL (arXiv 2504.13958): GRPO с наградой за формат и корректность вызова; «+17% improvement over baseline models, +15% over supervised fine-tuning»; SFT «struggles with unfamiliar or complex tool scenarios»; эффект — «fewer and more proactive tool invocations»; модели Qwen2.5 1.5B/3B/7B, Llama.
- ReTool (arXiv 2504.11536): Qwen2.5-32B, 67 % AIME за **400 RL-шагов** против 40 % за 1 080 шагов у текстового RL; появляется самокоррекция и «когда вызывать код».
- Qwen3-Coder (блог Qwen): «long-horizon RL (Agent RL)», «scalable system capable of running 20,000 independent environments in parallel»; SOTA среди open-weights на SWE-bench Verified без TTS.
- DeepSeek-V3.2 (arXiv 2512.02556): «synthesis pipeline that systematically generates training data at scale» для tool-use, «scalable agentic post-training».
- Agent-R1 (arXiv 2511.14460): «each interaction step as the basic reinforcement-learning transition» — фреймворк, чисел в абстракте нет; SINKFLEX-RL (arXiv 2608.10357): long-horizon RL требует 22–28 GB VRAM уже на 4 k токенов контекста для малых моделей, reward 0,25 → 0,44 на τ²-bench.
- Это же говорят Cuadron et al. (3.2): overthinking лечится «native function-calling capabilities and selective reinforcement learning».

Вывод: RL — правильный инструмент против лишних действий, но требует **верифицируемой награды и тысяч окружений**; в security у нас нет ни того, ни другого (верификатор — → пред. отчёт §2.2).

**(3) Дистилляция: сильный учитель → rejection sampling → SFT ученика.** Практика во всех работах выше одинакова: учитель (Claude 3.7 Sonnet у SWE-smith, Qwen3-Coder-480B у Nemotron, OpenHands-с-сильной-моделью у SWE-Gym) прогоняется на задачах с *проверяемым* исходом, оставляются только успешные траектории (SWE-smith дополнительно режет «лёгкие» и ограничивает 3 траектории/задача — иначе качество падает), ученик учится на `messages` с `tool_calls` (loss только на ходах ассистента). Порядок данных — 5 k траекторий (SWE-smith, Kimi-Dev) при 10–50 задач-репозиториях; больше репозиториев важнее, чем больше траекторий на репо.

**(4) Специфика security — предупреждения.**
- CyberGym (arXiv 2506.02548, 1 507 уязвимостей, 188 проектов): **SWE-дообученные модели (SWE-Gym, R2E-Gym, OpenHands-LM) — ≤ 2,0 %** на воспроизведении уязвимости против Claude-Sonnet-4 17,9 % и GPT-5 (thinking) 22,0 %; контаминация статистически не значима (p > 0,1 между до/после cutoff); типовые провалы — «exhausting iteration limits», «overwhelming the context window»; авторы бенчмарк для обучения не используют.
- SEC-bench (arXiv 2506.11791): ≤ 18,0 % PoC, ≤ 34,0 % патчей; датасет собирается за «$0.87 per instance» — потенциальный источник *окружений* для RL, но обученных моделей нет.
- VulnGym (arXiv 2608.02001): 184 advisories / 408 записей / 23 репо, только оценка.
- «Calibration Without Comprehension» (arXiv 2606.20502): 834 сэмпла ядра Linux, 74 CWE, 8 моделей, **15 LoRA-вариантов**, строгий temporal split: «fine-tuning shifts the output threshold without changing the decision policy»; лучшая точность 52,1 % (+2,1 п.п. над случайным), top-1 классификация CWE < 1,3 %; контаминация «provides no measurable advantage».
- Data-centric exploit generation (arXiv 2606.15123): Qwen3-8B QLoRA на 4 500 CVE / 126 CWE — RCE 6,58 → 9,38, но path traversal **13,53 → 10,18**: «does not yet generalize uniformly across different vulnerability types».

Вывод: свидетельств, что SFT/LoRA учит модель *находить* уязвимости, нет; есть обратные. Дообучение имеет смысл только для **поведения агента** (валидный tool-call, дисциплина действий, формат Отчёта, ссылки только из тулов), и оценивать его надо на *временно́м* сплите Батареи, а не на тех же репо.

**(5) Практическая стоимость и инструменты.**
- QLoRA (arXiv 2305.14314): «finetune a 65B parameter model on a single 48GB GPU while preserving full 16-bit finetuning task performance»; Guanaco — «24 hours of finetuning on a single GPU».
- Unsloth, таблица требований: **32B QLoRA 4-bit — 26 GB VRAM, LoRA 16-bit — 76 GB**; 14B — 8,5 / 33 GB; «2x faster, 70% less VRAM»; для reasoning-моделей Qwen3 — микс «75% reasoning and 25% non-reasoning», иначе теряется thinking. Для 27B dense ожидать ~22–26 GB на QLoRA при коротких последовательностях; наши LLM-вызовы — 17–50 k токенов входа, и память растёт с длиной (gradient checkpointing, packing) — реалистично одна карта 48–80 GB.
- TRL `SFTTrainer`: «fully supports fine-tuning models with tool calling» — `messages` с `tool_calls` и ролью `tool` + колонка `tools` (JSON-схемы); `assistant_only_loss=True` («For known model families (e.g. Qwen3), TRL automatically patches the template»); `max_length` по умолчанию 1024 — поднимать до 32 k+; `packing=True`; QLoRA через `quantization_config` + `peft_config`.
- LLaMA-Factory: «LoRA and 2/3/4/5/6/8-bit QLoRA», Qwen3 (MoE/Instruct/Thinking/Next), function-calling датасеты (Glaive) в sharegpt-формате; Axolotl — аналог (не проверялся).
- Формат Qwen: «Hermes-style tool use is recommended for Qwen3» — `<tool_call>{"name":…,"arguments":…}</tool_call>`, ответ ролью `tool`; сама документация: «The ultimate solution is fine-tuning using your own data».
- llama.cpp: в репозитории есть `convert_hf_to_gguf.py` и `convert_lora_to_gguf.py` — адаптер конвертируется в GGUF и подключается к серверу без пересборки базовой модели.

**Что у нас уже есть (данные).** `hub.activity` — полные траектории ходов: `tool_call` 291, `tool_result` 264, `node` 284, `text` 60, `task_started/report/finished/failed` 110, `chat_*` 12 (1 055 записей); чекпоинты LangGraph (`AsyncPostgresSaver`) — полные `messages` треда с `tool_calls`, т. е. уже TRL-совместимый формат после одного конвертера; `hub.findings` 26, `hub.reports` 3; `logs/info.jsonl` — токены/длительности на каждый вызов; `evals/data/repos.v1.jsonl` — Батарея с ручными Фактами (единственный честный фильтр успеха). Чего нет: ни одной траектории, помеченной «успех по Батарее»; 2 из 9 ходов завершились Отчётом; 77 % Сабагент-траекторий — негативные примеры.

**Итог для пользователя.**
1. *Стоит ли сейчас* — нет. Обучать не на чем (2 успешные single-agent траектории + 1 deps-Сабагент), а обучение на текущих — закрепит петли и `read_file`×8 (OpenHands LM даже после обучения на успешных выдаёт «repetitive steps»). Битые ссылки лечатся детерминированно (R8) — дообучение это не гарантирует. Security-«знание» LoRA не даёт (CyberGym ≤ 2 %, «calibration without comprehension»).
2. *Что дешевле сделать до любого дообучения* — R1–R9 из §4: убрать принудительное делегирование, бюджет действий, кэш чтений, тонкие `load_skill`/`grep_code`, references только из тулов. По Блоку А это снимает 21 % дублей, ~93 % токенов Сабагентов и 39 % битых URL без единого GPU-часа.
3. *Что собрать* — после R1–R9 и стабильного прогона: (а) траектории DeepSeek как учителя на Юнитах Батареи; (б) фильтр успеха: Отчёт записан, Факты Батареи подтверждены, 0 битых URL, дубли < 5 %, ≤ бюджета действий; (в) цель — **≥ 500 отфильтрованных траекторий на ≥ 20 репозиториях** (оценка: SWE-smith/Kimi-Dev работают с 5 k; для узкой цели «поведение» порядок сотен — гипотеза, проверяемая пилотом); temporal/repo-split для оценки.
4. *Минимальный пилот* — цель: не «находить лучше», а «делать меньше и валиднее»: QLoRA r = 16 на qwen3 27B (Unsloth/TRL, `assistant_only_loss`, `max_length` 32 k, 2 эпохи, 1 × 48–80 GB, порядок часов–суток по QLoRA/Guanaco), экспорт LoRA в GGUF → llama.cpp. Метрики до/после на held-out Юнитах: TP/FP Находок по Фактам, токены/Находку, доля дублей, `tool call parse` ошибки, битые URL, доля ходов с Отчётом. Стоп-критерий: если после R1–R9 базовый qwen уже укладывается в бюджет и даёт < 5 % дублей — пилот не нужен.
5. *Что не делать* — SFT «на уязвимости» (CVE-датасеты, отчёты сканеров) и обучение на текущих логах без фильтра.

---

## 4. Рекомендации

Явный ответ на главный вопрос. **Сабагенты нужны не как режим по умолчанию, а как опция для одного случая: `full_scan` большого репо с независимыми файловыми поверхностями.** Аргументы: (1) в наших данных оба успешных хода — single-agent, 77 % запусков Сабагентов бесплодны, 93 % токенов уходит детям; (2) Kim et al. — до −70 % на последовательных задачах и «tool-heavy tasks incur multi-agent overhead», Anthropic — 15× токенов, Cognition — «single-threaded linear agent»; (3) наш scope (диф коммита/PR) — по определению последовательная задача с общим контекстом. Режим: **single-agent Лид с todo и бюджетом действий** для `push`/`pull_request`/`merge_request`/`manual`; **делегирование только для `full_scan`, только по файлам/директориям, ≤ 3 параллельно, с картой репо на входе и центральной верификацией Лидом**.

| # | Что | Зачем (источник) | Где в коде | Размер | Риск |
|---|---|---|---|---|---|
| R1 | **Режим хода по типу События**: для `push`/`pull_request`/`manual` собирать Лида с `limits.subagent=False` (нет тула `task`) и промптом «hands-on reviewer»; для `full_scan` — оркестратор. | Наши §2.2 (2/2 успешных — без детей), Anthropic «scale effort to complexity», Kim et al. −70 % на sequential | `core/lead/graph.py::_lead_features`, `build_lead_profile`; `core/runner/executor.py::_event_prompt` уже знает тип | M | Низкий; для `full_scan` поведение не меняется |
| R2 | **Убрать противоречие промптов**: из `LEAD_SYSTEM_PROMPT` снять «Even "just a quick look"… delegate it» и чек-лист «delegate every relevant one to its own subagent»; оставить критерий из докстринга `task` (параллельно, независимо, контекст не нужен). Делить по *поверхностям* (файлы/пакеты), а не по классам. | MAST FM-1.1/1.3, Cognition (конфликт решений), наши 8× `read_file` одного файла | `core/lead/graph.py::LEAD_SYSTEM_PROMPT`, `core/tools/delegation/task.py` докстринг | S | Меньше «покрытия по чек-листу» — компенсируется todo (R3) |
| R3 | **Todo/план в состоянии Лида** (`write_todos`-подобный тул или секция в `HumanMessage`, которую Лид переписывает): список поверхностей scope → статус confirmed/ruled_out/open. Рецитация в конце контекста. | Manus `todo.md`, Deep Agents `write_todos`, Chroma (важно *как* подано) | новый тул в `core/tools/security/` или `core/middleware/`; персист в `hub.activity` | M | Локальные модели могут не поддерживать дисциплину — сделать обновление обязательным перед `write_report` |
| R4 | **Бюджет действий, видимый модели**: middleware, которая в каждый tool-result дописывает «tool calls left: N / tokens left: M»; при 0 — вырезать тул-вызовы и потребовать финальный ответ (как `LoopDetection`, но заранее). Дефолты: Сабагент 25 вызовов, Лид на `push` 30, `full_scan` 120. | Anthropic Task budgets («running countdown … finish gracefully»), 3–10 вызовов на простой запрос; наши capped-без-отчёта | новая `core/middleware/action_budget.py`, вешать в `core/agents/factory.py::build_agent`; заменить `GraphRecursionError`-ветку в `core/subagents/executor.py` | M | Слишком малый бюджет → «refusal-like behavior» (Anthropic) — калибровать по p99 из `turn summary` |
| R5 | **Грациозный финиш Сабагента**: за 2 шага до `max_turns` инжектить «пиши self-report по тому, что есть»; при `GraphRecursionError` без текста — один дополнительный LLM-вызов без тулов «summarize what you found». | §2.4-4 (5 из 6 capped без Находок), MAST FM-3.1 | `core/subagents/executor.py::arun`, `SubagentConfig.max_turns` | S | +1 вызов на кап; окупается мгновенно |
| R6 | **Кэш чтений и карта репо для детей**: (а) `read_file`/`list_dir` помнят вызовы хода и на повтор без нового `offset` отвечают «already read at call #N (lines a–b); use offset/grep»; (б) в `prompt` Сабагента автоматически вклеивать компактную карту Лида (дерево до глубины 2 + стек + scope диапазона `git_diff --stat`). | Cognition «share full agent traces», Claude Code Explore (read-only + summary), наши 173 дубля | `core/tools/sandbox/__init__.py` (замыкание с `dict` на ход), `core/tools/delegation/task.py::build_task_tool` | M | Кэш ломает «намеренное перечитывание после правки» — у нас репо read-only, риска нет |
| R7 | **Утоньшить `load_skill` и `grep_code`**: `load_skill` — идемпотентно (второй запрос той же справки → «already loaded»), верхняя граница 8 k символов на скилл с секцией «full: load_skill(name, full=true)»; `grep_code` — дефолт `--glob '!node_modules' '!vendor' '!*.min.*'`, режим `concise` (файл:строка:фрагмент, максимум 200 совпадений), потолок 25 k символов вместо 50 k. | Anthropic «Writing tools» (concise/detailed, 25 k), Chroma (дистракторы) | `core/tools/security/load_skill.py`, `core/tools/sandbox/search.py`, `SANDBOX_OUTPUT_MAX_CHARS` | S | Меньше контекста на сложные скиллы — `full=true` оставляет доступ |
| R8 | **References только из тулов + автогенерация + проверка**: (а) `report_finding` принимает `references` лишь если URL встречался в выводе `web_search`/`browse`/`sandbox_run` этого хода (леджер квитанций уже есть) — иначе отбрасывать с сообщением; (б) детерминированные ссылки из `cwe`/`cve`/GHSA (`cwe.mitre.org/data/definitions/<N>.html`, `osv.dev/vulnerability/<ID>`) строит система; (в) перед персистом в `hub.py` — `HEAD` с таймаутом 5 с, для OSV/NVD — `api.osv.dev/v1/vulns/<ID>`; битые → удалить, в `structured` — пометка `references_dropped`. | arXiv 2604.03173 (программная проверка, 6–79×), Semgrep (референсы курируются, не генерируются), Citations API (ссылка = позиция в переданном документе), наши 0 % vs 39 % | `core/tools/security/report_finding.py`, `core/tools/security/hub.py`, `core/subagents/receipts.py` (леджер URL), промпты Лида/Сабагента | M | Сетевой вызов в момент персиста; делать асинхронно с fail-open (`unverified`), не блокировать Находку |
| R9 | **Гейт между волнами делегаций**: Лид не может выпускать новые `task`, пока не «закрыл» предыдущие (принял/отверг результаты в todo) и пока бюджет хода > порога; после `FAILED` по причинам 4xx/5xx провайдера — запрет делегаций до конца хода. | §2.4-3 (8 Сабагентов после 402), Kim et al. «centralized verification», MAST FM-3.2 | `core/middleware/subagent_limit.py` (расширить `after_model`), `core/tools/delegation/task.py` (класс ошибки) | S | — |
| R10 | **Локальные модели — «safe mode» Сборки**: если провайдер локальный/`params.tool_calling_unreliable`, то `subagent=False`, `max_tokens` ≥ 4 k для аргументов, `finish_reason=length` → повтор с просьбой сократить аргументы (а не 500 → `run_failed`), `evidence`/`prompt` ограничены 2 k символов схемой тула. | vLLM #21026, Ollama #14570, наши 3× «missing closing quote», 6× `general` | `deps/container.py`/`core/agents/llm.py` (параметры), `core/middleware/tool_error_handling.py`, схемы тулов | S | Потеря части контекста в `evidence` — пусть ссылается на `file:lines` |
| R11 | **Разные модели/режимы для Лида и Сабагента** (`limits.subagentModel` в Сборке): большая для координации/финального отчёта, дешёвая для узких проверок; для Claude — `effort: low` детям. | NVIDIA SLM, SMART (7B ≈ 70B при обученном «когда тул не нужен»), Anthropic Effort («such as subagents») | `core/lead/graph.py::build_lead_profile` (передать `model` детям отдельно), `hub.agent_builds.limits` | M | Слабая модель у детей ↑ FP — компенсируется R8/R9 |
| R12 | **Метрики эффективности в `turn summary` и evals**: дубли вызовов, доля разведки, токены/Находку, cache-hit (из `usage_metadata.input_token_details.cache_read`), «capped без отчёта», доля битых URL — и порог в `evals/` как validity-гейт для Арма. | Anthropic (токены = 80 % дисперсии), Manus (KV-hit — метрика №1), Cuadron (overthinking score) | `core/tracing/turn_tracer.py::TurnStats`, `core/subagents/executor.py::SubagentTokenCollector`, `evals/grade.py` | S | — |

| R13 | **Корпус траекторий + конвертер в TRL-формат**: экспорт из чекпоинтов LangGraph / `hub.activity` в `messages` с `tool_calls`/`tool` + колонка `tools`; метки успеха из Батареи (Факты), R12-метрик (дубли, бюджет) и проверки URL (R8). Хранить как Бандлы. | SWE-smith (rejection sampling, ≤ 3/задача, режет лёгкие), Kimi-Dev (5 k), TRL «tool calling» формат | новый `evals/export_trajectories.py` (app-free, читает БД), `evals/grade.py` | S | Без Батареи на ≥ 20 репо метки успеха нечестные — сначала расширить `repos.v1.jsonl` |
| R14 | **Пилот QLoRA «поведение агента» на qwen3 27B** — только после R1–R9 и ≥ 500 отфильтрованных траекторий: Unsloth/TRL, `assistant_only_loss`, 32 k, 1 × 48–80 GB; экспорт LoRA → GGUF → llama.cpp; A/B на held-out Юнитах по R12-метрикам. | ToolRL (+15 % над SFT — значит SFT-потолок низкий, но дешёвый), Unsloth 26 GB для 32B QLoRA, QLoRA «single 48GB GPU» | вне репо (training-скрипт), Сборка с новым `model` в `hub.llm_connections` | L | Overfit на репо Батареи; «repetitive steps» после обучения (OpenHands LM); падение thinking без 75/25-микса |
| R15 | **Не дообучать «на уязвимости»** (CVE/CWE-датасеты, отчёты сканеров, немаркированные логи): анти-рекомендация, зафиксировать в `evals/README`. | CyberGym (SWE-tuned ≤ 2 %), «Calibration Without Comprehension» (52,1 %), 2606.15123 (регресс на path traversal) | — | — | — |

Порядок: R2 + R5 + R7 + R9 (день, без миграций) → R1 + R4 + R6 (неделя) → R8 (неделя, требует OpenSpec-изменения контракта Находки) → R3, R10–R12 → R13 (после расширения Батареи) → R14 (только при выполнении стоп-критерия §3.6).

---

## 5. Источники

1. Cognition — Don't Build Multi-Agents: https://cognition.com/blog/dont-build-multi-agents
2. Anthropic — How we built our multi-agent research system: https://www.anthropic.com/engineering/multi-agent-research-system
3. Kim et al. — Towards a Science of Scaling Agent Systems (arXiv 2512.08296): https://arxiv.org/abs/2512.08296
4. Cemri et al. — Why Do Multi-Agent LLM Systems Fail? (MAST, arXiv 2503.13657): https://arxiv.org/abs/2503.13657
5. Cuadron et al. — The Danger of Overthinking (arXiv 2502.08235): https://arxiv.org/abs/2502.08235
6. Qian et al. — SMART: Self-Aware Agent for Tool Overuse Mitigation (arXiv 2502.11435): https://arxiv.org/abs/2502.11435
7. Scores Are Not Decisions: Cost-Aware Stopping for Tool Acquisition (arXiv 2607.27083): https://arxiv.org/abs/2607.27083
8. Anthropic — Task budgets (docs): https://platform.claude.com/docs/en/build-with-claude/task-budgets
9. Anthropic — Effort (docs): https://platform.claude.com/docs/en/build-with-claude/effort
10. Yang et al. — SWE-agent: Agent-Computer Interfaces (arXiv 2405.15793): https://arxiv.org/abs/2405.15793
11. mini-SWE-agent (репозиторий): https://github.com/SWE-agent/mini-swe-agent
12. Wang et al. — OpenHands (arXiv 2407.16741): https://arxiv.org/abs/2407.16741
13. Anthropic — Writing tools for agents: https://www.anthropic.com/engineering/writing-tools-for-agents
14. Anthropic — Building effective agents: https://www.anthropic.com/engineering/building-effective-agents
15. Claude Code — Subagents (docs): https://code.claude.com/docs/en/sub-agents
16. LangChain — Deep Agents overview: https://docs.langchain.com/oss/python/deepagents/overview
17. Chroma — Context Rot: https://www.trychroma.com/research/context-rot
18. Manus — Context Engineering for AI Agents: https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus
19. LLM hallucinations in the wild: non-existent citations (arXiv 2605.07723): https://arxiv.org/abs/2605.07723
20. Detecting and Correcting Reference Hallucinations in Commercial LLMs and Deep Research Agents (arXiv 2604.03173): https://arxiv.org/abs/2604.03173
21. Anthropic — Citations (docs): https://platform.claude.com/docs/en/build-with-claude/citations
22. Anthropic — Claude Code Security: https://www.anthropic.com/news/claude-code-security
23. Semgrep — Rule syntax (metadata): https://docs.semgrep.dev/writing-rules/rule-syntax
24. Belcak et al. — Small Language Models are the Future of Agentic AI (arXiv 2506.02153): https://arxiv.org/abs/2506.02153
25. vLLM issue #21026 — Qwen3-32B loops with `tool_choice="required"`: https://github.com/vllm-project/vllm/issues/21026
26. Ollama issue #14570 — qwen3 tool call parser fails on truncated JSON: https://github.com/ollama/ollama/issues/14570
27. OSV API (использован для проверки идентификаторов, пример): https://api.osv.dev/v1/vulns/GO-2026-6355

Дообучение (§3.6):

28. Pan et al. — SWE-Gym (arXiv 2412.21139): https://arxiv.org/abs/2412.21139
29. Yang et al. — SWE-smith (arXiv 2504.21798): https://arxiv.org/abs/2504.21798 (полный текст: https://arxiv.org/html/2504.21798)
30. Jain et al. — R2E-Gym (arXiv 2504.07164): https://arxiv.org/abs/2504.07164
31. Skywork-SWE (arXiv 2506.19290): https://arxiv.org/abs/2506.19290
32. Kimi-Dev (arXiv 2509.23045): https://arxiv.org/abs/2509.23045
33. OpenHands LM 32B (блог): https://www.openhands.dev/blog/introducing-openhands-lm-32b----a-strong-open-coding-agent-model
34. NVIDIA Nemotron-SWE-v1 (HF dataset): https://huggingface.co/datasets/nvidia/Nemotron-SWE-v1
35. NVIDIA Nemotron-Agentic-v1 (HF dataset): https://huggingface.co/datasets/nvidia/Nemotron-Agentic-v1
36. Qian et al. — ToolRL: Reward is All Tool Learning Needs (arXiv 2504.13958): https://arxiv.org/abs/2504.13958
37. Feng et al. — ReTool (arXiv 2504.11536): https://arxiv.org/abs/2504.11536
38. Qwen — Qwen3-Coder: Agentic Coding in the World (блог): https://qwenlm.github.io/blog/qwen3-coder/
39. DeepSeek-V3.2 (arXiv 2512.02556): https://arxiv.org/abs/2512.02556
40. Agent-R1 (arXiv 2511.14460): https://arxiv.org/abs/2511.14460
41. SINKFLEX-RL — Efficient RL for Long-Horizon Tool-Use Agentic Tasks (arXiv 2608.10357): https://arxiv.org/abs/2608.10357
42. CyberGym (arXiv 2506.02548): https://arxiv.org/abs/2506.02548 (полный текст: https://arxiv.org/html/2506.02548)
43. SEC-bench (arXiv 2506.11791): https://arxiv.org/abs/2506.11791
44. VulnGym (arXiv 2608.02001): https://arxiv.org/abs/2608.02001
45. Calibration Without Comprehension (arXiv 2606.20502): https://arxiv.org/abs/2606.20502
46. Data-Centric Benchmarking of Exploit Generation in LLMs: Impact of Fine-Tuning (arXiv 2606.15123): https://arxiv.org/html/2606.15123v1
47. Dettmers et al. — QLoRA (arXiv 2305.14314): https://arxiv.org/abs/2305.14314
48. Unsloth — Requirements (VRAM table): https://unsloth.ai/docs/get-started/fine-tuning-for-beginners/unsloth-requirements
49. Unsloth — Qwen3: How to run & fine-tune: https://unsloth.ai/docs/models/tutorials/qwen3-how-to-run-and-fine-tune
50. TRL — SFTTrainer (tool calling, assistant_only_loss): https://huggingface.co/docs/trl/sft_trainer
51. LLaMA-Factory (репозиторий): https://github.com/hiyouga/LLaMA-Factory
52. Qwen — Function Calling (документация): https://qwen.readthedocs.io/en/latest/framework/function_call.html
53. llama.cpp (репозиторий; `convert_hf_to_gguf.py`, `convert_lora_to_gguf.py`): https://github.com/ggml-org/llama.cpp

Недоступно при подготовке: OpenAI «Introducing Aardvark» (`openai.com/index/introducing-aardvark/`, HTTP 403 для fetch) — использованы только сведения из предыдущего отчёта и поискового индекса, без цитат.

Проверка ссылок: 55/55 → 200 (curl -sL -o /dev/null -m 20 -A "Mozilla/5.0" -w %{http_code}, 2026-09-04; плейсхолдеры из evidence и URL-шаблоны в §2.8/§4 записаны без схемы и в проверку не входят)
