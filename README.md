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
GEMINI_MODEL=gemini-2.5-flash
LLM_TEMPERATURE=0.1
MAX_ATTEMPTS=3
RETRY_BACKOFF_SECONDS=1.0
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
  Pydantic `response_schema`, щоб обмежити формат відповіді моделі.
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
- **Retry.** За замовчуванням максимум 3 спроби з backoff `1s -> 2s`. Retry
  застосовується і до API/timeout, і до невалідного JSON/Pydantic output, бо
  тимчасова помилка або нестабільна відповідь може зникнути. Після ліміту
  конкретний запит отримує явний `error`, а batch продовжується.

## Обмеження та що вже зроблено

| Проблема | Зараз | Що покращити в production |
|---|---|---|
| Nondeterminism LLM | Низька температура, фіксований prompt і enum/schema | Версіонувати prompt, додати eval-набір і regression checks |
| Помилкова класифікація | Визначення категорій у prompt, локальна schema validation | Human-in-the-loop для low-confidence випадків і метрики по категоріях |
| Invalid JSON/типи/enum | Gemini JSON schema плюс Pydantic і bounded retry | Окремий retry policy для permanent validation errors та dead-letter queue |
| API/network failures | До 3 спроб, exponential backoff, помилка лише для одного `id` | Circuit breaker, provider monitoring, черга та повторна обробка |
| Rate limits | Обмежені retries, без паралельного burst | Async/batching із rate limiter та backpressure |
| Великий CSV | Лінійна обробка з малою пам'яттю | Batch API, async workers, checkpoint/resume та caching |
| Token/API cost | Короткий prompt і одна LLM-операція на рядок | Token budget, дедуплікація, cache, batch pricing |
| Неоднозначний текст | `needs_clarification` і конкретне питання | Еталонний датасет, review queue і feedback loop |
| Поточна retry strategy | Простий максимум 3 спроби, помилки зберігаються у JSON | Класифікувати помилки на retryable/non-retryable і додати tracing |

## Що зробив би далі

1. Додати async/batch processing з обмеженням concurrency.
2. Зібрати невеликий labeled eval dataset і рахувати precision/recall/F1 для
   category, priority та needs_clarification.
3. Додати cache за hash нормалізованого `raw_text`.
4. Додати human review для сумнівних або high-priority запитів.
5. Підключити monitoring, Google Sheets/Telegram digest і deployment secrets.

## Тести

Реальний LLM API у тестах не викликається:

```powershell
pytest -q
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

