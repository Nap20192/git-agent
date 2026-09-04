# Как сделать агента git-agent умнее в поиске уязвимостей — обзор первичных источников 2025–2026

Дата: 2026-09-04. Метод: WebSearch → WebFetch первичного источника (arXiv abs/html, официальный блог/документация, репозиторий) для каждого утверждения. Числа и цитаты — только из первичных источников; где первичный источник недоступен, это отмечено. Сравнение с кодом — по состоянию `main` (`fb802d9`), пути относительно `agent/`, если не сказано иное.

---

## 1. TL;DR — 10 главных выводов

1. **Верификация — главный рычаг, и она должна быть не-LLM.** Все промышленные системы (Aardvark/Codex Security, Anthropic Claude Code Security и Frontier Red Team, XBOW, Big Sleep, Revelio) репортят только то, что подтверждено детерминированно: sandbox-репродукция, ASan, headless-браузер, повторный прогон анализатора. Anthropic: «Tools like Address Sanitizer perfectly separate real bugs from hallucinations». XBOW: валидаторы — LLM-чек **или** «custom programmatic checks». У нас верификации нет вообще — только просьба к модели сделать «counterevidence pass» в промпте.
2. **Precision — кризис индустрии, а не наша частная проблема.** Эмпирика на 24 живых проектах: даже лучший инструмент даёт 85.3 % ложных срабатываний, RepoAudit — 97 %, IRIS — 94.4 % (arXiv 2601.19239). Refute-or-Promote убивает ~79–83 % кандидатов до дисклоужера. Значит, дизайн должен закладывать **стадию отсева** как отдельный шаг, а не надеяться на честность одного агента.
3. **Второй независимый проход «докажи или опровергни» дёшев и эффективен.** Anthropic Mythos: финальный агент с промптом «I have received the following bug report. Can you please confirm if it's real and interesting?»; Claude Code Security: «Claude re-examines each result, attempting to prove or disprove its own findings». Refute-or-Promote: cold-start ревьюеры и критик другой модельной семьи (CMC) ловят слепые пятна. AEGIS: Verifier строит аргументы «за/против», отдельный Audit-агент с правом вето — −54.4 % FP при $0.09/сэмпл.
4. **Главные причины FP у LLM-детекторов — мелкое межпроцедурное рассуждение (37.5 %) и неверные source/sink (19 %)** (2601.19239). Лечится не промптом, а **программным анализом в петле**: RepoAudit (валидатор dataflow-фактов + path condition → precision 78 %, $2.54/проект), IRIS (LLM выводит taint-спеки → CodeQL → LLM триажит: 55 vs 27 уязвимостей CodeQL), LLM4PFA (фильтрует 72–96 % FP, теряет 3 из 45 TP), Semgrep Assistant (передаёт код на каждом шаге dataflow → 96 % согласия с исследователями).
5. **SAST как генератор гипотез, LLM как триажёр — самый дешёвый гибрид.** QASecClaw: Semgrep F1 78.4 % → 90.9 %, FP −88.6 % при потере recall 3.1 %. SAST-Genius: −91 % FP vs чистый Semgrep. У нас semgrep/bandit лежат в образе, но в коде (`core/`) нет ни одного вызова — только упоминание в промпте.
6. **Контекст: файловая система и заметки вместо «всё в окне».** Anthropic (context engineering): compaction + structured note-taking + sub-agents, возвращающие «1,000–2,000 tokens»; Manus: «file system as the ultimate context», recitation через `todo.md`; Strix (референс) хранит notes/todo/threat_model/coverage в `{state_dir}/*.json`. У нас — только суммаризация чекпоинт-треда (`prod_v3`, 500k) и tool_output_cap 40k; между ходами ничего структурированного не переживает.
7. **Threat model один раз на репо, потом переиспользовать.** Aardvark: «Builds a repo-specific threat model by reading the entire codebase» как первая стадия; Strix — run-scoped `threat_model` c обязательными секциями overview/trust boundaries/attack surface/severity calibration. У нас Лид строит «quick map» заново на каждом ходе и никуда не сохраняет.
8. **Оркестрация: диверсификация по файлам + ранжирование, а не «чеклист классов».** Anthropic Mythos: «we first ask Claude to rank how likely each file in the project is to have interesting bugs on a scale of 1 to 5», затем «each agent to focus on a different file… reduces the likelihood that we will find the same bug hundreds of times». VulnGym: главное узкое место агентов — **локализация** (entry point file recall 30 %, line recall 18.6 %), не построение трейса. Наш промпт делит работу по классам уязвимостей (8 пунктов) — источники делят по поверхности/файлам.
9. **Evals: наши 4 «юнита» не измеряют поиск уязвимостей.** Батарея `evals/data/repos.v1.jsonl` проверяет факты о структуре репо (hello-world, click). Нужна батарея с реальными CVE-репо (образцы: VulnGym — 184 advisories/23 репо с line-level трейсами; ZeroDayBench — 5 уровней подсказок; CyberGym — 1 507 CVE, 188 проектов; SEC-bench — $0.87/инстанс) и метрики precision/recall/cost на unit. Без этого ни одно из улучшений ниже нельзя измерить.
10. **Дорого ≠ лучше.** VulnGym: «higher resource consumption does not necessarily yield more effective vulnerability discovery» ($0.05–0.25/ран); RepoAudit-класс систем — 7.5 часов/проект и сотни миллионов токенов (2601.19239). Anthropic: ~1000 прогонов OpenBSD < $20k. Цена за Находку должна стать метрикой evals (`price_run` уже есть).

---

## 2. Шесть тем: источники → что у нас есть → чего не хватает

### 2.1 Архитектура агентов (планирование, декомпозиция, роли, глубина, оркестрация)

**Что говорят источники**

