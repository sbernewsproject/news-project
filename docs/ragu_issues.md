# GraphRAG / RAGU — исследовательский документ

## 1. Мотивация: зачем GraphRAG в новостном пайплайне

Текущий pipeline работает на dense-RAG: запрос → вектор → Qdrant → top-K чанков → reranker → LLM. Этот подход хорошо находит **конкретные факты**, упомянутые в одном источнике. Но он плохо справляется со следующими классами запросов:

- *«Какие компании участвовали в сделках за последний квартал?»* — ответ размазан по сотням статей, ни один чанк не содержит полный список
- *«Как менялась ключевая ставка в 2024–2025 годах?»* — нужна агрегация временных данных из множества источников
- *«Кто связан с проектом Х?»* — требует обхода цепочки отношений: человек → компания → проект
- *«Каковы тенденции в банковском секторе?»* — глобальный вопрос без точного ответа в одном чанке

Исследование *«RAG vs. GraphRAG: A Systematic Evaluation and Key Insights»* (2025) показывает: GraphRAG превосходит dense-RAG на **+27.23% по multi-hop QA** при практически одинаковом качестве на single-hop вопросах. Dense-RAG и GraphRAG демонстрируют **взаимодополняющие** возможности — идеальный pipeline использует оба подхода.

В нашем роутинге (`rag/chain.py`) это уже заложено: `global` и `local` маршруты вызывают `global_search`/`local_search` из графа, а `dense` — чистый векторный поиск.

---

## 2. Теоретическая основа: Microsoft GraphRAG (2024)

