# Aperture: состояние проекта на 26 октября 2026

## Короткий вывод

Aperture уже соединяет прежние идеи Sentinel, owner-set pricing и Solana с нынешним gateway, compute worker, inference, SDK/MCP и восстанавливаемыми workflow. Это единый локально проверяемый MVP, а не две отдельные оболочки. Полностью готовым децентрализованным рынком проект пока не является: каталог исполнителей управляется оператором, GPU не поддержан, а текущая версия on-chain выплаты исполнителю ещё не подтверждена живой транзакцией.

Локальный `HEAD` по-прежнему `2ec06a9` от 24 октября 2026 года. Первичный срез этого обзора насчитал 104 изменённых или новых пути; на последнем срезе после последующих UI-изменений — 115. Изменения не входят в `HEAD`, и многие существовали до текущих проходов. Начальная таблица фиксирует первый срез; более поздние датированные разделы ниже обновляют результаты проверок. Проверки относятся к локальной рабочей копии, если отдельно не указано иное.

## Как проект менялся

| Дата | Коммит или этап | Что появилось | Как это связано с нынешним продуктом |
|---|---|---|---|
| 3 апреля | `a718ad6` | FastAPI, frontend, Anchor и исходная идея compute gateway. | Начало единого слоя запросов, исполнения и платежного протокола. |
| 6 апреля | `e44dea8` | Quantum Pricing, APS, импорт скрипта и compute dashboard. | Исторические расчёты остались в контексте, но больше не определяют цену задачи. Тариф публикует владелец worker. |
| 7 апреля | `d659fc8` | Gemini Sentinel, проверка кода и экран Robin Hood pricing. | Sentinel вернулся в Studio как проверка конкретного исходника. Его вывод — дополнительная проверка, а не гарантия безопасности и не решение о запуске. |
| 24 сентября | `8bd5c54` | Treasury-backed payment channels. | Это историческая схема расчёта. Сохранённый Devnet платёж относится к старому запуску, а не доказывает текущую выплату worker. |
| 26 сентября | `819e952` | Пересборка workspace; старые Provider/Gateway экраны были удалены. | В последующих изменениях снова собраны общая Studio, consumer/provider роли и выбор исполнителя. |
| 4 октября | `e6213b8`, `13f0ce0` | Agent workspace, файлы результата, Studio и система motion. | Нынешняя оболочка сохранила эти поверхности и добавила повторные переходы страниц. |
| 7 октября | `c2db95a` | Aperture v2, Python SDK и MCP. | Клиенты и агентские инструменты используют тот же gateway. |
| 24 октября | `2ec06a9` | Воссоединение inference и compute workspace. | Базовая интеграция: общий gateway, подписи, бюджеты, worker и общий интерфейс. |
| 26 октября | текущая локальная работа | Смешанные Model → Python → Model workflow, переносимый Sentinel bundle, UI polish и явный путь для обновления существующей Devnet-программы. | Последние изменения ещё локальные; они не опубликованы в `main`. |

Исторические даты взяты из локальной Git-истории. Сводка по интеграциям хранится также в [historical-integration.md](historical-integration.md).

## Как продукт работает сейчас

1. **Владелец worker задаёт тариф.** Клиент подписывает quote с выбранным worker и его ставкой. DeepSeek не выставляет цену и не меняет тариф.
2. **Sentinel проверяет исходник отдельно.** DeepSeek доступен только для фиксированной проверки конкретного Python-исходника. Его замечания помогают владельцу принять решение, но запуск отдельно ограничивает gateway policy и подтверждает владелец.
3. **Python, inference и workflow используют общую инфраструктуру.** Запрос проходит через gateway, согласование лимитов, выбор worker, выполнение и квитанцию. Модельные ответы могут стать явно привязанным входом следующего шага workflow.
4. **SDK и MCP подключаются к той же цепочке.** Задачи можно возобновлять по принятой записи, не создавая повторный запуск. Выбор worker закрепляется в авторизации.
5. **Solana остаётся опциональным путём.** `OFF_CHAIN` означает реальное локальное исполнение без оплаты в SOL. Код контракта `0.5.0` направляет подтверждённую плату за новую задачу целиком указанному worker, но сам исходник не доказывает, что эта версия развернута.

Каталог предложений пока операторский; оплаты внешнего API модели идут отдельно; GPU исполнение, permissionless discovery, ZK-доказательство вычисления и доказательство правильности ответа не входят в работающий MVP. Подписи связывают задачу, автора и результат, но сами по себе не доказывают честность или правильность удалённого worker.

## Что проверено в этой рабочей копии

| Проверка | Результат | Что она подтверждает |
|---|---:|---|
| Frontend tests | 88 passed | Логика интерфейса и протокола, source-bound Sentinel, проверка структуры и строк отчёта, recovery, route selection и состояния identity mismatch. |
| Frontend lint/build | passed | Код собирается и проходит линтер; Vite обработал 414 модулей. |
| SDK/MCP tests | 52 passed; 6 source-review passed after prompt update | Клиентские и MCP-контракты проходят локальные тесты. Последние 6 проверок подтвердили идентичность Sentinel prompt в SDK и gateway. |
| Backend tests | 131 passed, 2 skipped | Два теста требуют Docker; Docker CLI на этой машине отсутствует. Gateway проверяет привязку Sentinel к owner, исходнику, подписанному `inference_proxy` результату, receipt hash и строкам отчёта. GitHub Actions содержит Docker build и эти проверки, но успешный запуск Actions для текущего дерева не подтверждён. |
| Remote status для `2ec06a9` | Vercel: success | Это статус последнего сохранённого commit; он не проверяет сегодняшние 98 локальных изменений. GitHub Actions result для текущего дерева не подтверждён. |
| Rust tests and checks | 17 tests passed; `cargo check --locked --offline` and `cargo fmt --check` passed | Проверена нативная сборка логики; Cargo показывает предупреждения Anchor о `cfg` значениях. Это не SBF сборка, не запуск Solana validator и не Devnet payout. |
| SBF build and local validator | Не запускались для текущего дерева | `anchor` и `solana-test-validator` отсутствуют в окружении. Исходный код и нативные Rust тесты не доказывают развертывание программы или выплату в сети. |
| Смешанный локальный workflow | 13 задач, 8 синтетических model ответов, 0 платежей | SDK/MCP/owner flow и локальные транспортные переходы; synthetic provider fixture не является живым ответом DeepSeek. |
| Local CPU preview smoke | passed | Preset `Numerical analysis` исполнен зарегистрированным `NODE-CPU-PREVIEW` по опубликованному тарифу 1 000 lamports/s; SDK проверил подписанную квитанцию. Settlement `OFF_CHAIN`, платежа в SOL не было. |
| Live DeepSeek request | Не запускался | Ключ теперь находится только в игнорируемом `backend/.env`. Исходный gateway на `8000` был поднят до добавления ключа и по-прежнему публикует 0 model offers. Изолированный preview на `24141` после перезапуска показал `ready`, `OFF_CHAIN`, DeepSeek `deepseek-flash` в `/sentinel/providers`, одного доступного inference worker и минимальную цену владельца worker 1 000 lamports/s. Upstream запрос не отправлялся: auto-review остановил запуск smoke-test, потому что он передаёт исходник внешнему платному API; нужен явный ответ владельца на передачу конкретного тестового исходника. |
| Browser QA | Studio 1440×1000, 390×844, 708×768, 1280×720; Agent workflows 1274×720 | Sentinel prompt фиксирован и read-only. После изменения кода панель просит открыть проверку заново; исходник сменился в реальном браузере. Код сбрасывает draft quote и блокирует новый quote/sign для устаревшего review. Устаревшее состояние объявляется как polite live status. Эти quote/sign блокировки не были exercised: provider отсутствует. Дисклеймер уточняет: quote-запрос передаёт prompt gateway, а подпись и submit разрешают передачу выбранной модели; также указаны отсутствие исполнения, отдельный API-биллинг и advisory-only `SAFE`. Панель появляется за 220 мс при обычном motion; при reduced motion анимации нет. Workflow stepper показывает достигнутый шаг тональной заливкой, текущий — основным фиолетовым, а connector — primary с 220-мс переходом. Model → Python → model stages используют `aperture-graph-in` 360 мс со stagger 0/60/120 мс. Холодная загрузка Agent Passports показала `role=status` и спиннер 1.2 с; этот спиннер и sequence motion работают только при `prefers-reduced-motion: no-preference`. Каталог 1280×720 показал одну активную локальную CPU-мощность с ставкой 1 000 lamports/s; переход `Use this worker` открыл Studio и закрепил `NODE-CPU-PREVIEW` в селекторе без quote/sign. CSV signer mismatch указывает причину и путь восстановления: unified preview на `127.0.0.1:3000` выставляет matching local signer; кнопка открывает Getting started. В combined workflow показан Model → Python → model, отсутствие model offers и доступный `NODE-CPU-PREVIEW`; кнопка настройки открывает Getting started без отправки inference request. Свежая вкладка прошла без console errors/warnings. Состояния offline, draining и ошибочной ставки покрыты тестами без живого offline worker. В локальном gateway видны 0 model offers, поэтому DeepSeek-review не запускался. JS/console errors нет, горизонтального overflow нет. |
| Model setup navigation | Passed | Кнопка из Sentinel открывает Getting started и показывает настройку модели. Guide уточняет: временную PowerShell-переменную и `start_preview.bat` нужно запускать в одной сессии; для двойного щелчка ключ сначала кладут в `backend/.env`. Ключ не вводился, model request не выполнялся. |
| PowerShell deployment preflight | syntax/key checks passed | Временный CLI config позволил пройти проверку локальных ключей; внешний RPC вызов остановлен Windows socket policy. Транзакция не запускалась. |

**Визуальный проход 26 октября:** в браузере при 1274×720 смешанный сценарий теперь показывает связанный порядок Model → Python → Model, отдельные номера шагов и файлы `response.txt` / `analysis.json`. Линии соединения появляются последовательно за 240 мс только при `prefers-reduced-motion: no-preference`; при reduced motion действует общий запрет анимации. CSS складывает маршрут в вертикальную колонку при ширине до 640 px. Повторная проверка Agent workflows не показала console errors или warnings.

**Уточнение Sentinel 26 октября:** в изолированной Edge/Playwright вкладке открыл Studio → `Review with AI Sentinel`, используя локальную браузерную fixture с одним DeepSeek offer и inference worker. В source-bound панели отдельно видны передача исходника gateway, advisory-only роль проверки и разделение тарифа worker / API-счёта оператора. При 1274×720 и 390×844 горизонтального overflow нет; console errors/warnings не зарегистрированы. В этой проверке API-ответы были fixture: запросы `/inference/quotes` и `/execute` не отправлялись, кошелёк не подключался, DeepSeek не вызывался. Это доказывает только отрисовку и переход панели, не live-проверку модели.

**Проверка формата Sentinel:** frontend принимает отчёт только с допустимым verdict, причиной и массивом до 20 конкретных findings; строки должны существовать в проверенном исходнике. Противоречивый `SAFE` с findings уровня low и выше понижается до `REVIEW`, а некорректный формат требует ручной проверки. Это ограничивает некорректное отображение ответа модели, но не доказывает точность её анализа и не разрешает выполнение.

**Gateway identity 26 октября:** реальный локальный `/health` на `127.0.0.1:8000` сообщал `ready`, `OFF_CHAIN`; program ID совпал с фронтендом, но signer pin фронтенда отличался от signer gateway. Раньше шапка называла его `Gateway connected`; теперь показывает amber `Gateway signer mismatch`, а Overview объясняет, что до подписи нужно открыть unified local preview или исправить pin. При 1440×1000 и 390×844 overflow и console errors/warnings не обнаружены; кнопка `Setup guide` открыла Getting started.

**Overview polish 26 октября:** в текущем Vite preview 3041 обнаружена пустая правая колонка hero: схема `MODEL · CPU · RECEIPT` уже была в JSX, но стиль workspace скрывал её. Схема снова отображается на desktop; на мобильном она скрыта, чтобы hero оставался компактным. Удалено бесконечное idle-вращение; вместо него — короткий entrance при открытии страницы и небольшая реакция на hover, оба соблюдают `prefers-reduced-motion`. Playwright через установленный Edge проверил 1440×1000 и 390×844: горизонтального overflow нет, в актуальных строках отображаются `0 offers` и `1 worker`, hover меняет transform, переход `AI Sentinel → compute` открывает `#sentinel` / `Compute Studio`; при reduced motion CSS-анимации выключены, активных Web Animations нет. Ошибок приложения нет. Сеть браузера блокирует внешний импорт DM Sans из стилей Solana Wallet Adapter (`ERR_NETWORK_ACCESS_DENIED`); локальный Roboto загружен и используется как fallback. Это UI-проверка, она не исправляет уже известный signer mismatch preview 3041.

