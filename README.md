# Класифікація внутрішніх запитів через LLM

Невеликий Python-проєкт для первинної triage-обробки запитів із Slack,
Telegram та Email. Для кожного рядка `input_requests.csv` Gemini повертає
структурований результат: категорію, відділ, пріоритет, короткий опис,
конкретні дії та ознаку потреби в уточненні.

Проєкт не змінює `input_requests.csv` і не змінює файл із тестовим завданням.

## Архітектура

```text
CSV -> load_requests -> Gemini structured output
                         -> локальна Pydantic validation
                         -> per-request success/error result
                         -> output.json + report.md
```

Основні файли:

- `src/models.py` — enums і суворі Pydantic-моделі для input/output;
- `src/prompt.py` — компактний system prompt з правилами категоризації;
- `src/llm_client.py` — єдиний адаптер Google Gemini;
- `src/classifier.py` — retry, exponential backoff та ізоляція помилки одного запиту;
- `src/report.py` — детермінована агрегація результатів у Markdown;
- `src/main.py` — CLI entry point.

## Як встановити

Потрібен Python 3.11+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Після цього відкрий `.env` і додай API-ключ Gemini.

## Environment variables

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-3.5-flash-lite
MAX_ATTEMPTS=2
RETRY_BACKOFF_SECONDS=60
MAX_CONCURRENCY=1
```

Провайдер залишено окремою змінною для явної конфігурації, але поточна
реалізація свідомо підтримує лише Gemini: два провайдери для цього тестового
завдання додали б зайву складність.

## Як запустити

З кореня репозиторію:

```powershell
python -m src.main
```

За потреби шляхи можна змінити:

```powershell
python -m src.main --input input_requests.csv --output output.json --report report.md
```

Увімкнено стандартне logging: старт, кількість рядків, поточний `id`, retry,
помилки та завершення. API-ключ у логи не виводиться.

## Outputs

### `output.json`

Містить записи в тому самому порядку, що й CSV, і зберігає `id`, `channel` та
`timestamp`. Успішний запис має `classification`, а невдалий —
`classification: null` та об'єкт `error` з типом, повідомленням і кількістю
спроб. Це дозволяє не маскувати помилку вигаданою класифікацією.

Повний `raw_text` навмисно не дублюється: він уже є у вхідному CSV, а output
зберігає потрібні метадані та результат. Так менше зайвого копіювання тексту
внутрішніх повідомлень.

### `report.md`

Генерується програмно з `output.json`-подібних об'єктів і містить загальну
кількість, успішні/помилкові обробки, розподіли за категоріями, пріоритетами та
відділами, а також усі запити з `needs_clarification=true`.

## Design decisions

- **Gemini.** У ТЗ прямо вказаний безкоштовний tier Gemini. Використовується
  офіційний `google-genai` SDK і `response_mime_type=application/json` разом із
  явною Gemini-сумісною JSON-схемою, щоб обмежити формат відповіді моделі.
  Pydantic використовується додатково для локальної перевірки.
- **Pydantic.** Structured output не вважається достатньою гарантією: кожна
  відповідь додатково проходить локальну перевірку enum, типів, nullable-полів,
  списку дій та узгодженої пари `needs_clarification`/
  `clarification_question`. Незнайомі поля заборонені.
- **Prompt.** Описує різницю між категоріями, правило department=null без
  доказів, роботу зі змішаною мовою, кількома діями, out-of-scope повідомленнями
  та пріоритетом за бізнес-впливом, а не лише за словом «терміново».
- **`clarification_question`.** Це одне додаткове корисне поле для triage:
  замість загального «потрібно уточнення» результат одразу містить один
  найцінніший короткий question, який допоможе взяти запит у роботу.
- **Retry.** Для API/timeout і невалідного JSON/Pydantic output використовується
  bounded retry з backoff. Для безкоштовного tier у прикладі задано 2 спроби
  та паузу 60 секунд, щоб пережити ліміт запитів за хвилину.
  Retry застосовується і до API/timeout, і до невалідного JSON/Pydantic output, бо
  тимчасова помилка або нестабільна відповідь може зникнути. Після ліміту
  конкретний запит отримує явний `error`, а batch продовжується.

## Обмеження та що вже зроблено

| Проблема | Зараз | Що покращити в production |
|---|---|---|
| Nondeterminism LLM | Фіксований prompt і enum/schema; для Gemini 3.x `temperature` не передається | Версіонувати prompt, додати eval-набір і regression checks |
| Помилкова класифікація | Визначення категорій у prompt, локальна schema validation | Human-in-the-loop для low-confidence випадків і метрики по категоріях |
| Invalid JSON/типи/enum | Gemini JSON schema плюс Pydantic і bounded retry | Окремий retry policy для permanent validation errors та dead-letter queue |
| API/network failures | До 3 спроб, exponential backoff, помилка лише для одного `id` | Circuit breaker, provider monitoring, черга та повторна обробка |
| Rate limits | `MAX_CONCURRENCY` обмежує паралельність, retry/backoff обробляє тимчасовий 429; точного quota-aware rate limiter немає | Додати rate limiter та backpressure |
| Великий CSV | Лінійна обробка з малою пам'яттю | Batch API, async workers, checkpoint/resume та caching |
| Token/API cost | Короткий prompt і одна LLM-операція на рядок | Token budget, дедуплікація, cache, batch pricing |
| Неоднозначний текст | `needs_clarification` і конкретне питання | Еталонний датасет, review queue і feedback loop |
| Поточна retry strategy | Простий максимум 3 спроби, помилки зберігаються у JSON | Класифікувати помилки на retryable/non-retryable і додати tracing |

## Що зробив би далі

1. Додати quota-aware rate limiter та checkpoint/resume для великих batch.
2. Зібрати невеликий labeled eval dataset і рахувати precision/recall/F1 для
   category, priority та needs_clarification.
3. Додати cache за hash нормалізованого `raw_text`.
4. Додати human review для сумнівних або high-priority запитів.
5. Додати monitoring, provider fallback і CI-перевірку Docker-образу.

## Тести

Реальний LLM API у тестах не викликається:

```powershell
python -m pytest -q
python -m compileall -q src
```

Перевіряються Pydantic validation, invalid JSON/retry, результат після
вичерпання спроб та агрегація звіту.

## Optional bonus: Docker

Додано простий `Dockerfile` без ключів у image. Перед запуском контейнера
передай `.env` через `--env-file`:

```powershell
docker build -t request-classifier .
docker run --rm --env-file .env -v "${PWD}:/app" request-classifier
```

## Submission

У репозиторій не додаються `.env`, `secrets/`, `.venv/`, `__pycache__/` та
локальні generated outputs. Перевіряючий може створити власний `.env` на основі
`.env.example` і запустити `python -m src.main`.



## Optional integrations

### Async / batch processing

По умолчанию запросы обрабатываются асинхронными батчами с ограничением
MAX_CONCURRENCY=4. Gemini SDK остаётся синхронным, поэтому каждый вызов
выполняется в worker thread; одновременно не создаётся неограниченное число
API-запросов. Порядок результатов совпадает с порядком входного CSV.

### Google Sheets

Включается через:

~~~dotenv
GOOGLE_SHEETS_ENABLED=true
GOOGLE_SERVICE_ACCOUNT_FILE=secrets/google-service-account.json
GOOGLE_SHEET_ID=...
GOOGLE_WORKSHEET_NAME=classification_results
~~~

Нужно создать Google Cloud service account, включить Google Sheets API и Drive API,
скачать JSON-ключ в secrets/ и открыть нужную таблицу для email service
account с правами Editor. При каждом запуске worksheet очищается и заполняется
актуальным batch целиком. raw_text не отправляется в таблицу.

### Telegram digest

Включается через:

~~~dotenv
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_TIMEOUT_SECONDS=15
~~~

Бот должен иметь доступ к чату. Отправляется агрегированный digest с total,
категориями, приоритетами, ошибками и ID запросов, требующих уточнения. Токен
не логируется и не записывается в output.

Обе внешние публикации выполняются после локальной записи output.json и
report.md. Если Google Sheets или Telegram недоступны, локальные результаты
сохраняются, а ошибка попадает в logging.

### Docker

Dockerfile уже включает новые optional integrations. Сервисный JSON-ключ не
копируется в image; его нужно монтировать отдельно:

~~~powershell
docker build -t request-classifier .
docker run --rm --env-file .env -v "$((Get-Location).Path)\secrets:/app/secrets:ro" -v "$((Get-Location).Path):/app" request-classifier
~~~

## Submission

У репозиторій не додаються `.env`, `secrets/`, `.venv/`, `__pycache__/` та
локальні generated outputs. Перевіряючий може створити власний `.env` на основі
`.env.example` і запустити `python -m src.main`.

