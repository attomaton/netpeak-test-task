# Класифікація внутрішніх запитів через LLM

Python-застосунок для первинного triage внутрішніх запитів із Slack, Telegram та Email. Для кожного рядка `input_requests.csv` Gemini повертає структурований результат: категорію, цільовий відділ, пріоритет, короткий опис, запитані дії, ознаку потреби в уточненні та конкретне уточнювальне питання.

Проєкт не змінює вхідний CSV і не містить ключів або інших секретів.

## Реалізовано

Обов’язкова частина тестового завдання:

- читання та перевірка `input_requests.csv`;
- структурований JSON-вивід Gemini;
- сувора локальна валідація через Pydantic;
- ізоляція помилки окремого запиту;
- `output.json` у тому самому порядку, що й вхідні дані;
- `report.md` з агрегатами за категоріями, пріоритетами та відділами;
- список запитів, які потребують уточнення;
- README, тести, Dockerfile та історія Git.

Production-oriented покращення:

- quota-aware rate limiter для ліміту запитів провайдера;
- checkpoint/resume для великих batch;
- cache за SHA-256 хешем нормалізованого `raw_text`;
- асинхронна batch-обробка з обмеженням паралельності;
- черга human review для сумнівних, термінових та невдалих запитів;
- локальні operational metrics;
- опційний fallback-провайдер;
- labeled eval-набір і macro precision/recall/F1;
- Google Sheets, Telegram digest та CI-перевірка Docker-образу.

## Архітектура

```text
input_requests.csv
        |
        v
load_requests -> normalize/hash cache -> checkpoint lookup
        |
        v
bounded async batches -> rate limiter -> primary Gemini
                                      |
                                      +-> optional fallback
        |
        v
Pydantic validation -> output.json + report.md
                     -> review_queue.json
                     -> metrics.json
                     -> optional Google Sheets / Telegram
```

Основні модулі:

- `src/models.py` — суворі моделі input/output та enum-значення;
- `src/prompt.py` — правила категоризації й пріоритизації;
- `src/llm_client.py` — адаптер офіційного Google Gemini SDK;
- `src/classifier.py` — retry, валідація, cache, rate limiter та метрики;
- `src/async_processing.py` — bounded async/batch і checkpoint/resume;
- `src/cache.py` — нормалізація тексту та локальний JSON cache;
- `src/checkpoint.py` — атомарне збереження успішних результатів;
- `src/review.py` — формування черги ручної перевірки;
- `src/monitoring.py` — лічильники, latency та error metrics;
- `src/providers.py` — fallback-композиція та offline fallback;
- `src/eval.py` — оцінювання labeled dataset;
- `src/integrations.py` — Google Sheets і Telegram;
- `src/main.py` — CLI entry point.

## Встановлення

Потрібен Python 3.11+.

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Відкрий `.env` і додай власний ключ Gemini. Ключ не потрібно передавати автору тестового завдання та не можна комітити до Git.

## Налаштування

Мінімальна конфігурація:

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-3.5-flash-lite
MAX_ATTEMPTS=2
RETRY_BACKOFF_SECONDS=60
MAX_CONCURRENCY=1
RATE_LIMIT_REQUESTS_PER_MINUTE=15
RATE_LIMIT_WINDOW_SECONDS=60
```

Значення 15 запитів за 60 секунд відповідає типовому free tier, який використовувався під час перевірки. Якщо в акаунта інша квота, параметри можна змінити. Значення 0 для `RATE_LIMIT_REQUESTS_PER_MINUTE` вимикає локальне обмеження.

Локальні можливості:

```dotenv
CACHE_ENABLED=true
CACHE_FILE=.cache/classifications.json

CHECKPOINT_ENABLED=true
CHECKPOINT_FILE=.cache/checkpoint.json

HUMAN_REVIEW_ENABLED=true
REVIEW_FILE=review_queue.json

