# UX audit — frontend (2026-09-04, ветка wt/ux)

Прошёл как новый пользователь по живому приложению: вход → builds → repositories (watch по URL) →
run agent → playground (timeline/agents/findings/chat/terminal) → dash → account. Одна строка на
пункт; статус `fixed` — исправлено в этой ветке, `deferred` — оставлено (причина в скобках).
Термины — CONTEXT.md: Сборка = build, Экземпляр Агента = agent, sandbox **connection** (куда и из
какого образа создавать) ≠ sandbox **instance** (живой контейнер конкретного агента).

## P0 — тупики и скрытые ошибки

- [fixed] Ошибка API (502 trigger «resolve master head: … no such host») уходила только в статус-бар: серый однострочник, обрезан, затирается следующим действием — теперь баннер над экраном с текстом бэкенда, HTTP-кодом и кнопкой «copy trace …xxxx» (`Shell.fail`, `ErrorBanner`).
- [fixed] Путь «подключил репо → агент работает» неочевиден: главная кнопка называлась «trigger run @ master», нигде не сказано, что создаст песочницу и поднимет агента — переименована в «❯ run agent @ <branch>» с подсказкой; на playground тоже «run agent @ <branch>».
- [fixed] Без Сборки (или без default и без подписки) «run» отвечал 202 с пустым `instanceIds`, UI писал «0 instance(s) raised» и молчал — теперь кнопка заблокирована с подсказкой-ссылкой «create a build / make default», а пустой ответ показывается как ошибка с объяснением.
- [fixed] Пустой дашборд/список репо ни к чему не вёл — onboarding-чеклист «llm connection → build (default) → connect repository» с галочками по факту и ссылками (`Onboarding` в ui.tsx, показывается пока хоть один шаг не закрыт).
- [fixed] Пустой журнал watch-репо говорил «push to the repository and the webhook delivers…» — у watch-репо вебхука нет; текст зависит от режима.

## P1 — терминология и вводящие в заблуждение подписи

- [fixed] «Почему Сборка привязана не к экземпляру песочницы?» — в таблице Сборок колонка «sandbox» → «sandbox connection», в дровере Сборки подпись «sandbox connection · where the agent's sandbox instance is created», подзаголовок секции объясняет разницу («a build points at one connection, never at an instance»).
- [fixed] Кнопка «+ instance» у sandbox-подключения создавала «ничейный» контейнер (used by nobody) — убрана: экземпляры создаёт hub при запуске.
- [fixed] Playground: «attach sandbox…» + «attach» и «+ create sandbox» — ручная привязка там, где она автоматическая — убраны; панель называется «sandbox instance · auto-created on run», остался только «kill» (для протухшего контейнера) с объяснением, что следующий запуск создаст новый.
- [fixed] Playground header / repo page / dash: «sandbox …» → «sandbox instance …», «none» → «none yet — created on run».
- [fixed] Список sandbox instances на builds был забит мёртвыми контейнерами (6 dead «used by nobody») — dead скрыты за кнопкой «show N dead», подзаголовок «live containers, created automatically per agent on run».
- [fixed] «watchers» (нет в глоссарии) → «agents» в панели репо, колонке таблицы, чате, аккаунте; «raise instance» → «raise agent» с title, что это подъём из чекпоинта.
- [fixed] В дровере Сборки «— first connection» ничего не объясняло — показывается имя первого подключения «(first — default)» либо «none — add … first».
- [fixed] «assign build» в дровере подключения репо на самом деле создаёт подписку — подпись «subscribe build», пустой вариант «none — served by the default build».
- [fixed] Activity-лента на английском UI писала «ход начался / ход упал / Находок:» — переведено.
- [fixed] Статус-бар «0 repos · 0 running» не обновлялся после подключения репо — счётчики перезагружаются при смене маршрута; баннер ошибки при этом сбрасывается.
- [fixed] Dash: «no findings filed by this instance» на общем дашборде; «no instances — connect a repository and a build» без ссылки; runners = 0 не помечалось как блокер.
- [fixed] Пустые состояния builds/llm/chat/terminal вели в тупик («none.», «no watcher», «create it on the timeline tab») — переписаны в «что сделать дальше».
- [fixed] Карточка «default build: — none» не объясняла последствия — «without a default build, repos without a subscription never run» + ссылка «create a build →»; в таблице репо без Сборки «no build — nothing will run».
- [deferred] Ошибка запуска в самой песочнице («git clone … remote helper 'https' aborted») видна только в agents-таб / ⚙-строке timeline; а header остаётся «running» до idle-таймаута (это статус Экземпляра, не хода). Нужен журнал статусов События (PLAYGROUND-TODO §2) — бэкенд.
- [deferred] Memory preset — свободный текст, неизвестное имя падает только на запуске (нет эндпоинта со списком пресетов — бэкенд).

## P2 — мелочи

- [deferred] Нет полей ref/commitSha у «run agent» хотя trigger их принимает (обход DNS-падения resolve HEAD) — добавить, если понадобится.
- [deferred] Чат теряется при перезагрузке (нет history-эндпоинта, PLAYGROUND-TODO §3).
- [deferred] Playground поллит 6 эндпоинтов раз в 5 с — SSE статуса Экземпляра (PLAYGROUND-TODO §6).
- [deferred] Подтверждения через `window.confirm` — стилистически выпадают из макета, но работают.
- [deferred] Слоты раннера считаются по running-Экземплярам текущего пользователя (PLAYGROUND-TODO §4).
- [ok] Горизонтальный overflow на builds/playground при ~1300px — не подтвердился (scrollWidth == innerWidth; артефакт масштабирования скриншота).

## Среда (не фронт, замечено по пути)

- hub не резолвит `api.github.com` из своего процесса (DNS) — trigger без commitSha падает 502; connect по URL при этом прошёл (флап DNS).
- Образ песочницы `git-agent/sandbox:strix`: `git clone https://…` → «remote helper 'https' aborted session» — ход падает на подготовке репо.
