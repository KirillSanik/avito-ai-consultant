# Contract: LLM Structured Output

**Feature**: 001-homework-ai-detector | **Стороны**: `LLMJudge` (клиент) ↔ локальный LLM-сервер (vLLM/Triton, OpenAI-совместимый API)
База: ТЗ §5 (промпты) и §4.5 (механизм `beta.chat.completions.parse`); research §8–§10.

## 1. Формат обмена

- Протокол: OpenAI Chat Completions (совместимый), endpoint `base_url` задаётся при создании `AsyncOpenAI`.
- Механизм: `client.beta.chat.completions.parse(model=..., messages=[...], response_format=AIAssessmentResult, temperature=0)`.
- SDK сериализует pydantic-модель в `response_format: {"type": "json_schema", "json_schema": {..., "strict": true}}` — сервер обязан возвращать **строго** валидный JSON по схеме.
- Результат читается **только** как `response.choices[0].message.parsed` (объект `AIAssessmentResult`). `parsed is None` → `LLMJudgementError` (повторяется retry'ем). Regex-парсинг raw-текста ответа — запрещён (конституция §3).

## 2. Параметры запроса

| Параметр | Значение | Примечание |
|----------|----------|------------|
| `model` | `AI_DETECTOR_LLM_MODEL` или дефолтная константа | локальная модель с поддержкой Structured Output |
| `temperature` | `0` | детерминированность (SC-005) |
| `messages[0]` | role `system` | §3 |
| `messages[1]` | role `user` | §4 |
| `response_format` | pydantic-модель `AIAssessmentResult` | strict JSON schema |

## 3. System Prompt (дословно из ТЗ §5)

> Ты — старший инженер по код-ревью и эксперт по детекции AI-генерации в коде. Твоя задача — проанализировать предоставленный код и метаданные репозитория и вынести вердикт о вероятности его генерации ИИ.
>
> **КРИТЕРИИ ВЕРДИКТА (СТРОГО СОБЛЮДАЙ):**
> - 🟢 **GREEN (Человек):** Постепенная история коммитов с осмысленными сообщениями. Наличие неидеальностей, специфичные для задачи имена переменных. Код решает именно поставленную задачу, учитывая её нюансы. Комментарии по делу.
> - 🟡 **YELLOW (Смешанный/Подозрительный):** Код качественный, но история коммитов подозрительна (например, 1-2 коммита с разницей в минуту). Присутствуют избыточные, "водянистые" комментарии в стиле ИИ ("Этот код делает...", "Создаем переменную"), но видна попытка ручной адаптации под специфичные критерии задачи.
> - 🔴 **RED (ИИ-слоп/Копипаст):** Один коммит ("initial commit"). Идеальная, но бездушная структура. Галлюцинации в комментариях. Код решает общую абстрактную задачу, игнорируя специфические ограничения из критериев. Наличие артефактов нейросетей в коде или коммитах (например, "Конечно, вот ваш код", "Sure, here is the solution").
>
> Твой ответ должен быть строго в формате JSON, соответствующем предоставленной Pydantic-схеме. Не добавляй никакой текст вне JSON.

Дополнительные контрактные инструкции (прикручиваются к концу system prompt): обоснование и списки признаков — на русском языке; поле `task_compliance_score` не заполнять и не выдумывать (FR-009).

## 4. User Prompt (шаблон, дословно из ТЗ §5)

```text
**1. КРИТЕРИИ ЗАДАНИЯ:**
{task_criteria}

**2. МЕТАДАННЫЕ РЕПОЗИТОРИЯ:**
- Структура файлов: {file_tree}
- История коммитов: {commit_history_formatted}

**3. ПОЛНЫЙ ИСХОДНЫЙ КОД:**
{full_code}
```

Заполнители:
- `{file_tree}` — полный список файлов HEAD (строки путей, `git ls-files`).
- `{commit_history_formatted}` — по одному коммиту на строку: `<hash[0..7]> | <date ISO> | <author> | <message>`.
- `{full_code}` — агрегированный код с маркерами:

```text
--- FILE: path/to/file.py ---
[полное содержимое файла, без усечения]
--- END FILE ---
```

## 5. Strict JSON-схема ответа (mirror pydantic-модели)

```json
{
  "type": "object",
  "properties": {
    "status": {
      "type": "string",
      "enum": ["green", "yellow", "red"],
      "description": "Вердикт: 'green' (человек), 'yellow' (смешанный/подозрительный), 'red' (явный ИИ/копипаст)"
    },
    "confidence": {
      "type": "number",
      "minimum": 0.0,
      "maximum": 1.0,
      "description": "Уверенность модели в вердикте от 0.0 до 1.0"
    },
    "reasoning": {
      "type": "string",
      "description": "Подробное, аргументированное обоснование вердикта на русском языке"
    },
    "ai_indicators": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Список конкретных признаков, указывающих на генерацию ИИ"
    },
    "human_indicators": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Список признаков, указывающих на человеческую работу"
    }
  },
  "required": ["status", "confidence", "reasoning", "ai_indicators", "human_indicators"],
  "additionalProperties": false
}
```

## 6. Повторные попытки (контракт на сбои)

| Сбой | Повторяется? | Итог |
|------|--------------|------|
| Таймаут / `APIConnectionError` / `RateLimitError` / `APIStatusError` (5xx) | да, до 3 попыток, `wait_exponential(min=1s, max=10s)` | успех → результат; исчерпано → `LLMJudgementError` |
| `parsed is None` (ответ не по схеме) | да (там же) | исчерпано → `LLMJudgementError` |
| `NotFound` (404: модель/эндпоинт) | **нет** | немедленный `LLMJudgementError` |
| Context overflow (400, объём кода > вместимости) | **нет** | немедленный `LLMJudgementError`: «объём превышает вместимость модели, усечение запрещено» |

## 7. Инварианты

1. В запросе **полный** код всех поддерживаемых файлов — усечение на стороне клиента запрещено (FR-004).
2. Схема ответа **не содержит** `task_compliance_score` (FR-009); `additionalProperties: false`.
3. `confidence` вне `[0.0, 1.0]` — невалидный ответ → ветка `parsed is None`/validation → retry.
4. Никакой токен, путь к temp-каталогу или служебные данные окружения не передаются в LLM.