**Статья:** *«From Local to Global: A Graph RAG Approach to Query-Focused Summarization»*, Edge et al., апрель 2024.  
**Источник:** [arxiv.org/abs/2404.16130](https://arxiv.org/pdf/2404.16130)

### 2.1 Пайплайн построения графа

```
Текст документов
       │
       ▼
  [Stage 1] Извлечение сущностей и отношений
       │    NER-модель (ragu-lm) → (субъект, предикат, объект)
       ▼
  [Stage 2] Векторизация сущностей и отношений
       │    Embedding-модель (bge-m3) → векторы в Qdrant
       ▼
  [Stage 3] Обнаружение сообществ
       │    Алгоритм Leiden → иерархические кластеры
       ▼
  [Stage 4] Суммаризация сообществ
             LLM (qwen3:32b) → текстовое резюме по каждому кластеру
```

### 2.2 Алгоритм Leiden (Community Detection)

Leiden — улучшенная версия алгоритма Louvain. Microsoft выбрал его по двум причинам:

1. **Refinement phase**: после начальной группировки Leiden проверяет, что каждое сообщество внутренне связно — нет изолированных узлов внутри кластера. Louvain может оставлять «дыры».
2. **Иерархичность**: Leiden рекурсивно разбивает сообщества на под-сообщества, создавая граф с несколькими уровнями детализации. Это позволяет отвечать на вопросы разной степени общности.

Результат: каждый узел (сущность) принадлежит ровно одному сообществу на каждом уровне иерархии — взаимоисключающее, исчерпывающее разбиение.

### 2.3 Два режима поиска

**local_search** — поиск вокруг конкретной сущности:
1. Найти сущности, близкие к запросу по вектору
2. Обойти граф: взять все связанные узлы и рёбра
3. Собрать контекст из найденного подграфа + исходные чанки
4. LLM генерирует ответ

**global_search** — тематический обзор:
1. Загрузить суммари всех сообществ (или верхних уровней иерархии)
2. LLM генерирует промежуточные ответы по каждому суммари (map phase)
3. LLM агрегирует промежуточные ответы в финальный (reduce phase)

Global search дорогой по токенам, зато отвечает на вопросы о тенденциях и обзорах.

---

## 3. Архитектура ragu-lm

### 3.1 Что это за модель

**ragu-lm — это дообученный Qwen3-0.6B**, специализированный на извлечении структурированной информации для графов знаний на русском языке.

- **HuggingFace:** [RaguTeam/RAGU-lm](https://huggingface.co/RaguTeam/RAGU-lm)
- **Базовая модель:** Qwen3-0.6B (600M параметров)
- **Формат в Ollama:** GGUF Q8_0 — 8 бит на параметр
- **Размер файла:** 639 MB (≈ 0.6B × 8 бит ÷ 8 = 600 MB + overhead)
- **Задача:** принять на вход чанк текста, вернуть список триплетов `(субъект, предикат, объект)` на русском

### 3.2 Почему именно 0.6B, а не больше

Для задачи NER + relation extraction большая модель не нужна: это структурированное извлечение по чёткому шаблону, а не свободная генерация. Дообучение на специализированном датасете русскоязычных текстов компенсирует меньший размер. Главный плюс — скорость: 0.6B помещается в память многократно, допускает высокий параллелизм.

### 3.3 Сравнение с альтернативами

| Модель/подход | Размер | Качество | Скорость | Тип отношений |
|---|---|---|---|---|
| **ragu-lm (Qwen3-0.6B)** | 639 MB | хорошее (RU-специфика) | GPU: быстро | семантические |
| GliNER (в проекте) | ~200 MB | только NER, без отношений | CPU: быстро | нет |
| qwen3:32b как ragu-lm | 20 GB | отлично | медленно | семантические |
| Co-occurrence граф | 0 MB | слабое (шум) | мгновенно | нет |
| spaCy + правила | ~50 MB | среднее | быстро | ограниченные |

**Вывод:** ragu-lm — оптимальный баланс для нашей задачи. Проблема только в инфраструктуре.

---

## 4. Анализ производительности

### 4.1 Железо

| Параметр | Значение |
|---|---|
| GPU | Tesla V100-SXM2-16GB |
| GPU VRAM | 16 GB HBM2 |
| Memory bandwidth | **900 GB/с** (NVLink) |
| Наши GPU | 0, 1 (32 GB суммарно) |
| Свободные GPU | 2–7 (нужно проверить через `nvidia-smi`) |
| Датасет | ~727 000 статей → 1 688 838 чанков |

### 4.2 Теоретическая скорость ragu-lm на V100

LLM inference на GPU ограничен **memory bandwidth** (для малых batch size): время генерации одного токена ≈ размер модели / bandwidth.

```
Время на 1 токен (теория) = 0.639 GB / 900 GB/с ≈ 0.00071 с = 0.71 мс
Теоретический потолок       ≈ 1 400 токенов/с
Реалистично (Ollama, ~40%)  ≈ 400–600 токенов/с
```

Один чанк (800 входных + ~250 генерируемых токенов):

| Этап | Токены | Скорость | Время |
|---|---|---|---|
| Prefill (ввод) | 800 | ~3 000 токенов/с (параллельный) | ~0.27 с |
| Decode (вывод) | 250 | ~500 токенов/с | ~0.50 с |
| **Итого/чанк** | | | **~0.8–1.5 с** |

### 4.3 Наши реальные замеры

| Конфигурация | Время/чанк | Объяснение |
|---|---|---|
| qwen3 на GPU + ragu-lm конкурируют | **~400 с** | ragu-lm вытеснен на CPU; KV-кэш OLLAMA_NUM_PARALLEL=3 занимает весь VRAM |
| qwen3 выгружен (`keep_alive: 0`) | **~147 с** | ragu-lm всё ещё на CPU — Ollama не переместил модель мгновенно, или она всё равно не влезала |
| Выделенный GPU (прогноз) | **~1–2 с** | ragu-lm постоянно в VRAM, без конкуренции |

**Вывод: 147 с/чанк — это CPU-скорость.** Типичный сервер имеет bandwidth ~50–100 GB/с (DDR5 ECC), что даёт в 9–18 раз медленнее, чем V100 HBM2. Расчёт: 147 с × (50/900) ≈ 8 с/чанк — близко к нашему прогнозу для GPU.

### 4.4 Прогноз: выделенный GPU, rate_max_simultaneous

ragu-lm (639 MB) занимает ~0.64 GB из 16 GB VRAM. Для Q8 квантизации KV-кэш одного запроса при контексте 1024 токена ≈ 0.6B × 2 layers × 2 (K+V) × 1024 × 2 bytes ≈ незначительно. Фактически можно держать 15–20 параллельных запросов.

| rate_max_simultaneous | Время/чанк (GPU) | Всего (1 688 838 чанков) |
|---|---|---|
| 1 | ~1.5 с | ~29 дней |
| 5 | ~1.5 с | ~6 дней |
| **10** | **~1.5 с** | **~3 дня** |
| 15 | ~1.5 с | ~2 дня |
| 20 | ~1.5 с | ~1.5 дня |

### 4.5 Ollama vs vLLM для batch-обработки

Ollama удобен для интерактивных запросов, но при высоком параллелизме vLLM значительно эффективнее благодаря **continuous batching** (PagedAttention).

| Движок | Throughput (8B, 8 параллельных) | Плюсы | Минусы |
|---|---|---|---|
| **Ollama** | ~41 токен/с суммарно | простота, Ollama-API | sequential queue, нет continuous batching |
| **vLLM** | ~793 токен/с суммарно | continuous batching, x19 throughput | сложнее в настройке, нет GGUF |
| **llama.cpp server** | средне | GGUF, встроен в Ollama | нет PagedAttention |

Источник: [markaicode.com/benchmarks/ollama-vs-vllm-performance](https://markaicode.com/benchmarks/ollama-vs-vllm-performance/)

**Если использовать vLLM вместо Ollama для ragu-lm** (потребуется HuggingFace-версия модели):
- throughput может вырасти в 5–10x при высоком параллелизме
- 3 дня → возможно **менее 1 дня**
- Но: нужно адаптировать `build_graph.py` под OpenAI-совместимый API vLLM (он его поддерживает)

---

## 5. Сравнение: GraphRAG vs Dense RAG

### 5.1 Когда GraphRAG выигрывает

Согласно *«RAG vs. GraphRAG: A Systematic Evaluation»* (2025) и *«When to use Graphs in RAG»* (2025):

| Тип запроса | Dense RAG | GraphRAG | Победитель |
|---|---|---|---|
| Конкретный факт из одного источника | ✅ отлично | ✅ хорошо | Dense |
| Multi-hop (A → B → C) | ❌ плохо | ✅ отлично (+27%) | Graph |
| Глобальный обзор темы | ❌ плохо | ✅ отлично | Graph |
| Перечисление всех X, связанных с Y | ❌ неполно | ✅ хорошо | Graph |
| Временная динамика | ❌ плохо | ✅ через связи | Graph |
| Семантически близкий текст | ✅ отлично | ❌ не то | Dense |

### 5.2 Роутинг в нашем проекте

В `rag/chain.py` уже реализован эвристический роутер:
- `global` — слова «тенденция», «обзор», «динамика», длинный запрос
- `local` — имена собственные, «кто», «какие компании»
- `dense` — всё остальное

При наличии графа архитектура станет полноценной dual-channel retrieval системой.

---

## 6. Метрики качества графа

При построении графа важно измерять:

### 6.1 Качество извлечения (offline)

- **Precision NER** — доля верно извлечённых сущностей среди всех извлечённых
- **Recall NER** — доля верно извлечённых среди всех реальных
- **F1 для триплетов** — F1 по парам (субъект, объект), т.к. тип отношения сложнее оценить автоматически
- **Hit@1** — попадает ли правильная сущность на первое место при поиске

### 6.2 Качество поиска (online)

- Процент запросов, для которых `local_search`/`global_search` возвращают непустой контекст
- Сравнение ответов модели: с графом vs без графа (human evaluation или LLM-as-judge)
- Hallucination rate: доля ответов с выдуманными фактами

### 6.3 Структурные метрики графа

- **Число сущностей** (ожидаем десятки тысяч для 727к статей)
- **Число отношений** (обычно в 3–5 раз больше числа сущностей)
- **Средняя степень узла** (degree distribution)
- **Число сообществ** и их размеры на каждом уровне иерархии
- **Isolated nodes** (должны быть удалены: `remove_isolated_nodes=True`)

---

## 7. Технические детали нашего стека

### 7.1 graph-ragu — 4 стадии построения

```
Stage 1/4  Extraction     ragu-lm извлекает триплеты из каждого чанка
Stage 2/4  Vectorization  bge-m3 кодирует сущности и отношения в векторы
Stage 3/4  Clustering     Leiden выделяет сообщества сущностей
Stage 4/4  Summarization  qwen3:32b пишет суммари для каждого сообщества
```

Самая долгая стадия: **Stage 1** (LLM-вызов на каждый чанк).  
Самая ресурсоёмкая: **Stage 4** (qwen3:32b суммирует каждое сообщество — это происходит один раз).

### 7.2 Настройки в `graph/build_graph.py`

```python
KnowledgeGraph(
    chunker=SimpleChunker(max_chunk_size=800, overlap=120),
    artifact_extractor=RaguLmArtifactExtractor(llm=ragu_lm, temperature=0.0),
    builder_settings=BuilderArguments(
        use_llm_summarization=True,    # qwen3 пишет суммари по сущностям
        use_clustering=True,           # Leiden community detection
        make_community_summary=True,   # qwen3 пишет суммари по кластерам
        remove_isolated_nodes=True,    # чистка одиночных узлов
    ),
)
```

### 7.3 Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | URL Ollama для LLM (qwen3) и эмбеддингов |
| `OLLAMA_MODEL` | `qwen3:32b` | Основная LLM для суммаризации |
| `RAGU_LM_MODEL` | `ragu-lm` | Модель для извлечения сущностей |
| `GRAPH_WORKING_DIR` | `./ragu_working_dir` | Папка хранения графа |
| `POSTGRES_DSN` | — | Подключение к БД со статьями |

Планируемое добавление: `RAGU_LM_URL` — отдельный URL для ragu-lm Ollama.

---

## 8. Проблемы, которые мы решили

### 8.1 Неправильный пакет при установке
`pip install ragu` ставит чужой пакет с PyPI.  
**Решение:** `pip uninstall ragu && pip install graph-ragu`

### 8.2 `TypeError: 'coroutine' object is not iterable` — баг в библиотеке
Stage 1 завершался с 0 сущностей. В `ragu_lm_artifact_extractor.py:300` метод `_run` вызывает `batch_chat_completion()` без `await`.  
**Решение:** monkey-patch в `graph/build_graph.py` (нет прав на редактирование venv):

```python
from ragu.triplet import ragu_lm_artifact_extractor as _ragu_ext

async def _patched_run(self, conversations, description=""):
    return await self.llm.batch_chat_completion(
        [c.to_openai() for c in conversations],
        output_schema=str,
        continue_on_error=True,
        temperature=self.temperature,
        top_p=self.top_p,
        desc=description,
    )

_ragu_ext.RaguLmArtifactExtractor._run = _patched_run
```

### 8.3 Модели не найдены в Ollama
**Причина:** системный Ollama (порт 11434) не знает о наших моделях в `/raid/seva/ollama_models/`.  
**Решение:** `OLLAMA_MODELS=/raid/seva/ollama_models OLLAMA_HOST=127.0.0.1:11436 ollama serve`

### 8.4 Свапинг моделей — ragu-lm уходит на CPU
qwen3:32b (20 GB) + NUM_PARALLEL=3 KV-кэш заполняет 32 GB VRAM → ragu-lm (639 MB) вытесняется.  
**Временное решение:** выгрузить qwen3 перед запуском.  
**Правильное решение:** выделенный GPU.

### 8.5 Первый полный прогон — 0 сущностей после 6 часов
1 688 838 чанков, extraction — 28 минут, vectorization — 5 часов, результат: 0 entities.  
**Причина:** баг 8.2 + неверный OLLAMA_URL (8.3). После патчей повторный запуск на полном датасете ещё не делался.

---

## 9. Хроника экспериментов: практический опыт

### 9.1 Как мы вообще дошли до RAGU

До запуска RAGU pipeline работал на dense-RAG (Qdrant + reranker). В процессе разработки выяснилось, что `global_search` и `local_search` в `rag/chain.py` уже заложены в роутер — но граф пустой и они возвращали пустой результат. Решили построить граф и наполнить его реальными данными.

### 9.2 Проблема с портами Ollama на DGX

На момент начала работы на DGX уже работали **два** Ollama-инстанса, о которых мы не знали:

| Порт | Процесс | Владелец | Модели |
|---|---|---|---|
| 11434 | системный Ollama | пользователь `neweagle`, PID 5024 | чужие, без qwen3/bge-m3 |
| 11435 | Docker-Ollama | Docker daemon | — |
| **11436** | **наш Ollama** | **seva** | qwen3:32b, bge-m3, ragu-lm |

Первоначально `OLLAMA_URL` указывал на порт 11434 (системный) — именно поэтому при первых запросах вылетало `model 'ragu-lm' not found` и `model 'bge-m3' not found`. Исправили на 11436.

Наши модели хранились в `/raid/seva/ollama_models/`, но системный Ollama их не видел. Нашли через:
```bash
find /home /raid -maxdepth 5 -name "manifests" -type d
# Результат: /raid/seva/.ollama/models/manifests
#            /raid/seva/ollama_models/manifests
```

Запуск нашего Ollama:
```bash
CUDA_VISIBLE_DEVICES=0,1 OLLAMA_MODELS=/raid/seva/ollama_models \
  OLLAMA_HOST=127.0.0.1:11436 OLLAMA_NUM_PARALLEL=3 \
  nohup ollama serve > /raid/seva/ollama.log 2>&1 &
```

Попытка писать лог в `~/.ollama2.log` упала с `Permission denied` — файл был занят другим процессом. Решение: писать в `/raid/seva/`.

### 9.3 Первый полный прогон: 0 сущностей после 6 часов

Запустили `python -m graph.build_graph` на полном датасете:

| Стадия | Время | Результат |
|---|---|---|
| Stage 1/4 Extraction | 28 минут | 0 сущностей, 0 связей |
| Stage 2/4 Vectorization | 5 часов | выполнена (но векторизовать нечего) |
| Итог | 6 часов | **пустой граф** |

Extraction прошёл за 28 минут потому, что из-за бага `coroutine not awaited` каждый вызов к ragu-lm молча возвращал пустоту — обработка шла без ожидания ответа. По факту ни один чанк обработан не был.

### 9.4 Поиск бага: `coroutine not awaited`

После нулевого результата начали разбираться. Нашли в логах `TypeError: 'coroutine' object is not iterable`. Локализовали в исходниках библиотеки:

```bash
grep -n "batch_chat_completion\|_run\|return" \
  .venv/lib/python3.12/site-packages/ragu/triplet/ragu_lm_artifact_extractor.py
# строка 300: return self.llm.batch_chat_completion(...)  ← нет await
```

Попытка исправить через `sed` завершилась `Permission denied` — файлы venv принадлежат другому пользователю.

Написали monkey-patch. Первая попытка упала с новой ошибкой:
```
AttributeError: type object 'RaguLmArtifactExtractor' has no attribute '_run'
```
Причина: использовали неправильное имя класса `RaguLMArtifactExtractor` (с заглавной M) вместо `RaguLmArtifactExtractor` (строчная m). После исправления патч заработал.

### 9.5 Тест на 20 статьях: замер реальной скорости

Написали `scripts/test_graph.py` — прогон на 20 последних статьях из Postgres. Результаты:

| Параметр | Значение |
|---|---|
| Статей | 20 |
| Чанков | 51 |
| Скорость (типичная) | **141–155 с/чанк** |
| Скорость (с ретраем) | **173 с/чанк** |
| Полное время прогона | ~2 ч 30 мин |
| Прогресс за 7 минут | 3/51 чанка = **2%** |

На момент теста qwen3:32b был загружен в GPU. Конфигурация: `OLLAMA_NUM_PARALLEL=3`, обе модели в одном Ollama-инстансе.

### 9.6 Механика свапинга: почему ragu-lm уходит на CPU

Детальная картина того, что происходит с памятью:

```
GPU 0 (16 GB) + GPU 1 (16 GB) = 32 GB суммарно

qwen3:32b модель:          ~20 GB
KV-кэш при NUM_PARALLEL=3: ~10–12 GB (3 слота × ~3.5 GB каждый)
─────────────────────────────────────
Итого qwen3:               ~32 GB  ← заполняет весь VRAM

ragu-lm (639 MB):          не влезает → уходит на CPU (RAM)
```

CPU RAM bandwidth на сервере: ~50–100 GB/с (DDR5 ECC).  
V100 HBM2 bandwidth: 900 GB/с.  
Разница: **в 9–18 раз** — именно поэтому 147 с/чанк вместо ожидаемых 1–2 с.

### 9.6а APITimeoutError и механизм ретраев

В процессе прогона часть чанков вызывает `APITimeoutError`:
```
Retrying ragu.models.openai.CachedAsyncOpenAI._uncached_chat_completion
in 4 seconds as it raised APITimeoutError: Request timed out.
```

Паттерн: некоторые чанки (вероятно более длинные или насыщенные сущностями) превышают таймаут ragu-lm. Библиотека делает ретрай через 4 секунды и обычно успевает со второй попытки. На таких чанках итоговое время вырастает до ~173 с.

Это подтверждает CPU-природу задержек: на GPU таймаут был бы невозможен для 0.6B модели.

### 9.7 Попытка выгрузить qwen3

Отправили запрос с `keep_alive: 0` чтобы Ollama освободил VRAM под qwen3:
```bash
curl -s -X POST http://localhost:11436/api/chat \
  -d '{"model":"qwen3:32b","messages":[],"keep_alive":0}'
```

Результат: скорость улучшилась с **~400 с → ~147 с**, но всё равно CPU. Вероятная причина: Ollama не переместил ragu-lm на GPU немедленно — модель оставалась в RAM. Или при NUM_PARALLEL=3 KV-кэш резервировался под новые запросы до того, как ragu-lm смог занять VRAM.

Дополнительное наблюдение: `OLLAMA_NUM_PARALLEL=3` не влияет на скорость **одного** запроса — он только позволяет принимать 3 одновременных запроса без очереди. Для single-user сценария скорость ответа не меняется.

### 9.8 GPU-процессы на DGX во время теста

```
GPU 0: PID 873582 — наш Ollama (CUDA_VISIBLE_DEVICES=0,1)
GPU 1: PID 873582 — тот же процесс (NVLink, обе GPU как одна)
GPU 2–7: другие пользователи кластера (не наши)
```

На момент теста только наш Ollama использовал GPU 0 и 1. Несмотря на это ragu-lm работал на CPU — значит проблема именно в распределении памяти внутри Ollama, а не во внешней конкуренции.

### 9.9 Проблемы с командами на DGX

При вводе многострочных команд на DGX шелл интерпретировал перенос строки как конец команды и запускал следующую строку отдельно — в итоге открывался интерактивный Python-интерпретатор вместо нужной команды. Все команды на DGX нужно вводить **в одну строку**.

### 9.10 Параллельная разработка: что делалось одновременно

Пока разбирались с RAGU, параллельно было исправлено несколько других проблем:

**Ollama API v0.13.0** изменил endpoint эмбеддингов:
```
Старый:  POST /api/embeddings  body: {"prompt": "...", "model": "..."}  → response: {"embedding": [...]}
Новый:   POST /api/embed       body: {"input": "...", "model": "..."}   → response: {"embeddings": [[...]]}
```
После обновления Ollama на DGX эмбеддинги перестали работать. Исправлено в `embeddings/remote.py`.

**tmux-сессия** старого сервера блокировала порт 8080 — системный сервис не мог запуститься. Исправлено:
```bash
tmux kill-session -t api && sudo systemctl restart news-api
```

**SSE-стриминг** (`/query/stream`) реализован и протестирован через curl с подтверждением токен-за-токеном. Фильтрация `<think>...</think>` блоков qwen3:32b работает на фронтенде.

---

## 10. План подключения выделенного GPU

### Шаг 1: Проверить доступность GPU на DGX
```bash
nvidia-smi
# Смотреть GPU 2–7: Memory-Usage близко к 0 и нет процессов → GPU свободен
```

### Шаг 2: Запустить второй Ollama только для ragu-lm
```bash
# На DGX (GPU 2)
CUDA_VISIBLE_DEVICES=2 OLLAMA_MODELS=/raid/seva/ollama_models OLLAMA_HOST=127.0.0.1:11437 nohup ollama serve > /raid/seva/ollama_ragu.log 2>&1 &

# Убедиться что модель загружается
OLLAMA_HOST=127.0.0.1:11437 ollama list
```

### Шаг 3: Пробросить тоннель с сервера 1
```bash
ssh -R 11437:localhost:11437 <dgx_host>
```

### Шаг 4: Добавить RAGU_LM_URL в build_graph.py
```python
RAGU_LM_URL = os.getenv("RAGU_LM_URL", OLLAMA_URL)

# в _init():
ragu_lm = LLMOpenAI(
    client=CachedAsyncOpenAI(
        base_url=f"{RAGU_LM_URL}/v1",
        api_key="ollama",
        rate_max_simultaneous=15,
        cache="./llm_cache",
    ),
    model_name=RAGU_LM_MODEL,
)
```

### Шаг 5: Замерить реальную скорость перед полным прогоном
```bash
# Тест на 20 статьях, замерить время
RAGU_LM_URL=http://localhost:11437 GRAPH_WORKING_DIR=/tmp/ragu_test python scripts/test_graph.py
```

Ожидаемый результат: ~1–2 с/чанк. Если так — запускать полный прогон (~3 дня при rate=15).

---

## 11. Альтернативы если выделенный GPU недоступен

### Вариант A: vLLM вместо Ollama для ragu-lm
vLLM поддерживает continuous batching и OpenAI-совместимый API. При высоком параллелизме даёт x5–10 throughput против Ollama.

```bash
# На выделенном GPU с vLLM
CUDA_VISIBLE_DEVICES=2 python -m vllm.entrypoints.openai.api_server \
    --model RaguTeam/RAGU-lm \
    --port 11437 \
    --max-num-seqs 32
```

В `build_graph.py` API-совместим — менять почти ничего не надо.

### Вариант B: GliNER + граф co-occurrence
- GliNER уже установлен в проекте (`embeddings/embed_and_index.py`)
- Скорость: ~0.05–0.1 с/чанк (CPU)
- Даёт только NER, без типизированных отношений
- Граф: если две сущности в одном чанке → ребро (взвешенное по числу совместных появлений)
- Нужно написать собственный `local_search`/`global_search` поверх такого графа
- **Оценочное время:** ~24–47 часов против ~3 дней на GPU

### Вариант C: Ограничить граф по времени
- Строить граф только по статьям за последние 30–90 дней (~10 000–30 000 статей)
- Начальный прогон: ~12 часов на выделенном GPU (rate=15)
- Инкрементальный апдейт через `daily.sh`: только новые статьи → несколько часов в день

---

## 12. Открытые исследовательские вопросы

1. **Качество ragu-lm на финансовых новостях.** Модель обучена на общерусском тексте — насколько точно она выделяет специфические сущности: тикеры, ставки, регуляторные акты? Нужен ручной разбор 50–100 чанков.

2. **Оптимальный chunk_size для extraction.** Сейчас 800 токенов. Чанк меньше → больше API-вызовов, но каждый проще для модели. Чанк больше → модель может пропускать сущности в конце. Стоит сравнить 400/800/1200.

3. **Структура графа.** Сколько уникальных сущностей получится из 727к статей? Сколько сообществ? Насколько хорошо Leiden разделит «банки», «нефть», «IT», «политику»?

4. **Инкрементальные обновления.** graph-ragu поддерживает `build_from_docs` повторно — дубли пропускаются. Но как меняется структура сообществ при добавлении новых статей? Leiden пересчитывается полностью или инкрементально?

5. **Latency global_search.** Global search читает суммари всех сообществ и делает map-reduce через qwen3:32b. Сколько это займёт для нашего графа? Приемлемо ли для интерактивного режима?

6. **vLLM для stage 1.** Стоит ли переходить с Ollama на vLLM для ragu-lm? При rate=15 Ollama суммарный throughput ~7 500 токенов/с. vLLM с continuous batching может дать ~40 000 токенов/с → прогон за 12 часов вместо 3 дней.

---

## 13. Источники

- Edge et al. (2024). *From Local to Global: A Graph RAG Approach to Query-Focused Summarization.* [arxiv.org/abs/2404.16130](https://arxiv.org/pdf/2404.16130)
- *RAG vs. GraphRAG: A Systematic Evaluation and Key Insights* (2025). [arxiv.org/abs/2502.11371](https://arxiv.org/abs/2502.11371)
- *When to use Graphs in RAG: A Comprehensive Analysis* (2025). [arxiv.org/abs/2506.05690](https://arxiv.org/pdf/2506.05690)
- *LEGO-GraphRAG: Modularizing Graph-based RAG for Design Space Exploration* (2024). [arxiv.org/abs/2411.05844](https://arxiv.org/pdf/2411.05844)
- *Graph-Augmented Retrieval for Cross-Entity Financial Sentiment Analysis* (2025). [arxiv.org/abs/2606.00062](https://arxiv.org/pdf/2606.00062)
- RaguTeam/RAGU-lm на HuggingFace. [huggingface.co/RaguTeam/RAGU-lm](https://huggingface.co/RaguTeam/RAGU-lm)
- Ollama vs vLLM throughput benchmark. [markaicode.com](https://markaicode.com/benchmarks/ollama-vs-vllm-performance/)
- Ollama LLM Benchmark on NVIDIA V100. [databasemart.com](https://www.databasemart.com/blog/ollama-gpu-benchmark-v100)
- Global Community Summary Retriever — GraphRAG docs. [graphrag.com](https://graphrag.com/reference/graphrag/global-community-summary-retriever/)