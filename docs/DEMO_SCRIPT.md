# Удобный сценарий демонстрации Aperture (Walkthrough Guide)

- **Формат:** Спокойный живой тур по приложению (без заучивания и театрального пафоса).
- **Инструкции и шаги:** на русском языке.
- **Реплики спикера (Speech):** на естественном, простом английском языке.
- **Длительность:** ~2.5–3 минуты в комфортном темпе.

---

## Подготовка перед показом (за 30 секунд)
1. Открыть `http://localhost:3000` (или Vercel) на весь экран (F11).
2. Убедиться, что вы находитесь на вкладке **Overview** в левом меню.
3. Кошелек Solflare уже подключен в шапке (виден сокращенный адрес и бейдж Devnet).

---

## ШАГ 1. Открываем Overview и рассказываем о проекте (~30 сек)

### Что делать (Инструкция):
- Стоим на вкладке **Overview**.
- Спокойно прокручиваем страницу вниз, показывая архитектурную схему (Ingest -> Escrow -> Worker -> Verified Report).

### Что говорить на английском (Speech):
> "Hi everyone! This is Aperture—a high-assurance compute gateway for autonomous AI agents on Solana.
> 
> When agents execute real code, you can't just give them unlimited server access or a raw credit card. If an agent crashes midway or enters an infinite loop, you lose money and break production.
> 
> Aperture provides bounded compute: hard spending ceilings enforced on Solana, isolated CPU sandboxes, and automatic crash recovery."

---

## ШАГ 2. Переключаем тему оформления (~15 сек)

### Что делать (Инструкция):
- В верхнем правом тулбаре кликните на кнопку переключения темы (**Theme / солнце-луна**).
- Переключите со светлой темы на темную (или обратно), показав неоновый кибер-дизайн и плавные стеклянные переходы.

### Что говорить на английском (Speech):
> "The console is built with a clean FinTech cyber design system, with full dynamic theme support—seamless in both light and dark modes."

---

## ШАГ 3. Проводим быстрый тест в симуляторе (~45 сек)

### Что делать (Инструкция):
1. На странице Overview прокрутите к блоку **Deterministic Execution Telemetry**.
2. Покажите вкладку **Resilient CSV Pipeline (17K CSV)**.
3. Нажмите кнопку **Simulate 17,000-Row Crash Recovery**.
4. Подождите 3 секунды, пока бежит конвейер телеметрии.
5. Покажите карточку результатов: блок **State Journal Timeline** и файлы `report.json` / `categories.csv`.
6. Нажмите кнопку **Verify Cryptographic Proof**, покажите зеленый бейдж `Verified` и закройте модалку.

### Что говорить на английском (Speech):
> "Let’s run a quick live workload simulation: here we have a 17,000-row CSV aggregation with an intentional worker crash at Step 1.
> 
> When we run it, the worker abruptly terminates midway. But Aperture’s gateway recovers from the on-disk journal in just 18 milliseconds and resumes without duplicating any work.
> 
> The result: exactly zero duplicate tasks, zero extra fees, and bit-identical output. We can immediately verify the Ed25519 signatures and SHA-256 hashes right here."

---

## ШАГ 4. Вкладка Workflows — пайплайны задач (~25 сек)

### Что делать (Инструкция):
1. В левом меню нажмите на вкладку **Workflows**.
2. Прокрутите список пайплайнов, покажите граф шагов и потолки бюджета на каждый шаг.

### Что говорить на английском (Speech):
> "Moving to Workflows: this is where agents coordinate multi-step dependency DAGs. Each step has its own isolated runtime and budget ceiling, so runaway execution is impossible."

---

## ШАГ 5. Вкладка Studio — инспекция кода и песочница (~30 сек)

### Что делать (Инструкция):
1. В левом меню нажмите на вкладку **Studio**.
2. Покажите встроенный редактор кода на Python.
3. Покажите справа панель параметров (Security AST Check, Gas Quote, Runtime limits).

### Что говорить на английском (Speech):
> "Next, in Workload Studio, developers and agents can inspect code directly. Every script passes through static AST security checks before dispatch.
> 
> You don't need proprietary LLM API tokens here—Aperture handles the execution natively and exposes 19 Model Context Protocol tools for Claude, Cursor, and any autonomous framework."

---

## ШАГ 6. Вкладка Storage — артефакты и файлы (~20 сек)

### Что делать (Инструкция):
1. В левом меню нажмите на вкладку **Storage**.
2. Покажите список сохраненных файлов датасетов и отчетов с хэшами SHA-256.

### Что говорить на английском (Speech):
> "Finally, the Storage tab manages all input datasets and verified output artifacts. Everything is immutably hashed with SHA-256 and linked to on-chain task receipts."

---

## ШАГ 7. Финал и завершение (~15 сек)

### Что делать (Инструкция):
- Вернитесь на вкладку **Overview** или покажите репозиторий GitHub.

### Что говорить на английском (Speech):
> "To wrap up: our program is verified and deployed on Solana Devnet, all 46 protocol tests are passing, and the repo is open-source. Thank you, and I’d love to take your questions!"

---

## Шпаргалка для вопросов (если спросят)

- **"Do I need OpenAI / Anthropic keys?"**
  > "No, Aperture is the compute and escrow layer. Workloads run in sandboxed Python environments, so external LLM API tokens are not required."
- **"Why Solana?"**
  > "For sub-second finality, micro-payments in lamports, and cheap payment channels that prevent agents from overspending."
