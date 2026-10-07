# Ультимативный сценарий 3-минутной живой демонстрации Aperture (Demo Day Runbook)

- **Общий хронометраж:** 3 минуты 00 секунд (180 секунд)
- **Условия показа:** Кошелек **Solflare уже подключен** к консоли на Devnet; внешние API-токены (OpenAI/Anthropic) **не требуются** (рантайм Aperture самодостаточен).
- **Формат:** Инструкции и экранные действия — на русском языке; реплики спикера (Speech) — на чистом презентационном английском языке.
- **Интерфейс:** Консоль Aperture (`http://localhost:3000` или Vercel деплой)
- **Сеть:** Solana Devnet
- **Ончейн-программа:** `A5HfdyRWy77i5DxhTMBa1ZinxVGZbVZnb35EvXUvkNzQ`

---

## 1. Чек-лист готовности за 2 минуты до выхода (Zero-Fail Setup)

1. Открыть браузер на странице `Overview` в полноэкранном режиме (**клавиша F11**).
2. Убедиться, что кошелек **Solflare уже подключен** в правом верхнем углу (отображается сокращенный адрес и бейдж сети `Devnet`).
3. Никаких API-ключей вводить не нужно: шлюз и песочница исполняют код автономно без зависимости от сторонних платных LLM-провайдеров.
4. Во второй фоновой вкладке браузера открыть репозиторий GitHub: `https://github.com/AliNurym/aperture-ai-gateway`.
5. В блоке симулятора на Overview активна вкладка: **Resilient CSV Pipeline**.

---

## 2. Посекундный план выступления (Хронометраж 3:00)

### Блок 1. Проблема и ценность продукта (0:00 – 0:35 | 35 секунд)

#### Что делать на экране:
- Вы находитесь на странице **Overview** в полноэкранном режиме.
- Курсор плавно наведен на заголовок `High-Assurance Compute for AI Agents`.
- Виден статус в правом верхнем углу: `DEVNET READY · PROTOCOL V2`.

#### Что говорить на английском (Speech):
> "Hi everyone! Today, AI agents are evolving from simple chatbots into autonomous systems that write and execute real code. But giving an agent uncontrolled compute is dangerous: you can never give an agent your corporate credit card or direct server access.
> 
> If your agent crashes midway through a heavy pipeline, you lose money and have to restart from scratch. If it gets trapped in an infinite reasoning loop, it can drain your wallet in minutes.
> 
> Aperture solves this. We provide a high-assurance compute gateway for AI agents, backed by Solana escrow guardrails, isolated sandboxes, and automatic crash recovery with zero duplicate charges."

---

### Блок 2. Ончейн-паспорт и Budget Guardrail (0:35 – 1:15 | 40 секунд)

#### Что делать на экране:
1. Плавно навести курсор на правый верхний угол: показать, что кошелек **Solflare уже подключен** и отображает адрес в сети `Devnet`.
2. Проскроллить страницу вниз до блока **Deterministic Execution Telemetry**.
3. Нажать на вторую вкладку: **Budget Guardrail (POLICY)**.
4. Нажать кнопку: **Test Budget Guardrail Rejection**.
5. Наблюдать мгновенный перехват: HTTP 403 Forbidden, статус `0 lamports debited`.

#### Что говорить на английском (Speech):
> "Notice in the top right that my Solflare wallet is already connected on Solana Devnet. The key architecture here: the owner never shares private keys or expensive API tokens with the agent. Instead, the owner issues an on-chain passport with a strict budget ceiling.
> 
> Take a look at this Budget Guardrail scenario. An autonomous agent attempts to execute an unconstrained job requesting 500,000 lamports, but our owner policy strictly capped it at 50,000.
> 
> When we trigger the run, our gateway intercepts the call before spinning up any worker process. It immediately returns an HTTP 403 Forbidden. Zero transactions hit the chain, zero lamports are debited, and the treasury stays completely safe."

---

### Блок 3. Главный бенчмарк: 17 000 строк CSV и Crash Recovery (1:15 – 2:10 | 55 секунд)

#### Что делать на экране:
1. Переключиться на первую вкладку: **Resilient CSV Pipeline (17K CSV)**.
2. Обратить внимание жюри на параметры: `Ceiling: 100,000 lamports cap`, `17,000 rows`.
3. Нажать большую фиолетовую кнопку: **Simulate 17,000-Row Crash Recovery**.
4. В течение 2.9 секунд на экране анимируется конвейер телеметрии (Stage -> Escrow -> Recovery -> Settlement). В этот момент произносите слова о сбое и восстановлении.
5. Появляется карточка результатов: покажите блок **State Journal Timeline** слева и артефакты **report.json** и **categories.csv** справа.