**Workspace detail 26 октября:** новый Playwright-проход прошёл по 10 desktop маршрутам (`overview`, `studio`, `inference`, `sentinel`, `workflows`, `storage`, `agents`, `network`, `provider`, `guide`) и по пяти mobile маршрутам (Overview, Studio, Workflows, Network, Guide) при ширине 390 px: JS exceptions и горизонтального overflow не обнаружено. В Studio пустой Output был одной строкой в большой пустой панели; теперь он явно помечен `No run output yet` с кратким объяснением, когда появятся события worker. Иконка и пояснение появляются коротко и по очереди; Playwright подтвердил `animation: none` и `transition: 0s` при `prefers-reduced-motion`. Новое состояние видно в тёмной Material 3 теме на desktop/mobile; браузерная проверка подтвердила разметку и отсутствие переполнения, но реальный запуск здесь не выполнялся. Прямой локальный API-check: gateway `ready`, `demo_mode=true`, 1 Python worker и 0 model offers; preview 3041 по-прежнему сообщает `Gateway signer mismatch`.

**Путь настройки модели 26 октября:** Getting started разделяет два маршрута карточками `Quick start · local preview` и `Existing gateway · operator setup`: объединённый `start_preview.bat` и отдельный inference-only worker. Пояснение Sentinel теперь явно говорит, что вывод advisory-only, ставку задаёт владелец worker, а Python запускается отдельной подписанной задачей. Системный Edge через Playwright (Browser plugin недоступен) проверил переход `Compute Studio → Getting started` и мобильное меню `More pages → Getting started`; при 1440×1000 и 390×844 появились обе карточки без горизонтального overflow. Консольных JS-исключений нет. Внешняя загрузка DM Sans с `fonts.googleapis.com` заблокирована сетевой политикой; применяется локальный Roboto. Скриншоты лежат во временной QA-папке, в Git они не добавлялись.

**Design и motion audit 26 октября:** все десять маршрутов (`overview`, `studio`, `inference`, `sentinel`, `workflows`, `storage`, `agents`, `network`, `provider`, `guide`) открыты через системный Edge на 1440×1000 и 390×844; ширина документа совпала с viewport на каждой странице. На мобильных маршрутах JS-исключений и console errors нет. Desktop Overview повторно проверен после полной отрисовки; прежний Material 3 фиолетовый стиль, логотип, orbit-визуал и тёмный редактор сохранены. В отдельном реальном UI-переходе `Studio → Overview → Studio` изменённый текст редактора сохранился; с `prefers-reduced-motion: reduce` активных анимаций было 0, `data-entering` отсутствовал. Это доказывает только проверенные локальные UI-состояния, не live gateway execution.

**DeepSeek preflight 26 октября:** актуальная официальная документация по-прежнему указывает `deepseek-flash` для OpenAI-совместимого `POST /chat/completions`; тарификация считается по входным/выходным токенам. Изолированный launcher запустил локальные CPU/inference workers и Gateway на `24141`, подтвердил рекламируемый Sentinel offer и rate, после чего процессы остановлены, временная директория и ephemeral authority удалены. Фактический внешний запрос не был выполнен: автоматическая проверка разрешений отклонила `--check`, поскольку он передаёт source review input внешнему платному провайдеру. Это подтверждает конфигурацию каталога и маршрута, но не валидность ключа, качество анализа, live receipt или безопасное поведение модели.

Отдельный короткий запуск официального `inference_preview.py` на `23141/23181` подтвердил recovery path: `ready`, `OFF_CHAIN`, program и signer совпали, подключён один `NODE-CPU-PREVIEW` по 1 000 lamports/s; Agent workflows показывал обычный шаг подключения wallet, без красного signer-блока. Ключ модели отсутствовал; wallet, upload, quote, execute и вызов модели не запускались. Процессы и временные ключи QA остановлены и удалены. Открытый Vite preview на `3041` по-прежнему настроен на другой signer и должен пользоваться объединённым launcher-путём.

**Реальный локальный acceptance и восстановление 26 октября:** официальный combined preview запущен на `24141/3042`; интерфейс подтвердил правильный gateway signer. Через Studio выполнена одна подписанная числовая CPU-задача: `Mean root score: 29.817865`. В SQLite осталась ровно одна задача со статусом `completed`; owner-подпись quote, подпись worker attestation, подпись gateway receipt, подписанные поля и SHA-256 результата проверены независимо. После остановки и повторного запуска того же preview с тем же state API `GET /result` вернул HTTP 200, тот же результат и тот же receipt hash; второй job не создавался. Worker `NODE-CPU-PREVIEW` публиковал 1 000 lamports/s. Состояние было `OFF_CHAIN`, execution backend — `trusted_local`, `/stats` показал `0 SOL` и один завершённый job. Это подтверждает восстановление сохранённого локального результата и подписи, но не Docker-изоляцию, удалённое исполнение или Devnet-выплату. DeepSeek-запрос не отправлялся.

**Проверка цены worker 26 октября:** в живом локальном `Provider Workspace` введён operator credential; UI изменил ставку с 1 000 на 1 234 lamports/s и вернул её на 1 000. Неправильный `0` API отклонил с HTTP 422. Публичный `/workers` и созданная без исполнения quote показали `1 234`; canonical message quote закрепил те же ставку и `NODE-CPU-PREVIEW`. Новая задача не создавалась. `backend/test_worker_market.py`: 10/10 тестов прошли, включая публикацию тарифа, границы ввода и закрепление worker/rate в quote. Playwright: Provider Workspace подключился, показал оба изменения, страница не выдала JS-ошибок; снимок сделан в `C:\Users\megumin\AppData\Local\Temp\aperture-playwright-qa-20261022\provider-rate-published-20261026.png`.

**Связка цены и покупки 26 октября:** после публикации 1 234 lamports/s в Operator Workspace открыл Studio, подключил ephemeral Temporary key и запросил quote для Numerical analysis. Consumer UI показал выбранный `NODE-CPU-PREVIEW`, ставку `0.000001234 SOL/s` и лимит; в gateway появилась quote с теми же worker/rate. Число задач осталось 1, `Accept quote & sign` не нажималась, задача не запускалась, а ставка вернулась на 1 000 lamports/s. Temporary key исчез при закрытии браузера. Снимок: `C:\Users\megumin\AppData\Local\Temp\aperture-playwright-qa-20261022\worker-price-to-consumer-quote-20261026.png`.

**Проверка launcher и мобильного Provider Workspace 26 октября:** когда старый gateway занимал `8000`, официальный preview без заданных портов выбрал отдельный API-порт `64459` и UI `3000`, корректно напечатал адрес `http://127.0.0.1:3000/#studio`; Edge подтвердил `Gateway connected`, правильную пару signer/API, отсутствие JS-ошибок и горизонтального overflow на 1440 px. Первая отложенная отрисовка снимка была пустой; после ожидания завершения entrance-перехода экран отобразился правильно. Подключённый Provider Workspace на ширине 390 px имел `scrollWidth=390`, форма ставки помещалась, JS-ошибок не было. Скриншоты находятся в той же временной QA-папке и в Git не добавлены.

**Офлайн-аудит Sentinel 26 октября:** 11/11 выбранных backend-тестов прошли: DeepSeek присутствует только в Sentinel catalog, review quote привязан к конкретному source, inference-worker не забирает произвольный Python, а проверка и последующее исполнение идут разными задачами с отдельной подписью. `test_sentinel_review` проверяет формат и ссылку на owner/source/receipt. Дополнительно набор `test_preview_ports test_preview_env test_worker_market test_sentinel_review` прошёл 24/24. Все эти Sentinel-провайдерские проверки используют локальные fixtures/mock endpoints; ни один реальный запрос к DeepSeek не отправлялся.

**Автовыбор портов 26 октября:** `scripts/inference_preview.py` теперь сохраняет привычные `8000/3000`, если они свободны; при занятом порте выбирает свободный loopback-порт и выводит фактический адрес, а занятый порт, переданный явно, отклоняет с инструкцией. Проверка занятого `8000` прошла на реальном запуске combined preview. Старый сервер на `3041/8000` не изменялся и не останавливался; при запуске с ним следует открывать именно адрес, напечатанный `start_preview.bat`.

Скриншоты текущей фиолетовой Material 3 темы — `aperture-sentinel-source-binding-2026-10-26-desktop.png`, `aperture-sentinel-stale-source-2026-10-26.png` и `aperture-sentinel-source-binding-2026-10-26-mobile.png` — сохранены в папке Codex visualizations; новые AI-изображения не добавлялись. Для Overview дополнительно проверены снимки light desktop и dark mobile; они остались во временной QA-папке Windows.

## Studio motion polish — 26 октября

Убрана бесконечная пульсация всей busy-плашки: она дублировала вращающийся статусный значок и отвлекала во время долгого запуска. При переходе между этапами текущий шаг теперь получает один короткий акцент в 320 мс. Он действует только при `prefers-reduced-motion: no-preference`; общий reduced-motion override отключает его полностью.

Проверка в Edge на открытом локальном preview: Studio 1440×1000 и 390×844, ширина документа совпала с шириной viewport, горизонтального overflow нет. В обычном режиме у активного шага `aperture-step-current` / `0.32s`, при reduced motion — `animation: none` / `0s`; busy-контейнер не запускает повторную анимацию. JS-исключений нет. В QA явно блокировался внешний трафик, поэтому импорт DM Sans с `fonts.googleapis.com` дал ожидаемый сетевой отказ; используется локальный Roboto. Preview `3041` всё ещё показывает прежнее несовпадение signer и пригоден только для визуальной проверки.

Frontend: `npm test` — 88/88, `npm run lint` — успешно. Обычная команда `npm run build` остановилась до компиляции: esbuild отказал в доступе к `../../../..` при чтении Vite config в этом sandbox. Production build с теми же Vite 5.4.11, React plugin, aliases, defines и chunk policy успешно выполнен через programmatic API: 414 модулей собраны во временный каталог.

## Роли AI Sentinel и тарифа — 26 октября

Промпт Sentinel просит модель искать только риски безопасности исходника; он запрещает оценивать цену, производительность и время, запускать код или выдавать гарантию безопасности. Gateway привязывает приложенный review к владельцу, исходнику и хранимому завершённому inference task с совпадающим receipt hash. Вердикт `SAFE`, `DANGEROUS` или `REVIEW` остаётся advisory и сам по себе не разрешает и не блокирует задачу. В Studio теперь явно сказано, что Sentinel не исполняет код и не задаёт цену; результат `SAFE` не гарантирует безопасность.

Отдельно `issue_quote` выбирает worker и берёт `published_worker_rate`; эвристика сложности не меняет ставку. Жёсткое отклонение выполняет статический AST source policy для распознанных запрещённых конструкций — это не DeepSeek и не доказательство изоляции. Сообщение отказа теперь честно называет именно статическую политику. Upstream API billing модели также отделён от ставки worker. Backend `test_security`, `test_api_security`, `test_sentinel_review`: 47/47 прошли; живой вызов DeepSeek не запускался.

## Solana: старое доказательство и новая версия

В [presentation-evidence.json](presentation-evidence.json) хранится реальный Devnet запуск от 27 сентября 2026 года: списано 3 200 lamports, квитанция и подтверждение транзакции записаны 5 октября. Исполнение тогда было `trusted_local`, без Docker. Этот артефакт подтверждает тот прежний платёжный путь, но не новый контракт `0.5.0`, который направляет средства worker.

Read-only проверка текущего Devnet в этой среде не завершилась: запуск Python вернул `Access is denied`; Node вернул `fetch failed`, а PowerShell получил отказ Windows при открытии исходящего RPC-сокета. Agave CLI изначально требовал системный home directory; preflight теперь передаёт ему временный config-файл и проходит локальные проверки ключей, но сеть всё равно недоступна. Поэтому текущее состояние RPC, код программы в сети, upgrade authority и новая выплата здесь не проверены.