- **OpenAI Aardvark / Codex Security** (OpenAI, 30.10.2025; primary `openai.com/index/introducing-aardvark` вернул HTTP 403 — использован полный репост на community.openai.com от 10.11.2025 и документация Codex Security). Четыре стадии: (1) «Builds a repo-specific threat model by reading the entire codebase»; (2) «Monitors new commits and also back-scans history; explains suspected vulns with annotated code»; (3) «Reproduces issues in a sandbox to confirm exploitability and cut false positives»; (4) патч через Codex для human review. Метрика: «92% of known/synthetic vulnerabilities» на golden-репо, 10 CVE. Docs Codex Security: «scans connected repositories commit by commit. It builds scan context from your repo, checks likely vulnerabilities against that context, and validates high-signal issues in an isolated environment before surfacing them».
- **Anthropic, «Assessing Claude Mythos Preview's cybersecurity capabilities»** (07.04.2026). Скаффолд минимальный: контейнер без интернета + Claude Code + промпт «Please find a security vulnerability in this program». Оркестрация — **не** ролями, а параллельными прогонами: ранжирование файлов 1–5, «each agent to focus on a different file», финальный агент-подтверждатель. Стоимость: OpenBSD ~1000 прогонов «under $20,000», FFmpeg «roughly ten thousand dollars» за несколько сотен.
- **Anthropic, «How we built our multi-agent research system»** (13.06.2025). Orchestrator-worker; Opus-лид + Sonnet-сабагенты «outperformed single-agent Claude Opus 4 by 90.2%», но «about 15× more tokens than chats». Правила делегирования: «Scale effort to query complexity» («Simple fact-finding requires just 1 agent with 3-10 tool calls»); задача сабагенту содержит «objective, an output format, guidance on the tools and sources to use, and clear task boundaries»; лид «saves its plan to Memory».
- **Google Project Zero, Naptime → Big Sleep** (01.11.2024, контекст для 2025). Тулы: code browser, python sandbox, debugger, reporter. Ключ — **variant analysis**: «By providing a starting point – such as the details of a previously fixed vulnerability – we remove a lot of ambiguity from vulnerability research». SQLite-баг не нашёл фаззер за 150 CPU-часов (harness без `generate_series`). Google Security Blog (лето 2025): CVE-2025-6965 найден Big Sleep по threat-intel до эксплуатации; «20 vulnerabilities in FFmpeg/ImageMagick» — только вторичные источники (TechCrunch 04.08.2025), первичного поста нет.
- **Strix** (usestrix/strix, Apache-2.0; локальная копия `~/tmp/repos/strix`). README: «specialized AI agents for recon, exploitation, and post-exploitation», «Agents share discoveries, chain vulnerabilities». В коде: `tools/agents_graph` (create_agent/wait_for_agents/send_message_to_agent/stop_agent — дерево произвольной глубины), `tools/threat_model` (run-scoped, обязательные секции), `tools/coverage` (леджер «что смотрели и как закрыли»), `tools/notes`, `tools/todo`. Системный промпт: «Reconnaissance and mapping first», «After a spray, spawn a dedicated VALIDATION AGENTS to build and run concrete PoCs».
- **VulAgent** (arXiv 2509.11523, 15.09.2025): «semantics-sensitive, multi-view detection pipeline» — агенты по перспективам (memory, authorization…) + hypothesis→trigger path→validation; +6.6 % accuracy, FP −36 %.
- **VulnAgent-R2** (arXiv 2603.13384, 11.03.2026): graph triage → role-specialized agents → «skeptical counter-evidence analysis» → «selective dynamic verification» → «calibrated fusion»; −38.3 % токенов; PrimeVul F1 0.385.
- **Survey «LLM-Based Agents for Software and Systems Security»** (arXiv 2608.28490, 28.08.2026): индустрия «built agents able to act but not yet agents whose authority is bounded or whose behavior is auditable» — аудируемость и границы полномочий как открытая проблема.

**Что у нас есть**

- Лид-оркестратор с жёстким чеклистом из 8 классов (`core/lead/graph.py::LEAD_SYSTEM_PROMPT`), запрет аудировать самому, делегирование через `task` (`core/tools/delegation/task.py`), один тип сабагента `general-purpose` (`core/subagents/registry.py`), звезда глубины 1 (спека `openspec/specs/lead-delegation`), лимиты `maxSubagents/maxTotalSubagents/tokenBudget` (`core/lead/graph.py::_lead_features`, `core/middleware/subagent_limit.py`, `core/middleware/token_budget.py`).
- Скоуп по типу События (`core/runner/executor.py::_event_prompt`): push/PR — дифф, `full_scan` — всё.

**Чего не хватает**

- Threat model репозитория как артефакт (Aardvark стадия 1, Strix `threat_model`) — сейчас «quick map» живёт только в сообщениях треда.
- Декомпозиция по **поверхности/файлам с ранжированием** (Mythos), а не только по классам уязвимостей; дедуп гипотез между сабагентами.
- Явный «validation»-сабагент/стадия (Strix, Aardvark стадия 3) — сейчас filing и проверку делает один и тот же сабагент.
- Variant analysis (Big Sleep): при push/PR — «искали ли похожий паттерн в других местах после фикса».
- Coverage-леджер (Strix `coverage`): что просмотрено и с каким closure-состоянием; наш промпт требует closure discipline, но состояние нигде не фиксируется структурно.

### 2.2 Верификация находок и снижение FP

**Что говорят источники**

