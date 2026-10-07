# Сценарий для записи видео в OBS (Aperture Video Walkthrough)

- **Формат:** Запись экрана с микрофоном в OBS Studio (без прямого эфира и без жюри).
- **Хронометраж:** ~2.5–3 минуты в спокойном темпе (можно перезаписывать дубли).
- **Инструкции:** на русском языке (куда вести курсор, когда кликать).
- **Текст для начитки в микрофон (Voiceover):** на простом, уверенном и естественном английском языке.

---

## 1. Настройка OBS перед записью (за 1 минуту)
1. **Источник в OBS:** Захват окна (браузер с `http://localhost:3000`) или Захват экрана, разрешение 1920x1080.
2. **Браузер:** Развернуть на весь экран клавишей **F11** (убирает лишние вкладки и панель задач Windows).
3. **Начальная позиция:** Открыта вкладка **Overview**, страница в самом верху. Кошелек Solflare уже подключен в шапке.
4. **Главный совет для OBS:** Двигайте курсор плавно, без резких рывков. После каждого клика делайте микропаузу в полсекунды.

---

## 2. Пошаговая раскадровка для записи

### СЦЕНА 1. Начало видео и Overview (~30 сек)

#### Что делать на экране:
- Нажимаем кнопку «Начать запись» в OBS.
- Ждем 1 секунду тишины.
- Медленно ведем мышь по верхнему блоку страницы, плавно прокручиваем вниз, показывая схему (Ingest -> Plan -> Worker -> Report).

#### Что говорить в микрофон (Voiceover):
> "Hey everyone! In this video, I'm going to give you a quick walkthrough of Aperture—a high-assurance compute gateway for autonomous AI agents on Solana.
> 
> When agents execute real code, giving them unrestricted server access or a direct credit card is dangerous. If an agent crashes midway through a heavy pipeline, or gets trapped in a reasoning loop, you lose money and break production.
> 
> Aperture solves this by providing bounded compute: spending ceilings enforced on Solana, isolated CPU sandboxes, and automatic crash recovery with zero duplicate charges."

---

### СЦЕНА 2. Переключение темы (~15 сек)

#### Что делать на экране:
- Плавно ведем курсор в правый верхний угол.
- Кликаем на кнопку переключения темы (солнце/луна): показываем темную тему, затем светлую (или оставляем ту, которая больше нравится).

#### Что говорить в микрофон (Voiceover):
> "The console is designed with a clean FinTech cyber UI, featuring full dynamic theme support—it looks great in both dark and light modes."

---

### СЦЕНА 3. Быстрый тест в симуляторе (~45 сек)

#### Что делать на экране:
1. Прокручиваем страницу чуть вниз к блоку **Deterministic Execution Telemetry**.
2. Показываем вкладку **Resilient CSV Pipeline (17K CSV)**.
3. Нажимаем фиолетовую кнопку **Simulate 17,000-Row Crash Recovery**.
4. Спокойно ждем 3 секунды, пока бежит конвейер телеметрии (Stage -> Escrow -> Recovery -> Settlement).
5. Показываем появившуюся карточку результатов: таймлайн журнала слева и готовые файлы `report.json` / `categories.csv` справа.
6. Нажимаем кнопку **Verify Cryptographic Proof**, показываем зеленый бейдж `Verified` и закрываем окно.

#### Что говорить в микрофон (Voiceover):
> "Now let's run a live workload test right here in the simulator: we have a 17,000-row CSV aggregation with an intentional worker crash at Step 1.
> 
> When we run it, the worker terminates midway. But Aperture’s gateway recovers state from the disk journal in just 18 milliseconds and resumes execution without duplicating any tasks.
> 
> Exactly zero duplicate tasks, zero extra fees, and the output matches our baseline byte-for-byte. We can even verify the Ed25519 cryptographic signatures and SHA-256 hashes right here."

---

### СЦЕНА 4. Вкладка Workflows — пайплайны задач (~25 сек)

#### Что делать на экране:
1. В левом меню плавно кликаем на вкладку **Workflows**.
2. Прокручиваем страницу: показываем граф шагов пайплайна и лимиты бюджета на каждый шаг.

#### Что говорить в микрофон (Voiceover):
> "Next, let's head over to the Workflows tab. This is where agents coordinate multi-step task DAGs. Each step has its own isolated runtime and budget ceiling, so runaway execution is completely prevented."

---

### СЦЕНА 5. Вкладка Studio — инспекция кода (~30 сек)

#### Что делать на экране:
1. В левом меню кликаем на вкладку **Studio**.
2. Показываем встроенный редактор Python-кода.
3. Показываем правую панель параметров (AST Security Check, Gas Quote, Runtime limits).

#### Что говорить в микрофон (Voiceover):
> "Moving into Workload Studio: here developers and agents can inspect code directly. Every script passes static AST security validation before dispatch.
> 
> You don't need any proprietary LLM API tokens to run workloads here—Aperture handles the execution natively and exposes 19 Model Context Protocol tools for Claude, Cursor, and autonomous agent frameworks."

---

### СЦЕНА 6. Вкладка Storage — артефакты и файлы (~20 сек)

#### Что делать на экране:
1. В левом меню кликаем на вкладку **Storage**.
2. Показываем список файлов датасетов и сгенерированных отчетов с их SHA-256 хэшами.

#### Что говорить в микрофон (Voiceover):
> "In the Storage tab, all input datasets and verified output artifacts are managed. Every file is immutably hashed with SHA-256 and mapped directly to on-chain receipts."

---

### СЦЕНА 7. Завершение видео (~15 сек)

#### Что делать на экране:
- В левом меню возвращаемся на **Overview** (показываем бейдж Devnet Verified в шапке).
- Плавно останавливаем мышь по центру экрана.
- Ждем 1 секунду после окончания фразы и нажимаем «Остановить запись» в OBS.

#### Что говорить в микрофон (Voiceover):
> "To wrap up: our smart contract is live and verified on Solana Devnet, all 46 protocol tests are green, and the entire repository is open-source.
> 
> Thanks for watching!"