#### Что говорить на английском (Speech):
> "Now for our flagship benchmark: aggregating a private 17,000-row dataset. This dataset never enters the LLM prompt context—it runs inside an isolated CPU sandbox without requiring any external API keys.
> 
> Let’s trigger the pipeline. During Step 1, we simulate an intentional process interruption: the worker is abruptly killed. In any traditional setup, that means a total pipeline failure and double charges.
> 
> With Aperture, our gateway recovers state from the disk journal in just 18 milliseconds! It resumes execution exactly from the last committed offset.
> 
> Look at the verified audit trail: exactly zero duplicate tasks, zero extra fees, and the output report matches our baseline byte-for-byte."

---

### Блок 4. Криптографический пруф и Workload Studio (2:10 – 2:45 | 35 секунд)

#### Что делать на экране:
1. Внизу карточки результатов нажать кнопку **Verify Cryptographic Proof**.
2. В модальном окне показать зеленую плашку `Verified`, подписи Ed25519, хэши SHA-256.
3. Закрыть модальное окно (крестик или Esc).
4. Нажать кнопку **Inspect in Studio** (или перейти в раздел **Studio** в левом сайдбаре).
5. Показать код Python-воркера и параметры лимитов.

#### Что говорить на английском (Speech):
> "Every completed task is cryptographically attested. When we click 'Verify Cryptographic Proof', we see the full Ed25519 signatures from both worker and gateway, the SHA-256 code and output hashes, and the PDA receipt on Solana. The owner has mathematical proof of what was computed.
> 
> And inside Workload Studio, developers can inspect their workloads directly. Because Aperture handles compute deterministically, you don't depend on proprietary API tokens. For integration, Aperture exposes 19 Model Context Protocol tools to any agent framework."

---

### Блок 5. Финал и уверенный призыв к действию (2:45 – 3:00 | 15 секунд)

#### Что делать на экране:
- Вернуться на вкладку **Overview** (показать статус `Solana Devnet Program A5Hfdy... Verified`) либо переключиться на вторую вкладку с репозиторием GitHub.

#### Что говорить на английском (Speech):
> "To wrap up: Aperture turns risky agent code execution into a deterministic, budget-protected, and cryptographically verified workflow.
> 
> Our program is deployed on Solana Devnet, all 46 protocol tests are green, and the repository is completely open-source.
> 
> Thank you, and I’m ready for your questions!"

---

## 3. Таблица экстренных ответов на вопросы жюри (Emergency Q&A)

| Вопрос жюри | Что ответить на английском (Speech) | Пояснение для вас (на русском) |
|---|---|---|
| **"Do I need OpenAI or Anthropic API keys to use Aperture?"** | "No. Aperture separates reasoning from execution. We are the compute and settlement layer. Workloads run in sandboxed Python environments and MCP servers, so you don't need external LLM API tokens to execute bounded jobs." | Нужны ли API-ключи: Нет, Aperture — это слой вычислений и расчетов. Код крутится в песочнице, ключи LLM не требуются. |
| **"Why not run the computation directly on Solana smart contracts?"** | "On-chain compute is too expensive and constrained for processing 17,000 rows. Aperture uses an Off-Chain Compute with On-Chain Settlement model: heavy CPU computation runs in sandboxes, while Solana locks the escrow deposit and verifies cryptographic receipts." | Почему не ончейн: в блокчейне дорого считать тысячи строк; считаем в песочнице, сеттлим на Solana. |
| **"What prevents a malicious worker from returning fake data?"** | "The gateway validates the output structure and SHA-256 hash before co-signing the receipt. Escrow funds are only released from the payment channel when both worker and gateway signatures match the agreement." | Защита от мусора: шлюз проверяет хэш и схему. Без подписи шлюза эскроу воркеру не выплачивается. |
| **"How is this different from standard Docker containers?"** | "Docker only provides OS isolation. It doesn't enforce Solana payment channel budgets, it doesn't provide 18-millisecond journal resumption across crashes, and it doesn't integrate with 19 agent MCP tools." | Отличие от Docker: Docker — это просто изоляция, а Aperture дает экономический смарт-контракт, журнал без переплат и MCP. |

---

## 4. Паспорт проекта и ключевые факты (Шпаргалка)

- **Репозиторий:** `https://github.com/AliNurym/aperture-ai-gateway`
- **Программа смарт-контракта в Devnet:** `A5HfdyRWy77i5DxhTMBa1ZinxVGZbVZnb35EvXUvkNzQ`
- **Объем бенчмарка:** 17,000 строк CSV (16,983 валидные, 17 ошибок формата)
- **Скорость восстановления из журнала:** 18 мс
- **Покрытие тестами:** 46/46 фронтенд-тестов, 178 бэкенд-тестов
- **Интеграция:** 19 инструментов MCP (Model Context Protocol), Python SDK (`aperture_client`)