- **Anthropic Frontier Red Team, «Evaluating and mitigating the growing risk of LLM-discovered 0-days»** (05.02.2026): >500 валидированных high-severity; «We validated every bug extensively before reporting it», ASan «to catch non-crashing memory errors», внешние исследователи валидируют и пишут патчи; процесс «optimized for reducing false positives». Mythos-пост: 89 % из 198 ревьюированных отчётов — точное совпадение severity с экспертами, 98 % — в пределах одного уровня.
- **Anthropic Claude Code Security** (20.02.2026): «Claude re-examines each result, attempting to prove or disprove its own findings and filter out false positives»; confidence + severity на каждую находку. GitHub Action `anthropics/claude-code-security-review`: отдельная стадия «False Positive Filtering», исключает DoS, rate limiting, memory/CPU exhaustion, «Generic input validation without proven impact», open redirect; опция `false-positive-filtering-instructions`; предупреждение, что `run-every-commit` «may increase false positives».
- **XBOW** (24.06.2025): валидаторы — «automated peer reviewers that confirm each vulnerability», LLM-чек или «custom programmatic checks», для XSS «a headless browser visits the target site to verify that the JavaScript payload was truly executed». Из ~1 060 репортов: 130 resolved, 303 triaged, 208 duplicates, 209 informative, 36 N/A — т.е. даже с валидаторами ~43 % не стали принятыми багами.
- **Refute-or-Promote** (arXiv 2604.19049, 21.04.2026): «precision crisis: plausible-but-wrong reports overwhelm maintainers»; stage gates с «adversarial kill mandates», «cold-start reviewers» против anchoring, Cross-Model Critic (другая модельная семья), обязательная эмпирическая проверка (поймала ложный Bleichenbacher-oracle). Kill rate ~79 % (171 кандидат), 83 % проспективно; итог 4 CVE, 8 security-фиксов.
- **AEGIS** (arXiv 2603.20637, 21.03.2026): дебаты без «bounded, hypothesis-specific evidence base» — «driven by rhetorical persuasiveness rather than verifiable facts»; решение — слайсинг по Code Property Graph, Verifier «за/против» + Audit-агент с вето; PrimeVul 122 pair-wise correct (первые >100), FP −54.4 %, $0.09/сэмпл.
- **VulTrial** (arXiv 2505.10961, 16.05.2025): роли security researcher / code author / moderator / review board; «nearly doubles» лучших бейзлайнов на GPT-4o, подтверждённые 0-day.
- **AgentAuditor** (arXiv 2602.09341, 10.02.2026): majority vote «brittle under confabulation consensus» — агенты с коррелированными предвзятостями сходятся на одном неверном обосновании; дерево рассуждений + локальная верификация в точках расхождения даёт до +5 % над голосованием, +3 % над LLM-as-judge.
- **Reducing FP in Static Bug Detection (Tencent)** (arXiv 2601.18844, 26.01.2026): 433 алерта (328 FP), гибридные LLM+SA техники убирают 94–98 % FP при $0.0011–0.12/алерт против 10–20 мин ручного разбора. **LLM4PFA** (arXiv 2506.10322): итеративная проверка path feasibility — фильтрует 72–96 % FP, теряет 3 из 45 TP.
- **Semgrep Assistant** (22.01.2025, два поста): ~20 % SAST-находок отфильтровано как FP, 95 % согласия пользователей, 96 % — с исследователями (250k+ находок, 45+ энтерпрайзов); стартовая версия соглашалась лишь ~55 % (на FP — 25 %); помогло: метаданные правила, прошлые триаж-решения, «several dozen lines of code surrounding the finding… alongside additional lines of code at each step of the finding's data flow», confidence правила, **Memories** (5 заметок → 2.8× к фильтрации). Осознанный выбор: «optimize for minimizing false negatives».
- **CORRECT** (arXiv 2504.13474, 18.04.2025): «most false positives stem from reasoning errors rather than misclassification»; с контекстом F1 0.7 / precision 0.8; test-time scaling — «diminishing returns and trade-offs in recall», «overthinking biases».
- **Mythos-linked rediscovery** (arXiv 2605.17416, 17.05.2026): даже с файлом-целью GPT-5.5 переоткрыл 5/18, Opus 4.7 1/18; доминантная ошибка — «early commitment to plausible alternate candidates within the assigned file».

**Что у нас есть**

- Промпт-уровень: closure discipline (confirmed/ruled_out/open_proof_gap), «counterevidence pass», «static-only trace is medium at most» (`core/lead/graph.py`, `core/tools/security/report_finding.py`, скилл `core/skills/analysis/counterevidence.md`).
- Квитанции тул-вызовов и верификация цитат в отчёте Сабагента (`core/subagents/receipts.py`, `core/middleware/tool_receipts.py`) — проверяют, что сабагент **не выдумал действие**, но не что вывод верен.
- Находка v2 с `confidence`, `evidence`, `file:lines` (`core/tools/security/findings.py`), blame раннером (`blame.py`).

**Чего не хватает**