MONITORING_ENABLED=true
MONITORING_FILE=metrics.json
```

Fallback вимкнений за замовчуванням:

```dotenv
LLM_FALLBACK_ENABLED=false
LLM_FALLBACK_PROVIDER=heuristic
GEMINI_FALLBACK_MODEL=
```

Підтримані fallback-варіанти:

- `heuristic` — локальний консервативний fallback без додаткового API; його результати мають потрапляти до human review;
- `gemini` — друга модель Gemini, для якої потрібно вказати `GEMINI_FALLBACK_MODEL`.

Google Sheets:

```dotenv
GOOGLE_SHEETS_ENABLED=true
GOOGLE_SERVICE_ACCOUNT_FILE=secrets/google-service-account.json
GOOGLE_SHEET_ID=...
GOOGLE_WORKSHEET_NAME=classification_results
```

Telegram:

```dotenv
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_TIMEOUT_SECONDS=15
```

## Запуск

З кореня репозиторію:

```powershell
python -m src.main
```

Зі своїми шляхами:

```powershell
python -m src.main --input input_requests.csv --output output.json --report report.md
```

За потреби шляхи службових файлів можна змінити прапорцями `--checkpoint`, `--cache`, `--review-output` та `--metrics-output`.

### Rate limiter

Перед кожною реальною спробою до LLM викликається потокобезпечний sliding-window limiter. Це не гарантує квоту провайдера, але не дозволяє застосунку навмисно перевищувати заданий локальний ліміт. Якщо Gemini повертає `RetryInfo`, його затримка також враховується.

### Checkpoint/resume

Після завершення кожного запиту результат атомарно записується до checkpoint. Під час повторного запуску повторно використовуються лише успішні результати для того самого `id` і того самого хешу нормалізованого `raw_text`. Невдалі записи не блокують повторну спробу, а зміна тексту автоматично робить старий checkpoint непридатним.

Щоб виконати повний повторний запуск, видали локальний файл `.cache/checkpoint.json`.

### Cache

Застосунок нормалізує Unicode, регістр і пробіли, після чого обчислює SHA-256. У cache зберігаються лише успішні структуровані класифікації; API-ключ і сирий текст не зберігаються. Cache корисний для дубльованих або повторно оброблених запитів.

### Human review

Файл `review_queue.json` формується без блокування batch. До нього потрапляють:

- `needs_clarification=true`;
- `priority=high`;
- `поза скоупом` як потенційно неоднозначні повідомлення;
- запити з помилкою обробки.

Для кожного елемента зберігаються причина, вхідний текст, класифікація або помилка та поля `status`/`reviewer_notes` для ручного опрацювання. Файл містить внутрішній текст, тому залишається локальним і не комітиться.

### Monitoring

`metrics.json` не містить raw text або секретів. Він містить кількість успішних та невдалих запитів, cache hit, спроб і повторів, використань fallback, загальний час, середню latency, p95 latency та розподіл типів помилок.

## Результати

### `output.json`

Зберігає записи у тому самому порядку, що й CSV. Успішний запис має `classification`, невдалий — `classification: null` та об’єкт `error` з типом, повідомленням і кількістю спроб. Повний `raw_text` навмисно не дублюється в output.

### `report.md`

Генерується програмно та містить загальну кількість, успішні/помилкові обробки, розподіл за `category`, `priority`, `target_department`, запити для уточнення та помилки.

### Google Sheets

Для ввімкненої інтеграції worksheet очищується і заповнюється актуальним batch. У таблицю потрапляють структуровані поля, але не raw text. Потрібно створити service account, увімкнути Google Sheets API та Google Drive API, зберегти JSON-ключ у `secrets/` і надати service account доступ Editor до потрібної таблиці.

### Telegram

Надсилається агрегований digest із загальною кількістю, категоріями, пріоритетами, помилками та ID запитів для уточнення. Повідомлення автоматично розбивається, якщо перевищує ліміт Telegram.

Зовнішні публікації виконуються після запису локальних файлів. Збій Google Sheets або Telegram не стирає локальні результати.

## Оцінювання якості

У репозиторії є вручну розмічений набір із 10 прикладів: `eval/labeled_requests.csv`. Він містить очікувані значення для `category`, `priority` та `needs_clarification`. Це regression smoke-набір, а не статистично репрезентативна оцінка всієї системи.

Спочатку отримай передбачення:

```powershell
python -m src.main --input eval/labeled_requests.csv --output eval/predictions.json --report eval/report.md
```

Потім розрахуй macro precision, recall, F1 та accuracy:

```powershell
python -m src.eval --dataset eval/labeled_requests.csv --predictions eval/predictions.json --output eval/metrics.json
```

Оцінювання працює з уже отриманим `predictions.json` і не викликає додатковий API.

## Тести та CI

Реальний LLM API у тестах не викликається:

```powershell
python -m pytest -q
python -m compileall -q src
```

Тести перевіряють Pydantic validation, retry, async batch, Google Sheets/Telegram fake-клієнти, cache, checkpoint/resume, human review, fallback, monitoring та precision/recall/F1.

GitHub Actions автоматично запускає тести, перевірку синтаксису та збірку Docker-образу на кожному push і pull request. Docker-перевірка не використовує API-ключ.

## Docker

Образ не містить ключів. Секрети передаються під час запуску:

```powershell
docker build -t request-classifier .
docker run --rm --env-file .env -v "$((Get-Location).Path):/app" request-classifier
```

Для Google service account змонтуй secrets окремо:

```powershell
docker run --rm --env-file .env -v "$((Get-Location).Path):/app" -v "$((Get-Location).Path)\\secrets:/app/secrets:ro" request-classifier
```

## Обмеження та рішення

| Ризик | Поточне рішення | Наступний production-крок |
|---|---|---|
| Нестабільність LLM | фіксований prompt, JSON schema, локальна Pydantic validation | версіонування prompt і розширення eval-набору |
| Невалідний JSON або enum | structured output, validation, bounded retry | окрема класифікація retryable/permanent помилок |
| Перевищення квоти | sliding-window limiter і RetryInfo backoff | централізована quota-політика для кількох worker |
| Великий CSV | async batch, checkpoint/resume, cache | черга задач і durable storage |
| Дублікати | hash cache | TTL/LRU та спільний cache |
| Сумнівні результати | human review queue | збереження рішень reviewer і feedback loop |
| Збій провайдера | опційний fallback | незалежний provider з контрактними тестами |
| Спостережуваність | локальний metrics.json і logging | Prometheus/OpenTelemetry та алерти |
| Витрати API | короткий prompt, cache, rate limiter | token budget і розрахунок вартості |
| Приватність | секрети поза Git, raw text лише у локальній review queue | retention, шифрування та контроль доступу |

## Подача

У репозиторій не додаються `.env`, `secrets/`, `.venv/`, `__pycache__/`, локальні generated outputs, checkpoint, cache та review queue.

Перевіряючий може скопіювати `.env.example` у `.env`, додати власний ключ Gemini та виконати тести або CLI-запуск.