В `scripts/deploy-devnet.ps1` добавлен безопасный явный режим `-Upgrade`: preflight показывает текущий authority и проверяет совпадение с настроенным signer. Обычный вызов остаётся только просмотром; обновление требует явных `-Upgrade -Publish`. Сама транзакция в этой работе не запускалась. Официальная документация Solana описывает обновление loader-v3 через существующий upgrade authority и тот же `solana program deploy` путь: [Program Deployment](https://solana.com/docs/core/programs/program-deployment), [Deploying Programs](https://solana.com/docs/programs/deploying).

## Что ещё требует внешней проверки

- **DeepSeek Sentinel:** ключ загружен в локальный preview, а provider catalog показывает модель доступной. Запрос не отправлялся. Для настоящего advisory выбранный исходник должен быть передан `api.deepseek.com`; это может тарифицироваться. Фикстуры и локальный provider статус не подтверждают ответ живой модели.
- **Solana payout:** текущий Devnet RPC недоступен, а `anchor` и `solana-test-validator` не установлены. Нативные Rust тесты подтверждают только локальную контрактную логику. Проверка program ID, deployed bytes, upgrade authority и новой выплаты worker остаётся незавершённой; никаких транзакций в этой работе не отправлялось.

Для обновления программы или отправки платежа нужно отдельно просмотреть точный program ID, authority и сумму до подписи. Сохранённый старый платёж от 27 сентября относится к предыдущему контрактному потоку и не закрывает эти проверки.

## Контраст и объединённый локальный preview — 26 октября

В `frontend/src/Console.css` 16 оставшихся текстовых стилей переведены с `#786787` на `var(--console-muted)`. Старый цвет давал около 3.65:1 на тёмной поверхности. Браузерный скан восьми основных страниц в тёмной и светлой темах не обнаружил видимого обычного текста ниже 4.5:1; отдельно проверен режим `prefers-reduced-motion`: активных анимаций нет, переход страницы имеет `animation: none`.

В Edge поднят объединённый preview с изолированным временным состоянием: UI `http://127.0.0.1:3000/#studio`, API `http://127.0.0.1:61344` (порт 8000 занят прежним gateway). UI показал `Gateway connected`, несовпадения signer нет. В локальном `backend/.env` обнаружен настроенный DeepSeek без вывода значения ключа; `/sentinel/providers` вернул `aperture-deepseek` / `deepseek-flash` и одного доступного worker. Через `ApertureClient` выполнена реальная локальная CPU-задача `print(6 * 7)`: gateway принял owner-подписанную квоту, worker вернул `42`, SDK проверил подпись receipt; тип settlement — `OFF_CHAIN`, оплата и chain-запрос не выполнялись. Это подтверждает локальную конфигурацию и регистрацию worker. Запрос к DeepSeek не отправлялся, качество ответа и advisory по реальному source не проверены.

Edge QA: Overview, Studio, Workflows, Storage, Agents, Network, Provider и Guide открылись в полном состоянии при 1440×1000 и 390×844; ширина документа совпала с viewport, JS-исключений нет. Дополнительная матрица из 72 проверок этих страниц на ширинах 320, 360, 390, 640, 641, 768, 860, 1024 и 1440 px не обнаружила горизонтального переполнения. Внешние запросы браузера блокировались, поэтому шрифт мог перейти на локальный fallback. Frontend: `npm test` — 88/88, `npm run lint` — успешно. Backend `unittest discover` — 131 успешно, 2 Docker-теста пропущены без явного Docker-режима; SDK — 52 успешно; Rust `cargo test --locked --offline` — 17/17. Cargo выдал предупреждения Anchor о `cfg(anchor-debug)`. `solana-test-validator` и Anchor CLI не установлены, поэтому локальный validator test и Devnet-проверка не выполнены. Production build собран программным Vite API: 414 модулей, выход в отдельную временную папку. Стандартный загрузчик Vite config по-прежнему блокируется sandbox при чтении `../../../..`. Скриншоты QA хранятся во временной папке `%TEMP%\aperture-browser-qa-20261026`.

## Сквозные проверки workflow — 26 октября

Тестовые launcher-ы `scripts/demo_workflow.py` и `scripts/preview_workflows.py` теперь выставляют детерминированную тестовую ставку для локального worker и ждут, пока worker появится в каталоге как online, accepting и priced. Это настройки только синтетических прогонов; тарифы реальных provider-ов не менялись.

- `demo_workflow.py --rows 1000`: пройдены admission, восстановление после намеренного прерывания, выполнение двух задач и проверка артефактов.
- Расширенный сценарий на 17 000 строк с owner handoff, regional CSV, console workflow и сравнением с локальным Python завершился; итоги и байты совпали. Прямое локальное выполнение быстрее, но оно не проходит gateway, auth, receipt, recovery и изоляцию, поэтому его время не является честным сравнением производительности.
- `check_mixed_workflow.py`: Model → Python → Model, 8 ответов локальной model fixture, восстановление без дублирования, сверка Unicode-статистики, отклонение изменённого исходника. Внешний AI provider не вызывался.
- `check_workflow_cancel.py`: отмена через SDK и background controller останавливает последующие задачи и освобождает storage.
- `check_mcp_stdio.py`: 27 MCP tools, owner-assigned workflow, три шага, replay/resume и точное сохранение байтов; storage очищается после выполнения.
- `check_workspace_restart.py`: два перезапуска, восстановление промежуточных и конечных файлов из journal без повторных задач.
- `check_exported_plan.py`: 17 CSV batches, 20 задач, два merge шага, экспортированный план готовится отдельно от admission, replay повторно использует результаты.

Это локальные end-to-end проверки на OFF_CHAIN preview и синтетической model fixture. Они не подтверждают live DeepSeek, Solana settlement, удалённую GPU-ёмкость или запуск GitHub Actions для текущей рабочей копии.

## Motion polish: входы и состояния ожидания — 26 октября

Убрал бесконечное мигание статуса готового gateway: зелёная точка теперь даёт один короткий сигнал при появлении состояния (`520 ms`), верхний HUD-контур — один мягкий импульс (`560 ms`). Пока gateway стабильно подключён, индикаторы не продолжают пульсировать.

Вход на Overview теперь повторно запускает небольшую последовательность схемы Model → Compute → Receipt при каждом возвращении на страницу. Два кольца появляются за `260/280 ms`, центр — за `240 ms`, подписи — за `180 ms` с задержками `50/95/140 ms`; вся схема завершает движение до окончания `340 ms` перехода страницы. Все статичные состояния совпадают с концами keyframes. Global `prefers-reduced-motion` продолжает выключать анимации.

Browser QA через встроенный browser: переход Studio → Overview повторно запускал ожидаемые имена анимаций и задержки; после `400 ms` атрибут входа снимался. На каждом из восьми маршрутов после входа и завершения коротких переходов не было видимых бесконечных анимаций. При `1440×1000` и `390×844` страницы не переполняли viewport; на мобильном Overview `documentWidth=385` при viewport `390`. Browser console errors/warnings: `0`. Не запускал задачу и не отправлял запрос модели.

После этой правки повторно прошли frontend tests `88/88` и ESLint. Стандартный `npm run build` всё ещё блокирует esbuild при чтении `../../../..` в sandbox; прямой Node API с настоящим `vite.config.js` собрал те же `414` модулей в `%TEMP%\aperture-vite-motion-qa-20261026`.

## Provider и Storage: ошибочные и пустые состояния — 26 октября

В светлой теме просмотрены Provider и Storage при `1440×1000` и `390×844`. Storage без подключённого кошелька показывает пустое защищённое состояние и действие подключения; горизонтального переполнения нет. Плашка временного ключа теперь показывается только при фактическом подключении адаптера, а не просто после его выбора.

На Provider отправлен синтетический неверный credential в объединённый локальный preview (`127.0.0.1:61344`): gateway ответил `401 Invalid worker credentials`. До исправления компонент оставлял ошибочную сессию с надписью `Operator · qa-missing-worker`, скрывал форму и предлагал только Refresh/Disconnect. Теперь `401` сбрасывает операторскую сессию и временный токен, сохраняет введённый ID, возвращает форму, а сообщение стоит над ней. Браузер подтвердил видимую ошибку на мобильном размере, пустое поле токена, отсутствие строки сессии и ширину документа `385 px` при viewport `390 px`. Неверные данные были синтетическими и отправлены только локальному gateway.

Проверена архитектурная граница из текущего решения продукта: DeepSeek доступен только в каталоге AI Sentinel с фиксированной проверкой безопасности исходника; он не выставляет цену и не разрешает выполнение. Quote использует опубликованную ставку worker; upstream API billing модели отдельно оплачивает оператор. Это advisory-проверка, а не гарантия безопасности.

После исправлений `npm test` — `88/88`, `npm run lint` — успешно. Обычный `npm run build` блокируется esbuild при доступе к `../../../..` в sandbox. Прямой Vite API с `configFile:false`, настоящим `vite.config.js` и отдельным временным `outDir` собрал `414` модулей успешно. Повторный запуск выбранных Python-тестов в этой сессии не стартовал: Windows вернул `Access is denied` для существующего `backend/venv/Scripts/python.exe`; команды `python` и `py` в `PATH` отсутствуют. Более ранние результаты backend-тестов перечислены выше отдельно и не считаются повторной проверкой этого изменения.

**Этот этап закрыт ниже:** OFF_CHAIN signer больше не блокирует цену и запуск; реальный UI quote, выполнение Python-задачи, проверка receipt и отсутствие on-chain платежа подтверждены в следующем разделе.

## OFF_CHAIN signer и receipt payment status — 26 октября

Проверка реального окна Studio на `http://127.0.0.1:3041/#studio` выявила неверное применение Devnet signer pin к локальному режиму: `frontend/.env.local` содержит Devnet public pins, а gateway API на `127.0.0.1:8000` работает как `demo_mode=true` с отдельным OFF_CHAIN signer. Исправлено поведение по сети: локальный quote сверяется с gateway key из свежего `/health`, а Devnet по-прежнему требует совпадающие gateway и treasury pins. Это правило применено к статусу, Python quote/upload, workflow, inference, source-review recovery и private storage. `.env.local` не менялся. Другой локальный gateway на `61344` тоже отвечает OFF_CHAIN, но имеет отдельную идентичность; обе инстанции не смешиваются.

В том же live-потоке обнаружено, что verified OFF_CHAIN receipt показывал `Actual charge: Unavailable`. Теперь поле сообщает `Payment status: No on-chain payment`; Devnet receipt продолжает показывать числовую сумму, когда она есть.

Browser E2E через `3041` прошёл: UI показал ставку выбранного worker `1 000 lamports/s`, пользовательский предел `0.001 SOL` и runtime `30 s`; задача `Numerical analysis` была подписана одноразовым Temporary key и завершилась за `0.1502 s`, вернув `Mean root score: 29.817865`. Gateway и worker подписи совпали с quote и raw output после выполнения и повторной проверки восстановленного receipt. Settlement `OFF_CHAIN`, on-chain payment отсутствует; execution mode `trusted_local` выполняется на host и не является Docker isolation. Temporary key после прогона отключён. При viewport `714×764` ширина документа совпала с viewport; browser warnings/errors: 0.

Frontend `npm test`: 97/97; `npm run lint`: успешно. Browser reload подтвердил HMR-исправления, receipt recovery и новый payment label. Обычный `npm run build` остановился на sandbox-ошибке esbuild при чтении `../../../..`; прямой Vite API с тем же `vite.config.js` и временным `outDir` собрал production bundle из 416 модулей. Live DeepSeek, Devnet транзакция и выплаты не вызывались.

**Проверка, назначенная следующим шагом, закрыта ниже:** публикация тарифа worker → Network → UI quote → исполнение → проверенный receipt. Выполнена только на локальном OFF_CHAIN preview без Devnet и SOL-платежа.

## Worker rate → quote → receipt — 26 октября

В светлой теме receipt-модалка теперь использует те же Material 3 фиолетовые surface-токены, что и консоль. Убрал жёсткие светло-зелёные стили и декоративное свечение, оставил короткое появление с поддержкой `prefers-reduced-motion`. В receipt добавлены видимые строки `Worker owner rate` и `Approved cost cap`: ставку и предел больше не нужно искать только в JSON.

Реальная проверка локального API и браузера: `GET /health` подтвердил `demo_mode=true`, `network=off_chain`. Для preview-worker временно опубликована ставка `2 317 lamports/s`; live Network отобразил `2 317`, а Studio quote показал `0.000002317 SOL/s`, исполнителя `NODE-CPU-PREVIEW`, предел `0.001 SOL` и runtime `30 s`. Одноразовым ключом подписан quote на безопасный preset `Numerical analysis`; worker завершил расчёт (`Mean root score: 29.817865`). Gateway повторно проверил подписи и raw output. Receipt зафиксировал ту же ставку `2 317`, предел `1 000 000 lamports`, `OFF_CHAIN` и `No on-chain payment`.

После прогона тариф worker восстановлен с `2 317` на исходные `1 000 lamports/s`; `/workers/me`, `/workers` и свежий Network UI подтвердили восстановление. Одноразовый ключ отключён. Эта проверка не подтверждает Devnet-платёж, реальную выплату worker или Docker-изоляцию: preview исполняет код как `trusted_local` на host.

Источник и frontend-тесты подтверждают границу AI Sentinel: DeepSeek используется для advisory-проверки источника и не вычисляет worker price, не разрешает запуск; API-счёт модели остаётся расходом оператора. Реальный вызов DeepSeek в этой проверке не выполнялся.

После UI-изменений `npm test` — `97/97`, ESLint — успешно. Стандартный `npm run build` повторно остановился на sandbox-ошибке esbuild при чтении `../../../..`; импортированный настоящий `vite.config.js` через прямой Vite API собрал production bundle: `416` модулей, `10` chunks, `10` assets. Browser reload восстановил завершённую Studio-сессию и открыл receipt с новой ставкой; ошибок после reload не было. Был зафиксирован один прежний HMR-сбой в момент временного удаления CSS при замене файла; чистая перезагрузка устранила его.

**Следующая задача:** проверить модельный Sentinel flow отдельно — конфигурацию DeepSeek, формат ответа, отказы/таймауты и подтверждение пользователем перед передачей исходника провайдеру. Не отправлять проектный код во внешний API без явного согласования конкретного источника и получателя.

## Overview protocol tour — 26 октября

В обзоре карточки этапов теперь меняются с коротким появлением на 220 мс; `prefers-reduced-motion` отключает анимацию. Длинные значения фактов переносятся по словам, а выплата подписана как доля из исходника программы и явно отделена от неподтверждённого live-деплоя. Кнопки этапов получили доступные имена `Stage 01: Discover capacity` … `Stage 05: Inspect the receipt`, потому что на узкой ширине видимые текстовые подписи скрываются.

В живом UI `http://127.0.0.1:3041/#overview` переходы 03 → 04 проверены в Codex in-app browser; AX-дерево показывает полные имена шагов. Временно установленный в `%TEMP%` Playwright проверил Edge на `390×844`, `320×720` с `prefers-reduced-motion: reduce` и `1280×900` с обычной анимацией. На обоих узких размерах все пять кнопок видны без горизонтальной прокрутки, ширина документа совпадает с viewport; при `320×720` кнопка действия не перекрыта нижней навигацией. Computed style подтверждает `animation: none` при reduced motion и 220 мс для обычного режима. Финальные Playwright-проходы: ошибок консоли 0; локальный Roboto загружен. В первом холодном проходе среда один раз заблокировала Google Fonts импорт из wallet-adapter; он не ломает страницу и остаётся внешний необязательный шрифт с локальным Roboto fallback.

После финальных UI-правок `npm test` — `97/97`, ESLint — успешно. Production-сборка через прямой Vite API с настоящим `vite.config.js` обработала `416` модулей и создала `10` chunks и `10` assets во временном каталоге; обычный package-script build в этой итерации не запускался.


## AI Sentinel: формат ответа DeepSeek — 26 октября

Адаптер выделенного Sentinel-провайдера теперь отправляет `thinking: {"type":"disabled"}` и `response_format: {"type":"json_object"}`. Обычные OpenAI-совместимые провайдеры не получают принудительный JSON-режим. Это просит DeepSeek вернуть машиночитаемый отчёт; verdict и finding всё равно проходят проверку схемы и диапазона строк источника. `SAFE` остаётся advisory-результатом, а неправильный или обрезанный отчёт не считается принятым выводом безопасности. Параметры сверены с официальной [DeepSeek Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/).

Точечный тест JSON-тела и mocked-stream тест DeepSeek прошли. Полный backend suite: `132` passed, `2` skipped. Python из локального venv требовал sandbox-разрешения на запуск; после разрешения тесты запускались локально, внешний API не вызывался.

**Следующая задача на тот момент:** пройти Sentinel timeout/5xx/truncated-JSON flow через локальный stub и UI, проверить, что неподтверждённый результат остаётся manual review и запрос не повторяется автоматически. Выполнено ниже на локальных ответах; внешний DeepSeek API не вызывался.

## Sentinel failure flow — 26 октября

Worker теперь валидирует JSON Sentinel-отчёт и привязку строк к точному исходнику до записи `response.txt`. Если SSE завершился, но отчёт обрезан или нарушает схему, inference задача завершается как `failed` и не публикует отчёт как успешный артефакт. UI различает сбой/остановку модели и завершённую задачу с неверным форматом; в обоих случаях verdict не принимается и требуется ручное решение. В процессе ожидания UI продолжает только безопасные GET-запросы состояния; повторного вызова модели нет.

Локальные HTTP-stub сценарии провели Gemini-compatible adapter через gateway, worker receipt и финальный статус: HTTP 503 и завершённый SSE с обрезанным JSON дали подписанный `failed` receipt, пустой список артефактов и ровно один запрос к stub на сценарий. Timeout-сценарий также прошёл весь worker → signed receipt путь: adapter завершился на 8-секундном runtime deadline, receipt имеет `failed` и `OFF_CHAIN`, а stub получил ровно один запрос. В реальном UI-прогоне нашлась и исправлена гонка: восстановленный связанный run завершался, после чего draft-effect сбрасывал результат. Теперь активный run помечает тот же Sentinel draft применённым, поэтому signed failure и manual-review экран остаются видимыми после завершения.

Edge/Playwright проверил failure и invalid-report состояния на `1280×1400`, а некорректный отчёт — ещё и на `390×844`. API в браузере заменён локальными route fixtures с криптографически корректными gateway/worker signatures; это доказывает обработку и показ состояния интерфейсом, не live gateway или модель. В обоих сценариях receipt проверен, ошибки console/page — 0; узкий документ равен viewport `390 px`. Наблюдались только GET каталога/result/download; повторной отправки `/execute` или запроса модели не было. Нажатие **Close AI Sentinel** вернуло `#studio`.

Положительный браузерный fixture с подписанным `DANGEROUS` отчётом проверил recovery → **Close AI Sentinel** → Studio: finding `high · line 2` появился рядом с исходником, а кнопка **Line 2** выделила точную строку в редакторе. Quote не отправлялся: без подключения той же wallet UI правильно показал `Reconnect the reviewing wallet`. Backend отдельно подтверждает привязку принятого source-review к новому compute quote тестами gateway.

Frontend suite: `98/98`; ESLint прошёл. Backend suite: `133 passed, 2 skipped`. Обычный package build заблокирован sandbox-доступом esbuild к родительскому каталогу; сборка тем же настоящим `vite.config.js` через прямой Vite API прошла после последней правки: `416` модулей, временный каталог вне repo. Внешний DeepSeek не вызывался.

**Следующая задача:** провести успешный source-bound Sentinel отчёт через те же UI recovery и Studio handoff состояния с локальным signed fixture; проверить, что findings появляются рядом с источником и верный report можно привязать к отдельному compute quote. Live-запрос DeepSeek требует отдельного выбора исходника и явного согласия на передачу провайдеру.

## Workflow mode motion и следующий проектный шаг — 26 октября

Переключатель `CSV report` / `Model + compute` раньше сразу заменял крупную рабочую область. Добавлен короткий вход активного режима: 240 мс, небольшой сдвиг на 6 px и мягкое появление. Он запускается только при смене типа workflow, не дублирует вход страницы и не перемонтирует `WorkflowRun` или `AgentWorkspace`. Выбор остаётся обычной кнопкой с `aria-pressed`; `prefers-reduced-motion` отключает анимацию.

Проверено в Edge через временный Playwright, потому что Browser plugin отсутствует: `#workflows`, CSV → Model + compute → CSV при `1440×1000` и `390×844`. После переключения `data-mode` и `aria-pressed` совпадают, анимация заканчивается в `opacity: 1` и `transform: none`; первоначальный режим не получает второй вход. При `prefers-reduced-motion: reduce` у панели `animation: none`. Ширина документа равна viewport; page/console errors — 0, POST-запросов не было. Проверка не загружала файлы, не получала quote и не вызывала модель.

Frontend suite — `98/98`, ESLint — успешно. `npm run build` по-прежнему блокируется sandbox при чтении `../../../..`; прямой вызов Vite API с импортированным настоящим `vite.config.js` собрал production bundle: `416` модулей обработано, `10` JS chunks. Backend в этой итерации не менялся и повторно не запускался. Скриншоты лежат в `%TEMP%\aperture-workflow-mode-final-desktop.png` и `%TEMP%\aperture-workflow-mode-final-mobile.png`.

### Краткий аудит продукта до успешного handoff QA

В рабочем дереве уже соединены Studio для Python и model inference, AI Sentinel с проверкой источника и ручным решением, worker market с тарифом владельца, workflow-конструктор, private storage и проверяемые signed receipts. Локальные `OFF_CHAIN` прогоны и синтетические HTTP/browser fixtures подтверждают отдельные реальные пути, но не заменяют Devnet оплату, удалённые GPU или live вызов модели. Текущий локальный runtime — `OFF_CHAIN`; API возвращает один online CPU worker и один online `inference_proxy` worker. При этом `/inference/providers` пуст, поэтому Network показывает `0` public model offers и `0` public model workers. Единственный model offer на inference worker — `deepseek-flash` для `aperture-deepseek`; он используется Sentinel и намеренно исключён из обычного публичного inference каталога. Это не ошибка счётчика и соответствует решению оставить DeepSeek проверкой source safety, а не универсальным model/pricing engine. На доступных здесь экранах фиолетовая Material 3 система выдержана; наиболее заметный незакрытый сквозной пробел сейчас в подтверждении продолжения после Sentinel.

**Задача, назначенная на тот момент (закрыта ниже):** закрыть успешный путь `подписанный source-bound Sentinel review → Review compute price & limits → новая отдельная quote`. Провести browser flow с локальной wallet identity, совпадающей с автором review; проверить, что quote содержит именно исходный review и его hashes, требует отдельного подтверждения и не переносит старый бюджет/исполнителя. Сначала использовать локальный signed fixture и gateway; не отправлять код DeepSeek и не подписывать Devnet-транзакцию.

## Sentinel → compute quote: browser handoff and mobile layout — 26 октября

Успешно проверен связанный сценарий в локальном React/Vite Studio на настоящем интерфейсе: сохранённый подписанный Sentinel review восстановился, временная Ed25519 wallet с той же identity подключилась, и отдельный `POST /quotes` получил исходный `task_id`, SHA-256 исходника и SHA-256 receipt в `parameters.aperture_review`. UI показал выбранного worker, опубликованный тариф `1 000 lamports/s`, cap `0.001 SOL`, лимит `30 s` и статус `AI Sentinel review is bound to this compute quote`. Кнопку `Accept quote & sign` не нажимали.

Gateway API в браузере был заменён локальными Playwright fixtures: это подтверждает проверку UI, восстановление подписей, совпадение wallet, сборку параметров quote и её показ, но не приём запроса настоящим локальным gateway. Не вызывались `/execute`, DeepSeek или Devnet; payment/worker execution в этом прогоне не было. Внешний запрос к Google Fonts перехвачен пустым CSS-stub. Внешних data-запросов, ошибок страницы и ошибок консоли — 0.

В том же мобильном прогоне обнаружен и исправлен баг в approval-полосе Studio: при ширине 390 px summary сжимался почти до нуля и растягивал карточку до 636 px. В `frontend/src/Dashboard.css` на ширине до 760 px карточка теперь использует одну колонку, а цена и кнопка — соседние колонки. Повторный Playwright прогон подтвердил высоту полосы 108 px вместо 636 px; текст цены получил 173 px, ширина документа равна viewport и на 390 px, и на 320 px. Скриншоты: `%TEMP%\aperture-sentinel-quote-desktop.png`, `%TEMP%\aperture-sentinel-quote-mobile.png`.

Frontend: `npm test` — 98/98; ESLint прошёл; `git diff --check` чистый. Backend не менялся. Стандартная сборка в этой итерации не запускалась.

**Следующая задача, назначенная до проверки локального gateway (закрыта ниже):** провести source-bound проверку через реальный локальный gateway вместо browser mock: использовать уже сохранённый OFF_CHAIN runtime и безопасный Python workload, сверить опубликованный тариф, сформированный manifest и ответ `/quotes`, не отправляя новый запрос DeepSeek и не вызывая `/execute`. Если это пройдёт — после этого отдельно решать оставшиеся границы MVP: живой публичный inference provider и Devnet settlement; не смешивать их с локальными доказательствами.

## Локальный gateway: реальная quote без исполнения — 26 октября

`GET /health` подтвердил живой `development` gateway в `OFF_CHAIN` режиме; два preview worker были online. Отправлен один обычный source-only preview-запрос на `POST /quotes` с `print(42)`, временной валидной Solana identity, лимитом `100 000 lamports` / `10 s` и выбранным `NODE-CPU-PREVIEW`. Реальный gateway вернул `provider_published_worker_rate_v1`: `1 000 lamports/s`, тот же worker, эффективные `10 s`, `off_chain`, treasury `null` и срок quote 90 секунд.

Ответ проверен уже frontend-функциями: workload SHA-256, source SHA-256, canonical authorization message, manifest/source match, worker identity, опубликованный тариф и `off_chain` граница — все 7 проверок прошли. Sentinel-reference отсутствовал намеренно: действующий gateway не хранит этот синтетический browser fixture; его source-review привязка отдельно покрыта 7 backend-тестами. `/execute`, DeepSeek и Devnet не вызывались. Созданная неиспользованная quote не может запустить задачу без отдельной подписи; после 90 секунд она истекает и будет удалена при следующей quote-записи.

**Следующая задача:** сделать короткий визуальный проход по ключевым live-экранам в desktop и mobile, проверить переполнение/ошибки при реальном локальном telemetry и исправить наиболее заметную конкретную проблему.

## Пустой public model market — 26 октября

В `frontend/src/ComputeMarket.jsx` пустые состояния каталога стали различать загрузку, отсутствие оффера, недоступность каталога, отсутствие Python worker и отключённый gateway. Во время первого GET показывается `Checking public model offers` с `aria-busy=true`; готовый пустой каталог сообщает, что public route появится после публикации gateway offer и подключения worker. Там же отдельно сказано: AI Sentinel — проверка безопасности исходника, а настроенный DeepSeek зарезервирован для неё и не показывается как обычный inference offer. В All routes добавлена короткая заметка о разнице Sentinel и публичного каталога, чтобы нулевой Model offers рядом с живым CPU worker не выглядел поломкой. Состояние `offline`, пока `online` уже восстановился, тоже остаётся загрузкой, а не объявляет отсутствие моделей.

Реальный локальный интерфейс `http://127.0.0.1:3041/#network` был подключён к `http://127.0.0.1:8000` в режиме `OFF_CHAIN`; `/inference/providers` ответил пустым списком. Browser plugin в этой сессии недоступен, поэтому для проверки использован временный Playwright с установленным Edge. Проверен переход Overview → Worker network → Model inference; одна локальная GET-загрузка каталога была временно задержана, пока интерфейс показал loading, затем отпущена до того же настоящего backend. После ответа показался empty state; All routes показал объяснение, а `Open setup guide` открыл Getting started. На 1440×960, 390×844 и 320×740 ширина документа равна ширине viewport. Страница ошибок — 0; ошибок консоли — 0; POST и запросы наружу не выполнялись. Google Fonts stylesheet в изолированном браузере заменён пустым CSS-ответом.

Frontend после изменения: `npm test` — 98/98; `npm run lint` — прошёл; `git diff --check` для изменённого исходника чистый. Стандартный Vite CLI build в этом sandbox не может прочитать каталог выше разрешённой директории при esbuild загрузке `vite.config.js` (`Access is denied` для `../../../..`). Для проверки самого исходника выполнена сборка временной копии через Vite API с тем же `vite.config.js`, `configFile:false` и теми же установленными зависимостями: 416 модулей собрались успешно; `dist` остался в `%TEMP%`.

**Следующая задача:** отдельным live-проходом проверить Provider onboarding: публикацию worker rate, понятность авторизации и безопасный отказ для неверного токена, не меняя состояние внешних сетей.

## Provider onboarding и честная маркировка цены — 26 октября

Закрыта следующая UI-задача. Provider экран теперь с первого входа говорит, что тариф задаёт владелец worker: он публикует ставку в lamports/second, она видна в Network и входит в task quote. В локальном `OFF_CHAIN` preview заметка прямо говорит, что SOL не переводится. Верхний подзаголовок и вводный текст больше не называют OFF_CHAIN оценку «оплаченной»: они различают подтверждённые Devnet earnings и OFF_CHAIN estimates. После входа существующая форма остаётся источником настройки тарифа.

Browser-проверка реального `http://127.0.0.1:3041/#provider` использовала только локальные GET (`/health`, `/active_nodes`, `/stats`, `/inference/providers`, `/sentinel/providers`) и живой gateway `OFF_CHAIN`. Проверены нулевой экран без сессии, короткое пояснение owner-rate, password-поле, раскрытие credential help (показывает временный путь `worker-access.json` локального preview), и экран в размерах 1440×960, 390×844 и 320×740. Ширина документа совпала с viewport; ошибок страницы/консоли и POST-запросов не было. Токен не вводился; worker rate не менялся, `/workers/me` и `/workers/me/rate` не вызывались.

Последняя проверка после обоих UI-изменений: `npm test` — 98/98; `npm run lint` — прошёл; временная Vite API сборка обновлённой копии — 416 модулей успешно. Обычный CLI build по-прежнему упирается в sandbox `Access denied` выше корня разрешённого дерева; детали и способ независимой проверки описаны выше. Скриншоты остались только в `%TEMP%`: `aperture-provider-onboarding-desktop.png`, `aperture-provider-onboarding-mobile.png`, `aperture-model-market-empty-desktop.png`, `aperture-model-market-empty-mobile.png`.

**Следующий предметный шаг:** проверить реальное owner-публикацию цены с допустимыми локальными учётными данными или добавить отдельный disposable worker fixture; не менять rate действующего worker без явного тестового объекта.

## Owner-set rate propagated into Network — 26 октября

Проверен целый локальный путь владельца worker. Отдельный временный FastAPI стенд запускал настоящий Gateway и worker-market routes поверх `StateStore(':memory:')`; worker, Solana keypairs и тестовая авторизация были синтетическими. Опубликована ставка 4,200 lamports/sec, после перехода в Network без кнопки Refresh каталог уже показывал 4,200. Это выявило и закрыло задержку общего состояния: раньше directory продолжал показывать прежнюю телеметрию до следующего poll. Обновляются только разрешённые публичные поля инвентаря; историю, credentials и данные владельца в публичный объект не копируем.

Для quote-пути существующая backend проверка `test_automatic_route_pins_lowest_published_price_and_executor` подтверждает, что quote фиксирует опубликованную ставку выбранного worker и его identity. Отдельный live POST `/quotes` через одноразовую заглушку не засчитывается: первая заглушка была неполной, а повторный запуск временного Python процесса блокировался Windows sandbox. Внешний worker rate не менялся, подпись не создавалась, `/execute` и Solana transaction не вызывались.

Верификация исходников после изменений: frontend suite — 98/98; `npm run lint` — успешно; backend `test_worker_market` — 10/10; изолированная Vite API сборка — 416 модулей. Реальный browser проход подтвердил Owner workspace → Publish rate → Network при `1440×960`, `390×844` и `320×740`; ставка в каталоге обновилась сразу, ширина страницы не переполняет viewport, ошибок page/console нет. Скриншоты: `%TEMP%\aperture-provider-rate-published.png` и `%TEMP%\aperture-provider-rate-in-network.png`.

**Граница результата:** это подтверждает локальный `OFF_CHAIN` UI и Gateway путь для тестового worker. Перевод SOL, settlement в Devnet, выполнение реальной задачи и удалённая worker инфраструктура этим проходом не подтверждались.

## Route-linked motion на Overview — 26 октября

На Overview существующая схема `Model → CPU → signed receipt` теперь реагирует на четыре карточки маршрутов: наведение мыши или клавиатурный фокус выделяет соответствующий узел, а Agent workflow показывает всю цепочку. Для AI Sentinel и Python compute подсвечивается CPU-узел. Фиолетовая палитра Material 3 и исходная схема сохранены; анимация объясняет выбранный путь и не меняет сетевое поведение.

При проверке нашёлся каскадный конфликт: плоский стиль `.console-app.aperture-workspace .console-dispatch-path` в `Workspace.css` обнулял фон состояния hover/focus. Добавил более специфичное правило состояния после него. Строки маршрутов теперь подсвечиваются без сдвига layout, фокус клавиатуры виден, а при `prefers-reduced-motion` узлы остаются статичными.

Реальный локальный экран `http://127.0.0.1:3041/#overview` проверен в Edge/Playwright при `1440×960`, `390×844` и `320×740`: все четыре связи маршрута с диаграммой работают, ширина документа совпадает с viewport, ошибок страницы нет. Отдельно подтверждены keyboard focus и `prefers-reduced-motion`; в reduced-motion состояние цветовое выделение сохраняется без transform, transition и animation. Внешние запросы и изменения backend не выполнялись.

После правки: frontend suite — `98/98`, ESLint прошёл; изолированная production-сборка Vite успешно собрала 416 модулей во временную копию. Сборка в копии нужна из-за sandbox-ограничения, когда стандартная загрузка `vite.config.js` пытается прочитать каталог выше разрешённого дерева. Проект остаётся `OFF_CHAIN`: эта анимация не свидетельствует о реальном платеже, удалённом исполнении или Solana settlement.

**Следующая задача:** проверить Studio rail `Source → Sentinel → Price → Worker → Receipt` на desktop и mobile; сопоставить каждую анимацию реальным состояниям задачи и убрать визуальные скачки, не создавая впечатления завершённого шага до подтверждения backend.

## Studio rail: state mapping и mobile motion — 26 октября

Разбор исходника и живого Studio экрана выявил две ошибки прогресса. После возвращения из Sentinel совпадающий подписанный отчёт оставлял `status === 'idle'`, поэтому rail показывал Source текущим, хотя Sentinel уже завершён. При `uploading` неявная ветка по умолчанию, наоборот, сразу показывала Receipt. Открыл проверку этапов через отдельную функцию `studioProgressStep`: совпадающий source review переводит idle-поток к Price, открытый незавершённый Sentinel остаётся текущим до результата, загрузка файлов остаётся на Source, а неизвестный status не объявляет receipt готовым.

На mobile rail теперь соединён тонкими линиями между точками; цвет линий следует за достигнутыми этапами. Кнопка Sentinel получила явный `:focus-visible` контур без сдвига layout. Цвета Material 3 сохранены, все новые переходы используют существующий слой `Motion.css` и не запускаются при reduced motion.

Проверки: frontend suite — `100/100`; ESLint прошёл; изолированная production-сборка Vite — 417 модулей. Edge/Playwright открыл настоящий локальный `http://127.0.0.1:3041/#studio` с изолированным профилем, Browser plugin в этой сессии отсутствует. На `1440×960`, `390×844` и `320×740` проверены Source → Sentinel и ровно один `aria-current="step"`; документ не шире viewport. Клавиатурный переход к кнопке Sentinel показал focus-visible outline. В reduced-motion computed styles — `transition: 0s`, `animation: none`. Ошибок страницы/консоли не было; запросов наружу и не-GET действий не было. Сопоставление прикреплённого Sentinel report → Price покрыто отдельным тестом pure state mapper; живой подписанный report в browser fixture здесь не подменялся.

Ограничение доказательств остаётся прежним: локальный gateway работает как `OFF_CHAIN`; эта визуальная проверка не выполняла `/execute`, не отправляла код во внешний DeepSeek и не подтверждала settlement в Solana. На этом срезе `git status --short` показывает 115 изменённых/новых путей; большая часть относится к предыдущей интеграции и существовала до этого прохода.

**Следующая задача:** проверить семантику действия Sentinel в присоединённом отчёте. В `Dashboard.jsx` текст `Open AI Sentinel` формируется для совпадающего отчёта без доступного provider, но кнопка вызывает `requestSentinelReview`; callback в `App.jsx` очищает текущий `sentinelResult` и создаёт новый draft. Нужно решить, должен ли шаг открывать сохранённый результат или явно запускать повторную проверку, затем проверить выбранное поведение с локальным signed fixture без live-запроса DeepSeek.

## Sentinel report: просмотр и повторный запуск — 26 октября

Устранил несоответствие надписи и действия в Studio. Кнопка шага `Sentinel` теперь фокусирует и открывает уже прикреплённый отчёт; панель проверки открывается отдельно. В inspector повторный запуск явно назван `Review this source again`, а просмотр существующего отчёта — `View attached AI Sentinel review`. При старте нового draft предыдущий подписанный результат больше не удаляется; закрытие панели возвращает его в Studio. Это сохраняет подтверждённое evidence при отмене или незавершённой новой проверке.

Прогнал локальный signed fixture через реальный Edge/Playwright для `1440×960` и `390×844`. Gateway health, provider catalog и Devnet balance были stubbed в изолированном browser context; wallet был тестовым Phantom-совместимым адаптером, ключи fixture генерировались заново. Проверены восстановление и подпись отчёта, совпадение source/wallet/gateway, фокус на результате по кнопке rail, отдельное открытие повторного draft и возврат к исходному отчёту. Не было DeepSeek-вызова, запроса создания задачи, внешнего сетевого запроса и горизонтального overflow. Снимки: `%TEMP%\aperture-sentinel-attached-report-desktop.png` и `%TEMP%\aperture-sentinel-attached-report-390.png`.

Frontend suite — `100/100`; ESLint прошёл. Стандартные Vite CLI build/dev команды в этой sandbox-сессии блокируются попыткой загрузчика читать каталог выше workspace (`Access denied`). Сборка тем же Vite 5.4.11 API с теми же React, alias и chunk-настройками прошла: 417 модулей. Browser plugin в сессии отсутствует; проверка выполнена изолированным Playwright с уже установленным Edge. Это подтверждает UI и OFF_CHAIN подписанный fixture, но не live DeepSeek, worker execution или Solana settlement.

**Следующий предметный шаг:** проверить полный source review контракт в backend: DeepSeek должен получать только фиксированный source-bound safety prompt; модельный ответ должен оставаться advisory, а rate, execution policy и отдельное подтверждение compute — независимыми. Сверить gateway-проверки, SDK/MCP и существующие backend tests, закрыть реальные расхождения и повторить локальную проверку без вызова внешней модели.

## Source review parity и безопасное восстановление выплат — 26 октября

Закрыт backend/SDK source-review контракт: DeepSeek endpoint закреплён за единственным `aperture-deepseek` provider с ожидаемым протоколом и путём API; другой provider alias не может направлять запросы к DeepSeek. SDK теперь отклоняет отчёты без валидной ссылки на исходник, с неизвестной серьёзностью, некорректной строкой, пустой находкой или более чем 20 finding-записями. Противоречивый `SAFE` с замечаниями нормализуется в `REVIEW`, как в frontend. Тариф и исполнение остаются решениями worker/отдельного quote, а не выводом модели. Live DeepSeek не вызывался.

Усилено восстановление on-chain settlement. Если стартовая подпись отсутствует в доступной истории, gateway больше не записывает фиктивные `0 lamports`; job остаётся ожидающим подтверждения. При успешном старте без читаемой task receipt восстановление разрешается только при точном совпадении завершённого task hash в channel state. Из состояния сохраняется адрес последнего pinned worker; несовпадающий ключ вызывает ошибку вместо неверного начисления. Это улучшает восстановление и доказательство адресата в gateway receipt, но не заменяет чтение Solana transaction/event history.

Проверки: полный backend `unittest discover` — `137` passed, `2` skipped только для opt-in реального Docker image. Targeted Solana client suite — `8/8`; в предыдущем source-review проходе backend/Sentinel — `27/27`, SDK source-review — `6/6`. Frontend suite — `100/100`, ESLint и изолированная Vite production build — успешно в предыдущем UI/browser проходе. В этой итерации live-модель и Devnet не использовались; изменение относится к gateway recovery и локальным mocks.

**Следующий шаг:** прогнать реальный Anchor payout сценарий на локальном Solana validator, затем сверить deployed Devnet program bytes и recipient только при доступном validator/toolchain. В текущем окружении `solana-test-validator` и `cargo-build-sbf` не установлены, поэтому подтверждение транзакционного перечисления остаётся незавершённым.

### Motion, route readiness и Provider onboarding — 26 октября 2026

На входе страницы `aperture-page-glide` больше не начинает с полной прозрачности: при коротком переходе стартовая непрозрачность составляет 55%, чтобы lazy-loaded экран не выглядел пустым до завершения движения. Проверка reduced-motion подтвердила, что при системном запрете движение не запускается, а страница остаётся полностью видимой.

Изолированный Edge/Playwright прошёл Overview, Studio, Agent workflows, Files & results, Agent permissions, Worker network, Provide compute и Getting started при ширинах 1440, 390 и 320 px. На каждом маршруте появились ожидаемый заголовок и содержимое; горизонтального переполнения нет. Один ранний снимок Getting started на 160 мс пришёлся на lazy-load/вход экрана, поэтому для вывода об отрисовке снимки ожидались до стабильного состояния. Проверка начала анимации Provider показала видимое содержимое (`opacity` около 0.71 при замере), финал — 1.0; reduced-motion сразу оставил opacity 1.

Provider onboarding проверен с синтетическими неверными ID/token: интерфейс получил ожидаемый `401 Invalid worker credentials.` только от `GET /workers/me`. Запросов POST, DeepSeek, Devnet и внешних data-запросов не было. Временные browser-снимки лежат в `%TEMP%\aperture-provider-desktop-stable.png`, `%TEMP%\aperture-provider-mobile-stable.png` и `%TEMP%\aperture-provider-visible-entry.png`.

Frontend: `npm test` — 100/100; `npm run lint` — прошёл. Это локальная проверка UI и gateway read-only auth; она не подтверждает живую модель, выполнение удалённым worker или Solana settlement.

### Anchor payout checks доступным локальным toolchain — 26 октября 2026

`cargo test --manifest-path programs/Cargo.toml --offline` собрал Anchor-программу в host-target и прошёл 17/17 unit-тестов, включая привязку последнего исполнителя, начисление только фактического расхода и безопасный повтор settlement. Компиляция выдала 21 предупреждение `unexpected cfg` из Anchor macro expansion; тесты прошли без ошибок. Это проверяет Rust state logic и сериализацию, но не CPI/перевод lamports в транзакции.

В окружении доступны `cargo`/`rustc`, отсутствуют `solana-test-validator`, `cargo-build-sbf`, `anchor` и `solana`. Поэтому локальный runtime payout и BPF/SBF сборку сейчас проверить нельзя; денег, Devnet и внешней сети не касались.

### Повторный запуск Python suites из текущего sandbox — 26 октября 2026

Backend и SDK код в этом UI-проходе не менялся. Перезапустить их тесты здесь не удалось: системной команды `python` нет; bundled Python не содержит FastAPI, Solders или pytest; существующий `backend/venv/Scripts/python.exe` недоступен для старта из текущего sandbox (`Access is denied`). Это ограничение запуска тестов, а не обнаруженная ошибка приложения. Приведённые ранее результаты backend/SDK остаются результатами предыдущего прогона и в этой итерации не переподтверждались.

Клавиатурные детали: `Ctrl+K` открыл command palette и сфокусировал строку поиска; `Escape` закрыл её; `Alt+7` открыл Provide compute; `Alt+T` переключил dark → light. Эти действия не отправляли изменяющие API-запросы.

### Mixed Model → Python → model: ясный статус capacity — 26 октября 2026

Новый mixed workflow раньше сводил задержку загрузки каталога, отсутствие public offer и ошибку gateway к одному сообщению о настройке модели. `MixedWorkflowBuilder` теперь показывает отдельные состояния checking/unavailable/empty, отсутствие подходящего inference worker и отсутствие Python worker. Пустое состояние объясняет границы продукта: DeepSeek зарезервирован за AI Sentinel, не выставляет цену и не появляется как обычный model offer; для трёх шагов нужен отдельный public model offer с живым inference worker, онлайн Python worker и тариф, опубликованный владельцем worker. Кнопка `Open model setup` ведёт в Getting started.

Логика состояния покрыта тестом; browser QA в изолированном Edge показал загрузку при задержанных GET, empty после настоящего ответа локального `/inference/providers`, а также synthetic 503 → unavailable → Refresh → успешный повторный GET и empty. Desktop 1440 px и mobile 390 px без overflow; `Open model setup` переводит в `#guide`. Во всех сценариях только localhost GET; внешний API и DeepSeek не вызывались.

Frontend suite — `101/101`; ESLint прошёл. Обычный `npm run build` снова заблокирован esbuild из-за чтения `../../../..` в sandbox; production build теми же React plugin, alias, define и chunk-настройками через Vite API `configFile:false` собрал 418 модулей. This verifies bundle output; it does not prove a live model provider or full mixed workflow execution.

### Mixed workflow: реальные цены и допустимая capacity — 26 октября 2026

В каталоге workflow раньше любой online Python worker считался готовым, даже если владелец не опубликовал цену. Model worker отбирался шире, чем разрешает проверка browser quote: отдельные workflow котировки принимают до 25,000 lamports/sec. Поэтому UI мог собрать план, который backend не сумел бы оценить или чей quote frontend отверг бы после запроса.

`mixedWorkflowWorkerCapacity` теперь требует свежий heartbeat (45 секунд), нужный runtime, executor identity, опубликованную ставку и предел до 25,000 lamports/sec. Mixed plan строится только при наличии текущей совместимой model capacity и Python capacity; схема каталога с `available_workers` больше не используется как единственное доказательство. Непубликованная ставка и ставка выше протокольного предела получают отдельные пояснения. В selector показывается опубликованная owner ставка; automatic route обозначен как выбор самого дешёвого совместимого live worker. Поле лимита переименовано в `Spend cap per step`, рядом указано, что фактическую цену задаёт владелец worker, а точные цена и время подтверждаются подписываемым quote до запуска каждого шага. В quote panel удалены случайные буквальные кавычки вокруг поля `Worker owner rate`.

Добавлены проверки возрастного предела heartbeat, ставки 25,000/25,001 lamports/sec, отсутствующей цены и запрета сборки без model executor. Frontend suite — `103/103`; ESLint прошёл; `git diff --check` ошибок не вернул. Production build через Vite API `configFile:false` собрал 418 модулей. Визуальный browser QA для этого изменения не завершён: Playwright отсутствовал в проекте и npm cache, временная установка в `%TEMP%` не вернула результат и была остановлена; Computer Use не смог определить текущий browser URL и завершил вызов до навигации. Поэтому новый текст и mobile layout требуют отдельной визуальной перепроверки. DeepSeek, внешние model APIs и Devnet не вызывались.

### Mixed workflow empty state: action рядом со статусом — 26 октября 2026

Сохранённый desktop/mobile рендер показал, что `Open model setup` стоял после полной формы и схемы трёх шагов. При пустом каталоге это единственное полезное действие терялось ниже первого экрана телефона. Кнопка перемещена к capacity status, выделена как основное действие и показывается только после подтверждённого состояния: пустой каталог предлагает модельный setup, нехватка worker capacity — общий setup guide; во время загрузки или ошибки каталога никаких ложных CTA нет. Пустое сообщение сокращено, но сохраняет роль DeepSeek/Sentinel, нужную модельную capacity и ответственность владельца за тариф. На узком экране кнопка занимает ширину панели.

Логика action проверяется вместе с состояниями loading/unavailable/empty и missing worker. Импортированный Python-only workflow теперь показывает потребность в Python capacity и не выводит нерелевантное предупреждение об отсутствии model offer. `npm test` — `104/104`, ESLint прошёл, `git diff --check` для затронутых исходников не нашёл ошибок. Production bundle собран через Vite API с настоящим `vite.config.js`: 399 модулей в выходных chunks, 10 chunks и 10 assets во временном каталоге. Визуальный QA завершён в локальном in-app браузере: при 709×750 CTA `Open model setup` стоит рядом со статусом; при 390×844 статус читается, а кнопка занимает ширину панели без видимого перекрытия нижней навигацией. Снимок 320×740 выявил, что из-за переноса текста единственный CTA уходил за нижнюю панель навигации. Для ширины до 360 px сокращено сообщение, убрана подпись у кнопки Refresh (иконка сохраняет доступное имя), уплотнены отступы. Повторный снимок показывает статус и CTA целиком над нижней навигацией; DOM содержит оба элемента. Нажатие CTA переводит в `/#guide`; title страницы корректный, экран не пустой, overlay не виден, `tab.dev.logs({levels:["error","warn"]})` вернул пустой список. Worker Network и Provide compute также просмотрены при 390×844: карточки и форма идут в одну колонку, видимого горизонтального переполнения нет; console errors/warnings не зарегистрированы. После проверки временный viewport сброшен и вкладка возвращена на `/#overview`. Скриншоты проверены live, в repo не сохранялись. Этот browser QA не проверяет выполнение imported workflow, внешнюю модель или Devnet.

### Studio draft сохраняется при переходе между экранами — 26 октября 2026

В отдельной вкладке на изолированном origin `localhost:3041` в редактор введён тестовый исходник `print('studio-state-preserved')` без запуска. После перехода в Agent workflows редактор оставался в DOM (`count=1`) и был скрыт; после возврата в Compute Studio accessibility state показал тот же исходник. Это прямо проверяет сохранение текущего Studio UI state при навигации, а не только unit-test поведения motion helper. Тестовый исходник сброшен на исходный sample, временные вкладки закрыты; вкладки пользователя остались на прежних адресах. Wallet, подписи, выполнение workload, DeepSeek и Devnet не затрагивались.

### Восстановление задачи без исходника — 26 октября 2026

Реальный завершённый `OFF_CHAIN` task восстановился из состояния этой вкладки вместе с валидируемым receipt и результатом `Numerical analysis`, но исходный текст отсутствовал: checkpoint сохраняет task capability и quote, а не код. До исправления комментарий о пропавшем исходнике мог выглядеть как обычный редактируемый Python; интерфейс всё ещё предлагал Sentinel и новую price review, включая `Ctrl+Enter`.

Теперь Studio сохраняет существующий черновик при восстановлении и сравнивает его SHA-256 с `code_sha256` сохранённой quote. Совпадение оставляет run связанным с этим текстом; отличающийся код помечается как отдельный черновик. Когда исходника нет, экран прямо показывает recovery notice, кнопки Sentinel и review price отключены, а keyboard shortcut выводит локальное пояснение. Центральный вход в AI Sentinel из Overview также проверяет наличие исходника, поэтому комментарий recovery не передаётся в модель через обходной маршрут.

Browser QA на `http://127.0.0.1:3000/#studio`, `714×764`: восстановленный результат остался видимым и отмечен `OFF_CHAIN`; notice объясняет отсутствие кода, `Load source to continue` и `Review with AI Sentinel` имеют `disabled=true`. После `Ctrl+Enter` появился локальный текст о необходимости загрузить исходник. Из Overview нажатие `AI Sentinel → compute` осталось на той же странице и показало предупреждение; внешнего вызова модели не выполнялось. `document.scrollWidth=709` при `innerWidth=714`; browser console error/warn — пусто. Этот проход не менял цену, не подписывал транзакции и не запускал задачу.

Добавлены проверки хэш-сопоставления, отсутствующего текста, повреждённого hash и общего guard доступности. Frontend tests — `107/107`; ESLint и `git diff --check` прошли. Стандартный `npm run build` ограничен Windows sandbox при чтении родительского каталога; production-сборка тем же `vite.config.js` через Vite API с `configFile:false` успешно обработала 419 модулей. DeepSeek/API provider, Devnet и wallet не использовались; зависимости проекта не менялись.

Финальная проверка также подтвердила defense-in-depth для старого `sentinelDraft` в session storage: `App` отклоняет недоступный исходник, а экран Sentinel блокирует quote/sign при отсутствующем, изменённом или не совпадающем с фиксированным prompt исходнике. Реальный browser QA подтвердил disabled-кнопки и блокировку `Ctrl+Enter`/перехода из Overview на восстановленной задаче без исходника. Парсер сохранённого черновика вынесен в проверяемую функцию; новый unit-тест покрывает recovery-заглушку, повреждённый JSON, неполную и валидную запись. Вручную подложить fixture в browser storage не удалось из-за read-only QA scope. При `714×764` горизонтального overflow не было, console errors/warnings отсутствовали. Временные QA-вкладки закрыты, пользовательский экран оставлен в Compute Studio.

### Studio progress rail и спокойная обратная связь — 26 октября 2026

Завершённые обязательные шаги Studio теперь показываются галочками; текущий шаг остаётся выделенным, а опциональный Sentinel получает галочку только при наличии review, привязанного к исходнику. На `completed` закрывается и последний шаг Receipt; `unverified` оставляет его активным без ложного знака завершения. Появление чек-иконок рисуется существующей короткой SVG-анимацией, а recovery-плашка использует общий мягкий вход. Оба эффекта находятся внутри `prefers-reduced-motion: no-preference`; глобальный reduced-motion override сохраняет статичный вариант.

В локальной Studio при `714×764` визуально проверены реальные восстановленный `OFF_CHAIN` receipt и recovery notice: Source/Price/Worker/Receipt получили галочки, пропущенный optional Sentinel остался нейтральным, Receipt сохранил выделение. DOM подтвердил ожидаемые классы и `aperture-check`/`aperture-feedback-in`; горизонтального overflow и browser console errors/warnings нет. Тесты состояния rail — `108/108` frontend tests; ESLint прошёл, Vite production bundle собрал 419 модулей. DeepSeek, внешние API, кошелёк и Devnet не вызывались.

### Route naming и responsive QA — 26 октября 2026

Навигация называла раздел `Agent passports`, а заголовок маршрута — `Agent permissions`. Заголовок синхронизирован с навигацией, подзаголовок теперь перечисляет три реально настраиваемые области: spending, runtime и access limits.

Все восемь главных маршрутов открыты локально с ожидаемым `h1` на desktop `1440×900` и mobile `390×844`; `documentElement.scrollWidth` не превышал viewport. Studio, Agent workflows, Agent passports и Provide compute отдельно проверены в компактном `320×740`: горизонтальной прокрутки страницы нет; длинные строки кода остаются внутри скроллируемой области редактора. Browser console errors/warnings — `0`. Временный viewport сброшен, тестовая вкладка закрыта, вкладки пользователя оставлены на прежних адресах.

Reduced-motion в браузере на лету не эмулировался: доступные browser capabilities поддерживали viewport, но не media emulation. CSS сохраняет общий `prefers-reduced-motion: reduce` override, frontend motion suite содержит проверки reduced motion. Проверки после этого исправления: `108/108` frontend tests, ESLint passed, Vite production build passed (`419` modules). Внешние модели и Devnet не использовались.

### Worker network: переход из пустого каталога в настройку model capacity — 26 октября 2026

На `All routes` нулевой каталог model offers сообщал причину, но не давал короткого пути к существующей инструкции настройки. Когда уже есть доступный маршрут, баннер теперь показывает `Set up model capacity` и ведёт на Getting started. При выбранном `CPU compute` пояснение о model offers скрыто, чтобы фильтр показывал только относящееся к нему состояние. В фильтре `Model inference` отдельный empty state называет действие `Set up model capacity`; если нет ни одного route, остаётся одно общее empty state без дублирующего баннера.

Локальный browser QA: desktop `1440×900` — кнопка одна, баннер рядом с ней, ширина документа `1434`; mobile `390×844` — ширина документа `385`. Переключение на CPU убирает баннер, а нажатие CTA открывает `#guide` с заголовком `Getting started`. После проверки временная вкладка и viewport очищены; пользовательская вкладка осталась на `3041/#overview`, `714×764`. Console errors/warnings — `0`.

Отдельно проверен serving origin открытого проекта `http://127.0.0.1:3041`: он уже отдаёт тот же новый CTA и каталожное состояние, что и QA origin `3000`; на `1440×900` document width — `1434`, ошибок/предупреждений — `0`. Пользовательская вкладка осталась на прежнем `#overview`.

Для отдельного фильтра `Model inference` проверен пустой каталог и конкретная кнопка `Set up model capacity`; при `390×844` она также открывает тот же Getting started route. Console errors/warnings — `0`.

Дополнительный стабильный визуальный проход: `Agent passports` показывает owner-wallet gate и фактические области spending/runtime/access; `Files & results` показывает закрытый список до wallet подписи. Первый снимок Storage пришёлся на короткий `Loading workspace module…`; после завершения lazy import отрисовался `Private workspace` и `Storage allowance`. Это был переходный кадр, а не постоянное пустое состояние. Повторный console scan — 0 ошибок/предупреждений; тестовая вкладка закрыта и размер браузера сброшен.

Frontend tests — `108/108`, ESLint passed, Vite production bundle через API с исходным `vite.config.js` собран (`419` modules). Обычный `npm run build` в этом sandbox по-прежнему блокирован запретом чтения каталога выше checkout (`Access is denied`); та же сборка через Vite API прошла. DeepSeek, внешние model APIs, wallet и Devnet не использовались.

### Mobile и клавиатурный QA — 26 октября 2026

На локальной Studio вкладке проверены `390×844` и `320×740`. Диалог `Receipt evidence` помещается по ширине (`296 px` при viewport `320 px`), значения доказательств не обрезаются; действия футера остаются доступны при внутренней прокрутке диалога. `Tab` и `Shift+Tab` циклически переводят фокус между кнопками, `Escape` закрывает диалог и возвращает фокус на `Inspect receipt evidence`.

В `Agent workflows` при `390×844` и `320×740` страница не выходит за ширину viewport. Клавиатурой переключены `CSV report` ↔ `Model + compute`; выбранный режим обновился, фокус остался на переключателе. Консоль браузера: `0` ошибок и предупреждений. В этой вкладке виден восстановленный Studio receipt; визуальную панель по шагам отдельного `WorkflowRun` в этой проверке проверить не удалось.

Обновлённый mixed-workflow fixture в этом проходе повторно не стартовал: глобальный `python` отсутствует, bundled Python не содержит `requests`, запуск `backend/venv/Scripts/python.exe` завершился `Access is denied`; на момент проверки локальные порты preview не слушали. Это ограничение среды запуска, а не результат провалившегося workflow-теста. Никаких запросов к внешней модели, кошелька, Devnet или платежа не было.

**Обновление 26 октября:** локальный запуск и браузерный проход завершены позднее; промежуточный отказ `Access is denied` ниже не является итогом проверки.

### Смешанный workflow и свежесть capacity — 26 октября 2026

`scripts/check_mixed_workflow.py --serve` завершился с `status=completed`, моделью `synthetic_http_fixture` и settlement `OFF_CHAIN`: три шага через SDK, три через MCP и три owner-assigned шага; восемь запросов ушли только в локальный HTTP fixture. Восстановление checkpoint и повторное выполнение прошли без дублирующих model-запросов; Unicode-статистика совпала, source review и compute bundle проверены, изменённый исходник не смог переиспользовать старый review. Итоговые файлы, ключи и процессы изолированного прогона очищены после остановки сервисов.

В браузере собрался `Model → Python → model` план с опубликованными ставками обоих preview workers по 1 000 lamports/s. На ширинах `390×844` и `320×740` горизонтального overflow нет (`documentWidth/bodyWidth` — `385/385` и `314/314`), консоль ошибок и предупреждений не показала. Ни wallet approval, ни исполнение из браузерного шага в этом проходе не запускались.

Обнаружено и исправлено устаревшее состояние каталога: форма могла показывать `No priced active worker` после истечения 45-секундного heartbeat, хотя следующий `Refresh capacity` возвращал обоих активных workers без изменения их тарифов. Теперь смешанный builder отличает stale heartbeat от отсутствующего worker или тарифа и сообщает обновить capacity, прежде чем менять настройку. Исправленное состояние проверено в UI на мобильной ширине; ручное обновление вернуло модельный и Python executor. Frontend suite — `108/108`, ESLint — успешно; console — `0` ошибок/предупреждений.

Внешний DeepSeek и другие model APIs, wallet, Devnet и SOL не использовались.

### Браузерные approvals, receipts и восстановление журнала — 26 октября 2026

На изолированном preview `http://127.0.0.1:54548/#workflows` пройден настоящий UI-путь `Model → Python → model`. Использован уже имеющийся DEV-only `SessionKeyAdapter` с флагом `VITE_ENABLE_SESSION_KEY=true`: новый невытаскиваемый ключ существовал только в памяти вкладки; пользовательский wallet не подключался. На каждом шаге интерфейс отдельно показал quote: ставка worker — 1 000 lamports/s, runtime cap — 30 секунд, максимальная сумма — 0.0001 SOL на шаг, суммарный cap — 0.0003 SOL. Каждый шаг был отдельно подписан и выполнен.

Все три задачи и их receipts прошли browser-проверку: `generate` создал `response.txt`, Python `analyze` создал `analysis.json`, `interpret` использовал эти проверенные statistics и создал финальный `response.txt`. Артефакт `analysis.json` открылся из UI и содержал 51 символ, 6 слов, 1 строку и SHA-256 `3c7bd3ff…bf76f3`. После перезагрузки вкладки журнал восстановился без повторного подключения одноразового ключа: интерфейс подтвердил `Workflow completed`, `3 verified / 3 planned steps`, три result files и verified receipts. Browser console: 0 errors и warnings; page title/URL совпали с локальным workflow.

Preview был `OFF_CHAIN`; все запросы модели обслужил локальный synthetic HTTP fixture. Fixture получил 10 model requests после browser-прохода: 8 от предшествующей SDK/MCP интеграционной проверки и ещё 2 от browser model steps. Внешние DeepSeek/Gemini, Devnet и SOL не использовались. После длительного прогона capacity UI отдельно сообщил о stale model heartbeat; уже завершённые receipts не были затронуты, а перед новым планом требуется обновить capacity. Визуальное доказательство completed-состояния снято через in-app browser.

### Восстановление потерянного ответа admission — 26 октября 2026

Второй локальный browser fault test пропустил подписанный `POST /execute` через loopback proxy в OFF_CHAIN gateway, затем намеренно заменил успешный admission-ответ локальным сетевым отказом. UI сохранил exact signed request и показал `An admission response is unresolved. Recover the exact signed request before creating another task.` Gateway на первом вызове создал `task-e6364c41f376460e9d2553c73bfea7ac`.

В той же вкладке нажата `Recover exact signed request`. Proxy зафиксировал два POST к `/execute` с одним и тем же task ID; gateway вернул уже принятую задачу, новую не создал. UI дождался и подтвердил receipt: `generate` стал `Verified`, `1 verified / 3 planned steps`, `response.txt` доступен. Это проверило и идемпотентность admission, и реальный recovery-клик в браузере. Страница после успешного replay оставалась на том же workflow; консоль после восстановления — без ошибок и предупреждений.

Отдельная перезагрузка вкладки до recovery восстановила `admitting`-журнал и правильно отключила кнопку recovery, пока исходный signing wallet не переподключён. Тестовый `SessionKeyAdapter` намеренно не сохраняет секрет между загрузками, поэтому такой ephemeral ключ нельзя переподключить после reload; обычный Phantom/Solflare должен вернуть ту же identity. Полный recovery с подписью выполнен в том же табе, а восстановление завершённых receipts после hard reload проверено отдельным предыдущим прогоном.

Fault injection использовал только loopback и synthetic model, provider keys были пустыми, settlement `OFF_CHAIN`; Devnet и SOL не использовались. Тестовые процессы и временные файлы после проверки остановлены и удалены.

**Следующая задача:** проверить истёкший quote при неопределённом admission: browser должен найти исходный task через подписанную task-history, принять только его и не создать замену. Затем прогнать stop/cancel во время исполнения и подтвердить финальный receipt.

### Доводка motion активных workflow-состояний — 26 октября 2026

Исправлен визуальный разрыв статуса: шаг `verifying` теперь окрашен в тот же фиолетовый active-state, что `admitting` и `running`. Для активного номера добавлен сдержанный 1,8-секундный expanding-ring pulse; завершённая галочка рисуется короткой анимацией. Motion-правила размещены под `prefers-reduced-motion: no-preference`; существующий глобальный reduce override отключает CSS-анимацию.

Проверка CSS в браузере использовала временную локальную visual-only страницу с синтетическими шагами, подключавшую исходные `Console.css`, `WorkflowRun.css` и `Motion.css`. Chromium computed styles подтвердили `aperture-step-live`/`1.8s` для verifying и `aperture-check` для completed; палитра осталась `#633be4`. Временная fixture-страница удалена после проверки.

Регрессия: frontend suite — `108/108`, включая motion `31/31`; ESLint прошёл; production build преобразовал 419 модулей. Backend unittest — `137` passed, `2` skipped. В DeepSeek-тесте исходящий HTTP вызов заменён локальным fake `requests.Session.post` с фиктивным ответом. Пользовательский внешний DeepSeek API не вызывался.

**Следующая локальная задача:** browser-check истёкшего quote при неопределённом admission и stop/cancel во время исполнения на OFF_CHAIN Python fixture. Внешний model API не нужен.

### Browser lifecycle, stop race и cancelled receipt — 27 октября 2026

В `frontend/src/hooks/useBrowserWorkflow.js` устранил гонку отмены: явное нажатие Stop и poll-монитор теперь разделяют один in-flight `/stop/{task_id}`. Если запрос завершился ошибкой, обещание сбрасывается, поэтому восстановленный monitor может повторить отмену. В `WorkflowRun.jsx` receipt `execution_status=cancelled` отображается как нейтральный `Cancelled`, а не красный `Failed`; stopped-состояние получает соответствующую иконку и точный текст о том, что downstream шаги удержаны. Добавлен pure helper и regression tests.

Временный Playwright в `%TEMP%` запускал установленный Edge и изолированный Vite/gateway preview. Перед каждой цепочкой `/health` подтвердил `OFF_CHAIN`, а `/inference/providers` вернул пустой список. В первом сценарии локальный proxy пропустил ровно один подписанный `POST /execute` в gateway, затем намеренно отбросил HTTP-ответ. После истечения 90-секундного quote UI восстановил тот же task через подписанные `/agents/tasks/list` и `/agents/tasks/resume`; receipt подтвердился как `completed`, UI показал `1 verified / 1 planned`, а счётчик `execute` остался равен одному. Счётчики history включали CORS `OPTIONS`: журнал proxy показал по одному фактическому POST на каждый endpoint.

Во втором сценарии браузер запустил ограниченный тестовый Python `sleep(25)` и нажал `Stop workflow`. После дедупликации proxy увидел ровно один POST `/stop`; завершающий receipt имел `execution_status=cancelled`, UI показал нейтральный статус `Cancelled` и не открывал downstream approvals. До исправления тот же сценарий отправлял два POST `/stop`, что выявило гонку между кнопкой и monitor.

Rendered QA в Edge: desktop `1440×1000` и mobile `390×844`. На mobile `documentWidth=bodyWidth=390`; после прокрутки cancelled tag и receipt полностью размещались над fixed navigation (`nav top=776`, receipt `y=412–432`). Финальный изолированный cancellation-run дал `stop_posts=1`, `provider_count=0` и ноль ошибок browser console. Снимки хранятся только во временной папке: `workflow-cancelled-final.png` и `workflow-cancelled-mobile-receipt.png`.

Frontend: `110/110` тестов, ESLint прошёл, production build собрал `420` модулей. DeepSeek, Gemini и другие внешние model APIs не вызывались; DEV-only session key был только в памяти Edge-вкладки, SOL и Devnet не использовались. Этот проход подтверждает локальные browser flows и UI, но не live provider, production gateway, on-chain settlement или качество AI Sentinel.

### Стабильный visual QA, мобильная навигация и выплата worker — 27 октября 2026

Повторный browser-pass снимал только подтверждённые состояния, дожидаясь нужного заголовка и `aria-pressed` у выбранного режима. Проверены восемь прямых маршрутов на desktop `1440×1000`, шесть основных экранов на mobile `390×844`, deep link `#sentinel` и переключение мобильного `More → Provide compute`. Страницы открылись в ожидаемом режиме; мобильный документ остался шириной `390 px`, переход из меню привёл на `#provider`, browser console errors — `0`. На этой выборке не нашлось постоянного визуального дефекта: тёмные поверхности и фиолетовые M3 states согласованы, AI-сгенерированные изображения не добавлялись. CSS в этом pass не менялся.

Первые быстрые снимки исключены из QA: они попали в route transition/lazy loading и в одном случае показали предыдущее состояние вкладки. Финальные скриншоты сохранены во временной папке `%TEMP%\aperture-lifecycle-verify-aba1df27906444d8bc560027e3620c44\design-audit`; пользовательская вкладка и её маршрут не менялись. UI работал в изолированном `OFF_CHAIN` preview, `/inference/providers` был пуст.

Проверка payout нашла недостаток в доказательстве: существующий native Rust test проверял закреплённого worker и состояние расчёта, но не движение баланса. `pay_from_channel` теперь принимает рассчитанный `Rent` явно; production callers по-прежнему берут значение через `Rent::get()`. Расширен тест pinned-worker: из bounded settlement вычисляется charge `50`, `AccountInfo` проверяет, что все `50` lamports добавились именно worker, reserve канала сохранился, сумма аккаунтов не изменилась, а попытка опустошить reserve завершается без частичной мутации.

`cargo test --locked --offline -q` — `17/17`; `cargo fmt --check` и `git diff --check` прошли. Это нативный unit-test helper с локальными `AccountInfo`, не выполнение инструкции внутри Solana runtime. Anchor по-прежнему выдаёт `cfg(...)` warnings. После sandbox-отказа запуска Python venv focused suites были выполнены разрешённым локальным способом: inference, Sentinel и worker pricing — `37/37`, с in-process и loopback fixtures. DeepSeek endpoint эти тесты не вызывали. Последний полный backend run остаётся `137 passed, 2 skipped`; полный набор в этом pass не запускался.

DeepSeek, другие внешние model APIs, кошелёк, Devnet и реальные lamports не использовались. Источники подтверждают разделение, которое выбрал владелец проекта: DeepSeek принимает только фиксированный source-bound Sentinel review, а quote тарифицируется по опубликованной ставке worker; соответствующие offline backend tests уже есть. Точность ответа DeepSeek и работа с живым провайдером не проверялись.

**Следующий технический приоритет:** проверить Anchor `stop_task` как транзакцию в локальном Solana program-test/validator, включая фактический pinned-worker payout, rent reserve и legacy recovery recipient. Нынешний тест доказывает арифметику helper-а, а не runtime исполнение инструкции; развернутую версию и выплату в Devnet этот workspace не подтвердил. Не запускать платную модель или сетевую транзакцию без отдельного решения владельца.

### Переключение темы без лишних переходов — 27 октября 2026

Инициализация темы в `frontend/index.html` выставляет сохранённую тему до загрузки React, а React использует те же ключи localStorage и тёмный fallback. В браузере отдельно подтверждены начальная тёмная и светлая темы без переключения на противоположную при старте.

Проверка CSS выявила лишний эффект: постоянное правило перехода цветов затрагивало все обновления статусов и индикаторов, хотя плавность нужна только при ручном переключении темы. В `App.jsx` переход теперь активен 260 мс после нажатия; CSS crossfade длится 220 мс и работает только пока установлен `data-theme-transitioning`. Таймер заменяется при быстром повторном клике и очищается при размонтировании. При reduced motion CSS-переход отключён.

Edge/Playwright на локальном preview подтвердил: idle transition `0s`; после переключения темы — `0.22s`; после окна перехода снова `0s`. `prefers-reduced-motion: reduce` отключил CSS animation и transition; Studio на mobile `390×844` не имеет горизонтального переполнения. В обоих settled-снимках Overview видно, что светлая и тёмная палитры сохранили исходный фиолетовый характер. Ошибок страницы — `0`; внешние запросы блокировались, API по адресу `65500` не был запущен, кошелёк/Devnet/модели не использовались.

Численный аудит десяти видимых текстовых ролей в settled Overview подтвердил контраст не ниже `4.5:1` в обеих темах: минимум `5.18:1` в light и `5.65:1` в dark для sampled body text и navigation. Заголовки и подписи имеют больший запас. Палитру оставил без изменений.

Полный frontend suite после правок — `110/110`, ESLint прошёл, production build обработал `420` modules. Полный suite выявил locale-зависимый flaky assertion: Node отдавал разделитель тысяч неразрывным пробелом, тогда как English UI и тест ожидали запятую. Форматирование `receiptPaymentField` закреплено на `en-US`, согласовано с остальными англоязычными суммами и теперь проходит полный suite. Сборка выполнена прямым Vite API с проектным config и `configFile: false`, поскольку обычный package script в sandbox не может читать родительскую папку при загрузке config. `git diff --check` прошёл. Локальный HTTP preview остановлен после browser QA.

**Следующая задача:** добавить локальный Solana program-test/validator harness для инструкции `stop_task` и проверить runtime-перевод всего начисления закреплённому worker, сохранение rent reserve, legacy recovery recipient, повторный вызов и отказ при нехватке средств. До появления этих проверок unit-test helper остаётся ограниченным доказательством; Devnet settlement не заявлять.

### Anchor runtime payout: rent-инвариант и локальный toolchain — 27 октября 2026

В текущем дереве уже есть CI job, который устанавливает matching Solana validator tools `4.3.0`, собирает SBF программу и запускает `frontend/tests/onchain-v2.local-validator.mjs`. Скрипт делает реальные транзакции к локальному validator: включает успешный `stop_task`, полную выплату закреплённому worker, отказ при подмене worker, отсутствие выплаты treasury, повторный вызов и закрытие активного канала с persistent receipt.

Расширил этот runtime сценарий прямой проверкой rent exemption после stop и точной разницы lamports канала, равной сумме квитанции; повторный `stop_task` теперь также обязан оставить lamports неизменными. Добавил обработку `spawn` error, чтобы при отсутствующем `solana-test-validator` harness завершался с явной причиной вместо бесполезного ожидания RPC. `node --check`, `cargo fmt --manifest-path programs/Cargo.toml --check`, `cargo test --manifest-path programs/Cargo.toml --locked --offline -q` (`17/17`) и `git diff --check` прошли.

Локальный запуск `node frontend/tests/onchain-v2.local-validator.mjs` остановился сразу с `spawn solana-test-validator ENOENT`. `cargo-build-sbf` и бинарник `solana-test-validator` на этой машине отсутствуют; имеющийся `target/deploy/aperture_gateway.so` собран 26 октября и не является подтверждённым артефактом текущего исходника. Поэтому новые runtime assertions пока не исполнены, а предыдущий CI workflow-конфиг сам по себе не является доказательством успешного CI run. Тестовый temp ledger очистился; процесс на RPC-порту `8899` не остался.

Текущий сценарий проверяет обновлённый путь `start_task → stop_task` и текущий owner-close payout worker-у, но не активную задачу из предобновлённой схемы, чей recovery получатель выбирается из legacy treasury fallback. Это остаётся отдельным незакрытым случаем.

**Следующая задача:** добиться успешного CI запуска обеих локально-validator проверок на matching Anza `4.3.0` toolchain. Не заявлять runtime/Devnet settlement до успешных логов.

### Проверка treasury recovery для pre-pinning задачи — 27 октября 2026

Добавлен отдельный сценарий `frontend/tests/onchain-legacy-recovery.local-validator.mjs` и CI шаг после основного validator integration. Он загружает в genesis локального validator совместимые с bounded-task layout аккаунты config, channel и unsettled receipt, где `last_charged` — обычное значение, то есть активная задача началась до закрепления worker payout. После подписанного владельцем `close_channel` проверяются удаление канала, сохранённый settled receipt, точное начисление treasury и отсутствие выплаты подставленному worker. Сценарий также проверяет реальную транзакцию, а не только helper арифметику.

Синтаксис обоих Node harnesses проверен; `cargo fmt --check`, Rust tests (`17/17`) и `git diff --check` прошли. Локальный запуск нового сценария пока не подтверждён: он остановился с `spawn solana-test-validator ENOENT`, поскольку validator tools здесь отсутствуют. Официальный локальный-validator workflow Solana поддерживает сохранение account JSON и его повторное подключение через `--account`; CI job уже устанавливает Anza `4.3.0` перед обоими harnesses ([Local validator docs](https://solana.com/docs/toolkit/local-validator)). Значит, proof полного исполнения этого теста появится только после успешного CI run; неподтверждённые локальные genesis fixtures нельзя считать runtime-pass.