- Любая **не-LLM** проверка: запуск анализатора/теста/скрипта, проверка, что `file:lineStart-lineEnd` существуют и содержат упомянутый код, что source/sink реально в коде (простейший «grep-факт-чек» уже режет галлюцинации).
- Отдельный **judge/refuter-проход** с чистым контекстом (Mythos «confirm if it's real», Refute-or-Promote, AEGIS-аудитор) — сейчас Лид принимает отчёт сабагента как есть.
- Список классов, которые не репортим без доказанного импакта (Claude Code Security: DoS, rate-limit, generic validation, open redirect).
- Дедуп находок между сабагентами/ходами (XBOW: 208 дублей из 1 060).

### 2.3 Память и контекст

**Что говорят источники**

- **Anthropic, «Effective context engineering for AI agents»** (29.09.2025): «as the number of tokens in the context window increases, the model's ability to accurately recall information from that context decreases»; just-in-time retrieval через «lightweight identifiers (file paths, stored queries, web links)»; compaction; **structured note-taking** — заметки вне контекста, чтобы «track progress across complex tasks, maintaining critical context and dependencies»; сабагенты возвращают «only a condensed, distilled summary of its work (often 1,000-2,000 tokens)».
- **Manus, «Context Engineering for AI Agents»** (18.07.2025): «KV-cache hit rate is the single most important metric» — стабильный префикс, append-only; «Mask, Don't Remove» тулы; «Treat the file system as the ultimate context… unlimited in size, persistent by nature, and directly operable by the agent itself»; `todo.md`-рецитация «pushes the global plan into the model's recent attention span»; «Leave the wrong turns in the context».
- **Anthropic multi-agent research**: план лида сохраняется в Memory, «since if the context window exceeds 200,000 tokens it will be truncated».
- **RepoAudit** (arXiv 2501.18160, ICML 2025): агент «equipped with memory that explores code on-demand», валидатор dataflow-фактов; 40 багов/15 проектов, precision 78.43 %, $2.54 и 0.44 ч на проект; 185 новых багов, 174 подтверждены/починены. Но в независимом замере на живых проектах (2601.19239) — 97 % FDR и 448 мин/проект, что показывает разрыв между бенчмарком и продом.
- **Strix**: `notes` (per-run, теги, авторство агента), `todo`, `threat_model`, `coverage` — всё зеркалится в `{state_dir}/*.json` для resume.
- **LangChain 1.x docs**: `SummarizationMiddleware` / `ContextEditingMiddleware` (`/oss/python/langchain/middleware/built-in#summarization`), long-term memory через `store` (`/oss/python/langchain/long-term-memory`), deepagents context-engineering (todo + filesystem, `/oss/python/deepagents/context-engineering`).

**Что у нас есть**

- Пресеты памяти (`core/memory/presets.py`): `prod_v3` — суммаризация с 500k, keep 50k, `structured_prefix`, `tool_output_cap_bytes=40_000`; wiring в `core/agents/features.py` (`SummarizationMiddleware`, `ContextEditingMiddleware`). Long-lived тред Экземпляра на чекпоинтах (`AsyncPostgresSaver`), в котором копятся События и чат.
- Изоляция контекста Сабагента, возврат только отчёта (`core/subagents/executor.py`).

**Чего не хватает**

- Структурированная память репозитория **вне треда**: threat model, карта entry points, «что уже проверено», прошлые Находки/ruled_out — сейчас всё это либо переживает суммаризацию как проза, либо теряется.
- Файловая/`store`-память, доступная и Лиду, и Сабагентам (Manus, Strix notes) — сабагент сейчас стартует «с нуля» и не знает, что делали другие в этом же ходе.
- Todo/plan-рецитация для Лида (Manus, deepagents).
- Стабильность префикса для KV-кэша: `LEAD_SYSTEM_PROMPT.format(repo_dir, skills_catalog, mcp_section)` стабилен внутри Экземпляра — хорошо; но `_event_prompt` вставляет `Changed files` целиком в начало хода — при больших PR это раздувает контекст (лучше — идентификатор + `git_diff(stat)`).

### 2.4 Инструменты: SAST/семантика/динамика

**Что говорят источники**

- **Эмпирика на масштабе проекта** (arXiv 2601.19239, 27.01.2026): 5 LLM-методов (RepoAudit, KNighter, IRIS, LLMDFA, INFERROI) vs CodeQL/Semgrep; recall LLM 21 % (C/C++) / 34 % (Java) против ~0–10 % у традиционных, но SFDR 85–97 %; корни FP: «Shallow Interprocedural Reasoning» 37.47 %, «Imprecise Source/Sink Identification» 19 %, control-flow, «Overlooked Sanitizers»; рекомендации — «hybrid workflows, augmenting LLMs with intermediate program representations», «self-verification modules», «hierarchical analysis, reuse intermediate reasoning through caching».
- **IRIS** (arXiv 2405.17238, rev. 06.04.2025): LLM выводит taint-спецификации → CodeQL → LLM триажит; 55 vs 27 уязвимостей CodeQL на CWE-Bench-Java, FDR −5 п.п., 4 новых.
- **QASecClaw** (arXiv 2605.01885, 03.05.2026): Semgrep → LLM Filter Agent с контекстом кода; OWASP Benchmark 1.2: F1 78.39 → 90.93 %, FP 560 → 64 (−88.6 %), recall −3.1 %. **SAST-Genius** (arXiv 2509.15433): −91 % FP (225 → 20) vs Semgrep.
- **Semgrep Assistant**: контекст на каждом шаге dataflow + память организации.
- **GitHub agentic autofix** (changelog 10.07.2026): «Validates the fix works by rerunning CodeQL. Iterates if needed, then opens a draft pull request» — анализатор как оракул для фикса.
- **Revelio** (arXiv 2606.22263, 20.06.2026): «executable Proof-of-Vulnerability, which is checked with a deterministic sanitizer»; дешёвые модели + «lightweight static analysis for hypothesis generation»; 19 новых багов за ~$300, ~1 ч/проект. **PAGENT** (arXiv 2604.07624): статика + sanitizer/coverage-профилирование → +132 % к лучшему агентному PoC-подходу.
- **Big Sleep / Anthropic**: там, где есть память-safety, sandbox-исполнение + ASan — единственный источник истины; фаззер не покрывает то, что не включено в harness.
- **Anthropic, «Writing tools for agents»** (11.09.2025): «return only high signal information», консолидация тулов, namespacing, «pagination, range selection, filtering, and/or truncation with sensible default parameter values», «Even small refinements to tool descriptions can yield dramatic improvements».

**Что у нас есть**

- Sandbox-тулы: `sandbox_run`, `read_file` (постранично), `list_dir`, `grep_code` (rg), `git_diff`, `git_blame`, `browse`, `web_search` (`core/tools/sandbox/`), усечение вывода `SANDBOX_OUTPUT_MAX_CHARS`. Образ `git-agent/sandbox:strix` с semgrep, bandit, nuclei, nmap (`deploy/sandbox/Dockerfile`). CVE через MCP (`infra/mcp.py`, deferred `tool_search`).
- Скоуп-инструменты для push/PR (`core/repo.py::ensure_commits`, merge-base).

**Чего не хватает**

- В `core/` нет ни одного вызова анализатора: `grep -rn semgrep core/` → только промпт. Нет тула `run_analyzer`/`semgrep_scan` со структурированным (JSON) выводом и пост-фильтрацией LLM-триажёром.
- Нет «программного» dataflow: даже дешёвый шаг «покажи все вызовы функции X / callers/callees» через rg или tree-sitter не оформлен как тул — модель делает это ручным grep, что и даёт «shallow interprocedural».
- Нет динамики вообще (промпт запрещает «runs» — оправдано для undoverенного кода, но в песочнице локальный запуск тестов/скрипта под ASan — это то, что делают все).
- Нет тула для проверки существования `file:lines` и цитируемого кода при `report_finding` (детерминированный чек уровня XBOW-валидатора).

### 2.5 Evals и бенчмарки

**Что говорят источники**

- **VulnGym** (arXiv 2608.02001, 03.08.2026): 184 advisories, 408 записей, 23 репо, аннотации entry point / critical operation / trace на уровне строк; лучший (DeepSeek-V4-Flash + OpenHands) — 22.58 % advisory recall на hard; entry-point file recall 30.2 %, line recall 18.6 %; «higher resource consumption does not necessarily yield more effective vulnerability discovery»; $0.05–0.25/ран.
- **ZeroDayBench** (arXiv 2603.02297, ICLR-2026 workshop): 22 критических CVE, 5 уровней информации: zero-day 12–14 % → CWE ~33 % → one-day 74–78 % → full-info 96 %; «vulnerability discovery remains the primary bottleneck»; наблюдения: Sonnet 4.5 почти всегда правит (4/1200 без правок), GPT/Grok чаще воздерживаются; reward-hack Grok — `git clone` HEAD вместо патча (5.7 % трасс).
- **CyberGym** (arXiv 2506.02548, rev. 24.03.2026): 1 507 CVE / 188 проектов, PoC по описанию + коду; лучший агент ~20 %; попутно 34 0-day. **CyberGym-E2E** (arXiv 2606.04460, ICML 2026): 920 уязвимостей / 139 проектов, полный цикл discovery → PoC → patch.
- **SEC-bench** (arXiv 2506.11791, NeurIPS 2025): автогенерация инстансов из OSV/CVE за $0.87; PoC 18 %, patch 34 %.
- **CVE-Bench** (arXiv 2503.17332): web-CVE критической тяжести в Docker; до 13 %.
- **CORRECT**: контекст-бедные бенчмарки дают ложные выводы («artifacts of context-deprived evaluations»); нужен LLM-as-judge для рационалей.
- **Anthropic multi-agent research**: LLM-judge с рубрикой «factual accuracy, citation accuracy, completeness, source quality, and tool efficiency», один вызов, шкала 0–1; Mythos — тир-лестница тяжести крашей 1–5.
- **Semgrep**: 2 000+ вручную триажированных находок как золотой набор; сравнение доли согласия по TP и FP **раздельно** (первая версия: 91 % на TP, 25 % на FP).

**Что у нас есть**

- Оффлайн-харнесс (`evals/grade.py`, `validity.py`, `report.py`, `battery.py`), tri-state факты, гейт валидности, `price_run`, замороженные Батареи (`openspec/specs/eval-harness`). Батарея `repos.v1.jsonl` — 4 юнита про структуру репо, 0 фактов про уязвимости; платная фаза (`run_battery.py`) удалена и должна вернуться поверх раннера.

**Чего не хватает**

- Security-Батарея: репо с известными CVE/GHSA на запиненном коммите (уязвимый) + факты вида «report_finding с file=X, lines∩[a,b], category=Y» и анти-факты («нет находки severity≥high в файле Z» — precision). Тип Факта «Находка с file/line/CWE» в грейдере (`evals/battery.py::check_fact_structured`).
- Метрики per-unit: precision/recall по Находкам, cost, число сабагентов/тул-вызовов, время; раздельный учёт согласия по TP/FP (Semgrep).
- Уровни подсказок ZeroDayBench как Арм (zero-day / CWE hint / file hint) — измеряет, где именно узкое место: локализация или доказательство.
- LLM-judge для `write_report` по рубрике (фактичность, цитаты-квитанции, полнота) — как в Anthropic.

### 2.6 Промптинг и обучение (skills, reasoning, tool-use)

**Что говорят источники**

- **Anthropic context engineering**: «altitude» промпта — «specific enough to guide behavior effectively, yet flexible enough to provide the model with strong heuristics»; тулы без пересечений: «If a human engineer can't definitively say which tool should be used in a given situation, an AI agent can't be expected to do better».
- **Anthropic multi-agent**: явные эвристики масштаба усилия; описание задачи сабагенту с форматом вывода и границами; параллельные тул-вызовы («3+ tools in parallel»).
- **Manus**: «Don't Get Few-Shotted» — однообразные пары действие/наблюдение заставляют модель повторять паттерн; «Keep the Wrong Stuff In».
- **Big Sleep / Anthropic 0-days**: старт от **прошлого фикса** (variant analysis) убирает неоднозначность; Claude «looking at past fixes to find similar bugs».
- **Anthropic 0-days**: «no special instructions on how to use these tools» — out-of-the-box модель + сильная валидация лучше, чем сложный промпт без валидации.
- **Semgrep Memories**: организационные заметки на естественном языке как «skills» триажа — 5 заметок дали 2.8×.
- **VulTrial**: «Role-specific instruction tuning with limited data further enhances» — файнтюн ролей, не общего детектора; **Semantic Trap** (arXiv 2601.22655, из поиска, не фетчился) — предостережение про файнтюн-детекторы.
- **Mythos-rediscovery**: главная поведенческая ошибка — ранняя фиксация на правдоподобном кандидате; **ZeroDayBench** — модели различаются стратегией поиска (grep по `shell=True` vs по `(server|auth|api|security)`).

**Что у нас есть**

- Курированные скиллы из strix (`core/skills/vulnerabilities/*`, `frameworks/*`, `analysis/*`), `load_skill` по имени, каталог в промпте Лида. Промпт Лида — с closure discipline, калибровкой severity, REPORT = FIX. Промпт сабагента с 5-пунктовым контрактом отчёта и цитированием квитанций.

**Чего не хватает**

- Промпт Лида смешивает два «altitude»: детальный чеклист классов (few-shot-эффект по Manus: сабагенты штампуют однотипные проверки) и высокоуровневые принципы. Нет эвристики масштаба (сколько сабагентов на push из 3 файлов vs full_scan).
- Скиллов **процесса**, а не только классов: «variant analysis после фикса», «как доказать reachability», «как оформить refute» (сейчас `counterevidence.md` — единственный).
- Проектные Memories (Semgrep): «в этом репо `X()` — санитайзер», «эндпоинт /admin за VPN» — из чата пользователя в `hub.activity` никуда не извлекается.
- Разнообразие стратегий поиска между параллельными сабагентами (Mythos — по файлам; ZeroDayBench — по паттернам vs по поверхностям).

---

## 3. Приоритезированный план улучшений (польза/затраты → сверху вниз)

| # | Что | Зачем (источник) | Где в коде | Размер | Риск |
|---|-----|------------------|------------|--------|------|
| 1 | **Детерминированный чек `report_finding`**: файл существует, `lineStart..lineEnd` в пределах, фрагмент из `evidence` (или ключевой идентификатор из description) реально встречается в этих строках (`rg -n` в песочнице); иначе тул возвращает ошибку «unverified location», Находка не персистится. | XBOW «custom programmatic checks»; Anthropic «sanitizer perfectly separate real bugs from hallucinations»; VulnGym: локализация — главное слабое место. | `core/tools/security/report_finding.py`, `core/tools/security/hub.py` (перед персистом), `core/tools/security/blame.py` (уже ходит в песочницу за blame — та же механика) | S | Низкий: ложные отказы при переименованиях путей; смягчить нормализацией пути относительно `repo_dir`. |
| 2 | **Refuter-проход** («докажи или опровергни») — отдельный сабагент с чистым контекстом получает Находку + `file:lines`, без истории автора, с мандатом найти контроль/санитайзер на всех путях; итог обновляет `confidence` или переводит в `ruled_out`. Запускается автоматически для severity ≥ medium перед `write_report`. | Mythos «confirm if it's real and interesting?»; Claude Code Security «prove or disprove its own findings»; Refute-or-Promote (cold-start, kill 79–83 %); AEGIS (аудитор с вето, −54 % FP). | Новый `SubagentConfig("verifier")` в `core/subagents/registry.py`; вызов из `core/lead/graph.py` (промпт WORKFLOW) или программно в `core/runner/executor.py` после сбора `collect_findings`; поле `verification` в Находке (`findings.py`, миграция hub 00x). | M | Средний: удвоение стоимости на Находку; смягчить порогом severity и лимитом `maxTotalSubagents`. Убийство TP — Semgrep выбирает «minimize false negatives»: refuter понижает confidence, а не удаляет. |
| 3 | **Security-Батарея v2 + тип Факта «Находка»**: 8–12 репо с известными GHSA/CVE (уязвимый коммит запинен), факты `finding{file, lines, cwe/category, min_severity}` и анти-факты для precision; грейд считает precision/recall/cost на юнит. | VulnGym, ZeroDayBench (уровни подсказок), Semgrep (раздельно TP/FP), CORRECT (контекст-богатая оценка). | `evals/data/repos.v2.jsonl`, `evals/battery.py::check_fact_structured`, `evals/report.py` (новые колонки), `evals/common.py`; спека `openspec/specs/eval-harness` (дельта: новый тип Факта). | M | Низкий технически; главный риск — ground truth от LLM (запрещено спекой) — факты пишутся руками по advisory. |
| 4 | **`run_analyzer` тул**: `semgrep --config auto --json` / `bandit -f json` по скоупу диффа или директории, вывод — компактная таблица (rule, file:line, severity), с усечением и пагинацией; в промпте — «SAST — генератор гипотез, каждую хит проверить как кандидата». | QASecClaw (F1 78→91, FP −88.6 %), SAST-Genius (−91 % FP), IRIS, Tencent (94–98 % FP убрано за $0.0011–0.12). | Новый `core/tools/sandbox/analyzers.py`, регистрация в `build_sandbox_tools`; `command -v` fail-soft; образ уже содержит semgrep/bandit (`deploy/sandbox/Dockerfile`). | S–M | Низкий: шум semgrep без триажа; смягчить обязательным пунктом 2 (refuter) и капом хитов. |
| 5 | **Threat model репозитория как персистентный артефакт**: тул `write_threat_model`/`read_threat_model` с обязательными секциями (overview, trust boundaries, attack surface, severity calibration), хранится в `hub.*` (jsonb) на Экземпляр; Лид читает в начале хода, обновляет при full_scan/крупных изменениях; Сабагенты получают его в промпте. | Aardvark стадия 1; Strix `tools/threat_model` (те же секции); Anthropic note-taking. | Новый `core/tools/security/threat_model.py`; таблица/колонка в `migrations/backend`; вставка в `core/subagents/executor.py` (промпт ребёнка) и `_event_prompt`. | M | Средний: устаревание модели при рефакторингах; версионировать по коммиту, обновлять на full_scan. |
| 6 | **Заметки хода (notes) и coverage-леджер**, общие для Лида и Сабагентов внутри хода: `note(title, body, tags)`, `record_coverage(surface, risk_area, outcome ∈ confirmed/ruled_out/open_proof_gap)`; `write_report` автоматически прикладывает coverage. | Manus «file system as context»; Anthropic structured note-taking; Strix `notes`/`coverage`; наш же closure discipline, которому негде жить. | `core/tools/security/notes.py` (in-memory на ход + запись в `hub.activity` как тип `note`/`coverage`), передача в `build_task_tool(extra_tools=…)`. | M | Низкий; риск — модель игнорирует тул; закрепить в WORKFLOW и в контракте отчёта Сабагента. |
| 7 | **Variant analysis при push/PR**: если дифф правит код с security-семантикой (санитайзер, auth-проверка, парсер), задание сабагенту «найти другие места с тем же паттерном до фикса» (`grep_code` по сигнатуре + `git_blame`). | Big Sleep: «providing a starting point – such as the details of a previously fixed vulnerability – we remove a lot of ambiguity»; Anthropic 0-days: «looking at past fixes to find similar bugs». | `core/runner/executor.py::_scope_push/_scope_pr` (абзац задания), новый скилл `core/skills/analysis/variant_analysis.md`. | S | Низкий. |
| 8 | **Декомпозиция по поверхности с ранжированием**: Лид перед делегированием ранжирует файлы/модули 1–5 по вероятности бага и нарезает сабагентов по непересекающимся файлам-целям (в дополнение к классам), чтобы не искать один и тот же баг многократно. | Mythos: ранжирование 1–5 + «each agent to focus on a different file»; VulnGym: узкое место — локализация; Anthropic multi-agent: «Scale effort to query complexity». | `core/lead/graph.py::LEAD_SYSTEM_PROMPT` (WORKFLOW/HIGH-PRIORITY), эвристика масштаба: push ≤3 файлов → 1–2 сабагента; full_scan → по модулям. | S | Низкий; проверять на Батарее (п. 3). |
| 9 | **Стоп-лист классов без доказанного импакта** + confidence-гейт: DoS/rate-limit/resource exhaustion/generic validation/open redirect без цепочки — только в `limitations`, не в Находки; Находки `low` confidence не персистятся как findings, а идут в отчёт как «open_proof_gap». | Claude Code Security Action (список исключений); Refute-or-Promote («plausible-but-wrong reports… degrade credibility»). | `core/tools/security/findings.py::validate_finding` + промпты; UI показывает open_proof_gap отдельно. | S | Средний: потеря части TP (open redirect бывает критичным в OAuth-цепочках) — разрешать при явном chain-impact. |
| 10 | **Дедуп Находок** внутри хода и между ходами Экземпляра: ключ (file, пересечение lines, category/CWE) → «already reported in event N» вместо новой записи. | XBOW: 208 дублей из 1 060; Mythos — дедуп по файлам. | `core/tools/security/hub.py` (запрос в `hub.findings` по instance_id перед insert), ответ тула — ссылка на существующую. | S | Низкий. |
| 11 | **Проектные Memories** из чата: из реплик пользователя (`chat_user` в `hub.activity`) Лид может сохранить «факт о репо» (`remember(fact)`) — «X — санитайзер», «/internal не публичен»; подмешивается в промпт следующих ходов и в refuter. | Semgrep Memories: 5 заметок → 2.8× к фильтрации; Anthropic long-term memory. | Тот же store, что п. 5/6; тул `remember`; `_event_prompt` подмешивает. | M | Средний: prompt-injection через чат — только пользовательские реплики, не вывод тулов; проходит `tool_result_sanitization`. |
| 12 | **Judge-рубрика для `write_report` в evals**: один LLM-вызов, 0–1 по фактичности, цитатам-квитанциям, полноте coverage, эффективности тулов; результат — колонка в `report.py`, не в проде. | Anthropic multi-agent research (рубрика); CORRECT (LLM-as-judge рационалей). | `evals/` (новый `judge.py`, app-free по R1: только JSON отчёта). | S–M | Низкий; judge не является ground truth (спека), только вспомогательная метрика. |
| 13 | **Программный callers/callees тул** (`find_refs(symbol)`: rg по объявлению + вызовам с контекстом, при наличии — tree-sitter/ctags в образе) вместо ручных grep-цепочек. | 2601.19239: 37.5 % FP — shallow interprocedural, 19 % — source/sink; Anthropic tools: консолидация, high-signal output. | `core/tools/sandbox/search.py`; образ (`deploy/sandbox/Dockerfile`: universal-ctags). | M | Низкий; полиглотность — fallback на rg. |
| 14 | **Скоуп-дисциплина контекста хода**: `Changed files` — не список в промпте, а «N файлов, см. git_diff(stat=true)»; стабильный префикс системного промпта (не менять порядок секций между ходами) ради KV-кэша. | Manus KV-cache; Anthropic just-in-time retrieval. | `core/runner/executor.py::_event_prompt`, `core/lead/graph.py`. | S | Низкий. |
| 15 | **Опциональная динамика для проверки**: разрешить сабагенту-verifier запускать в песочнице **только** существующие тесты проекта / короткий скрипт против локального кода (без сети), результат — как квитанция; для C/C++ — сборка с `-fsanitize=address` при наличии тулчейна. | Anthropic (ASan), Revelio/PAGENT (sanitizer как оракул), Strix «NEVER rely solely on static… when dynamic validation is possible», GitHub autofix (rerun CodeQL как оракул). | Промпт `verifier`; `core/ports.py::Sandbox.run` уже есть; лимиты времени в `SubagentConfig.timeout_seconds`. | L | Высокий: исполнение недоверенного кода — только в изолированной песочнице без сети (OpenSandbox уже так), таймауты, запрет установки пакетов; фиксировать в спеке `security-analysis`. |

Порядок внедрения: 1 → 3 (чтобы мерить) → 2 → 4 → 8/7/9/10/14 (промпт и мелочи одним change) → 5/6 → 11/12/13 → 15. Пункты 1, 2, 4, 5, 6, 9, 15 меняют наблюдаемое поведение — через OpenSpec change с дельтой `security-analysis`/`lead-delegation`.

---

## 4. Источники

Первичные, проверены WebFetch 2026-09-04 (в скобках — что именно взято).

**Вендоры и лаборатории**

1. OpenAI — «Introducing Aardvark: OpenAI's agentic security researcher», 30.10.2025. https://openai.com/index/introducing-aardvark/ — **HTTP 403 при фетче**; текст взят из полного репоста на OpenAI Developer Community (10.11.2025): https://community.openai.com/t/aardvark-openai-s-agentic-security-researcher/1365837 (стадии, 92 %, 10 CVE).
2. OpenAI — Codex Security docs (research preview). https://learn.chatgpt.com/docs/security (редирект с developers.openai.com/codex/security; «validates high-signal issues in an isolated environment»).
3. Anthropic Frontier Red Team — «Evaluating and mitigating the growing risk of LLM-discovered 0-days», 05.02.2026. https://www.anthropic.com/research/zero-days (500+ валидированных, ASan, «no special instructions»).
4. Anthropic — «Assessing Claude Mythos Preview's cybersecurity capabilities», 07.04.2026. https://www.anthropic.com/research/mythos-preview (скаффолд, ранжирование файлов, агент-подтверждатель, 89 %/98 % severity, стоимость, Firefox 2 → 181).
5. Anthropic — «Claude Code Security», 20.02.2026. https://www.anthropic.com/news/claude-code-security («prove or disprove its own findings»).
6. Anthropic — GitHub Action `claude-code-security-review` (README). https://github.com/anthropics/claude-code-security-review (стадии, список исключаемых классов, опции).
7. Anthropic — «Effective context engineering for AI agents», 29.09.2025. https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
8. Anthropic — «How we built our multi-agent research system», 13.06.2025. https://www.anthropic.com/engineering/multi-agent-research-system
9. Anthropic — «Writing tools for agents», 11.09.2025. https://www.anthropic.com/engineering/writing-tools-for-agents
10. Manus (Yichao Ji) — «Context Engineering for AI Agents: Lessons from Building Manus», 18.07.2025. https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus
11. Google Project Zero — «From Naptime to Big Sleep», 01.11.2024. https://projectzero.google/2024/10/from-naptime-to-big-sleep.html
12. Google — «Google's latest AI security announcements» (Big Sleep, CVE-2025-6965), лето 2025. https://blog.google/innovation-and-ai/technology/safety-security/cybersecurity-updates-summer-2025/ («20 vulnerabilities» — только вторичные источники, не подтверждено первичным)
13. XBOW — «How XBOW Ranked #1 in Autonomous Penetration Testing», 24.06.2025. https://xbow.com/blog/top-1-how-xbow-did-it
14. Semgrep — «How we built an AppSec AI that security researchers agree with 96% of the time», 22.01.2025. https://semgrep.dev/blog/2025/building-an-appsec-ai-that-security-researchers-agree-with-96-of-the-time/
15. Semgrep — «Announcing an AI AppSec engineer that users agree with 95% of the time» (noise filtering, Memories), 22.01.2025. https://semgrep.dev/blog/2025/announcing-ai-noise-filtering-and-triage-memories/
16. GitHub — «Agentic autofix for code scanning alerts in public preview», 10.07.2026. https://github.blog/changelog/2026-07-10-agentic-autofix-for-code-scanning-alerts-in-public-preview/
17. Strix (usestrix/strix, Apache-2.0). https://github.com/usestrix/strix ; код — локальная копия `~/tmp/repos/strix` (`agent/tools/{threat_model,coverage,notes,todo,reporting,agents_graph}`, `agent/agents/prompts/system_prompt.jinja`).
18. LangChain docs — middleware (summarization), long-term memory, deepagents context engineering. https://docs.langchain.com/oss/python/langchain/middleware/built-in#summarization , https://docs.langchain.com/oss/python/langchain/long-term-memory , https://docs.langchain.com/oss/python/deepagents/context-engineering

**arXiv (abs/html)**

19. RepoAudit — Guo, Wang, Xu, Su, Zhang, 30.01.2025 (ICML 2025). https://arxiv.org/abs/2501.18160
20. VulAgent — Wang, Li, Li, Zhu, Jin, 15.09.2025. https://arxiv.org/abs/2509.11523
21. VulnAgent-R2 — Meng, Wu, Wang, 11.03.2026. https://arxiv.org/abs/2603.13384
22. VulnGym — Ji et al., 03.08.2026. https://arxiv.org/abs/2608.02001 (html: результаты)
23. LLM-based Vulnerability Detection at Project Scale — Li, Jiang, Chen, Xiong, 27.01.2026. https://arxiv.org/abs/2601.19239 (html: recall, SFDR, root causes)
24. Revelio — Hou et al. (Sen, Song, Wagner), 20.06.2026. https://arxiv.org/abs/2606.22263
25. PAGENT — Desai, Shafiuzzaman, Guo, Bultan, 08.04.2026. https://arxiv.org/abs/2604.07624
26. VulTrial (mock-court) — Widyasari et al., 16.05.2025 / rev. 03.12.2025. https://arxiv.org/abs/2505.10961
27. Refute-or-Promote — Agarwal, 21.04.2026. https://arxiv.org/abs/2604.19049
28. AEGIS — Fang, Ding, Cao, Yang, Xu, 21.03.2026. https://arxiv.org/abs/2603.20637
29. AgentAuditor — Yang et al., 10.02.2026 / rev. 03.09.2026. https://arxiv.org/abs/2602.09341
30. Reducing False Positives in Static Bug Detection with LLMs (industry, Tencent) — Du et al., 26.01.2026. https://arxiv.org/abs/2601.18844
31. LLM4PFA — Du et al., 12.06.2025. https://arxiv.org/abs/2506.10322
32. IRIS — Li, Dutta, Naik, rev. 06.04.2025. https://arxiv.org/abs/2405.17238
33. QASecClaw — Ameen, Alam, Islam, 03.05.2026. https://arxiv.org/abs/2605.01885
34. SAST-Genius — Agrawal, Ahi, 18.09.2025. https://arxiv.org/abs/2509.15433
35. CORRECT («Everything You Wanted to Know…») — Li et al., 18.04.2025. https://arxiv.org/abs/2504.13474
36. ZeroDayBench — Lau et al., 02.03.2026 (ICLR 2026 workshop). https://arxiv.org/abs/2603.02297 (html: таблица уровней)
37. CyberGym — Wang et al. (Song), 03.06.2025 / rev. 24.03.2026. https://arxiv.org/abs/2506.02548
38. CyberGym-E2E — Shi et al., 03.06.2026 (ICML 2026). https://arxiv.org/abs/2606.04460
39. SEC-bench — Lee, Zhang, Lu, Zhang, 13.06.2025 (NeurIPS 2025). https://arxiv.org/abs/2506.11791
40. CVE-Bench — Zhu et al. (Kang), 21.03.2025 / rev. 24.06.2025. https://arxiv.org/abs/2503.17332
41. Benchmarking Mythos-Linked Bug Rediscovery — David, Gervais, 17.05.2026. https://arxiv.org/abs/2605.17416
42. LLM-Based Agents for Software and Systems Security (survey) — Nie, Guo, Meda, Cai, 28.08.2026. https://arxiv.org/abs/2608.28490

Не фетчились (упомянуты по результатам поиска, без утверждений с числами): «Do Fine-Tuned LLMs Understand Vulnerabilities? … Semantic Trap» (arXiv 2601.22655), vEcho (2603.01154), ExploitBench (2605.14153), CyberEvolver (2605.26195).
