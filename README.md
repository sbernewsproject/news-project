<img width="700" height="743" alt="IMG_0064" src="https://github.com/user-attachments/assets/1bf8df90-3e74-4c80-96bb-c80f61cde8e2" />

<img width="700" height="561" alt="IMG_0063" src="https://github.com/user-attachments/assets/3ee94941-5e04-4d94-811e-9e9a7604537d" />

# news-project

Агрегатор новостей и банковских отзывов с RAG-ассистентом. Статьи парсятся из
нескольких источников, складываются в PostgreSQL, индексируются в векторную БД
(Qdrant) и доступны через REST API и веб-интерфейс. ИИ-ассистент отвечает на
вопросы по базе знаний (RAG) на локальных моделях.

---

## Архитектура

Проект рассчитан на **два хоста**:

- **VPS** (без GPU) — данные и лёгкий API: `Postgres + Qdrant + FastAPI`.
- **GPU-хост** — все модели: `Ollama (qwen + bge-m3) + RAG-сервис (bge-m3, reranker)`.

```
                    БРАУЗЕР
                       │
                       │  http://VPS:8000
                       ▼
┌─────────────────────────────────────────┐         ┌──────────────────────────────┐
│  VPS  (docker-compose.yml)               │         │  GPU-ХОСТ (docker-compose.gpu.yml)
│                                          │         │                              │
│  api:8000  (Dockerfile.api, slim)        │         │  rag:8001 (Dockerfile.rag)   │
│   ├─ /                сайт (frontend)     │         │   └─ модели BGE-M3 + reranker│
│   ├─ /api/articles    лента из Postgres   │  /query │      + RAGChain              │
│   ├─ /api/...         темы/типы/деталь    │ ──────▶ │                              │
│   └─ /query           проксирует на RAG ──┼─────────┘   Ollama (на хосте):         │
│                                          │             qwen3.5  (генерация)        │
│  postgres:5432   1.45М статей             │ ◀───────────  bge-m3   (эмбеддинги)     │
│  qdrant:6333     векторные чанки          │ ◀───────── (RAG/поиск читают БД по сети)│
└─────────────────────────────────────────┘         └──────────────────────────────┘
```

**Почему так:** модели тяжёлые и требуют GPU, поэтому крутятся отдельно. VPS-образ
(`Dockerfile.api`) не тянет `torch`/`sentence-transformers` — он лишь раздаёт ленту
из Postgres, делает гибридный поиск (эмбеддинг запроса берёт у Ollama по HTTP) и
**проксирует** `/query` на RAG-сервис GPU-хоста (`RAG_URL`). Если `RAG_URL` не задан,
API лениво поднимает RAG-цепочку в своём процессе (удобно для локальной разработки).

### Потоки данных

- **Лента** (`/api/articles`, `/api/themes`, …): браузер → `api`(VPS) → Postgres.
- **Гибридный поиск** (`/api/articles?q=`): `api`(VPS) → Postgres FTS **+** Qdrant
  (вектор запроса считает Ollama на GPU-хосте) → слияние RRF. Если Ollama/Qdrant
  недоступны — деградирует на чистый полнотекстовый поиск.
- **RAG-чат** (`/query`): браузер → `api`(VPS) → проксирование → `rag`(GPU) →
  Qdrant+Postgres (на VPS) + генерация Ollama → ответ.

---

## Запуск через Docker

### 1. Предпосылки

- Docker и Docker Compose v2 на обоих хостах.
- На GPU-хосте: драйверы NVIDIA + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
  и запущенный **Ollama** с моделями:
  ```bash
  ollama pull qwen3.5:32b   # генерация
  ollama pull bge-m3        # эмбеддинги для поиска
  ```
- Дамп БД `dumps/latest.sql` (восстанавливается автоматически при первом старте).

### 2. VPS — данные + API

`docker-compose.yml` поднимает `postgres`, `qdrant` и `api`.

```bash
# в корне проекта на VPS
bash backup.sh start
```

Что происходит на **первом** старте:
1. Поднимаются Postgres, Qdrant, собирается и стартует образ `api`.
2. Postgres при первой инициализации (пустой volume `pgdata`) запускает
   `scripts/init.sh`: восстанавливает `dumps/latest.sql` и накатывает миграции из
   `db/migrations/*.sql` (полнотекстовый FTS-индекс).
3. Данные сохраняются в volume `pgdata` — повторный `start` **не** переимпортирует
   дамп (это долго: дамп ~1.8 ГБ).

Логи восстановления:
```bash
docker compose logs -f postgres
```

Готово — сайт и API на **http://VPS_IP:8000**.

> Чтобы принудительно перезалить свежий дамп:
> ```bash
> docker compose down -v && bash backup.sh start
> ```

#### Кто что запускает (важно не путать)

`backup.sh` и `scripts/init.sh` — **два разных скрипта с противоположными ролями**:

```
ТЫ вручную
   │
   ▼
bash backup.sh start          ← скрипт-обёртка, запускаешь ТЫ
   │
   ▼
docker compose up -d --build  ← это всё, что делает backup.sh start
   │
   ▼
поднимаются postgres / qdrant / api
   │
   └─ контейнер postgres на ПЕРВОМ старте САМ запускает
      scripts/init.sh  (рестор дампа + миграции)
```

- **`backup.sh` запускаешь ты.** Docker его не вызывает. Это удобная обёртка:
  `start` = `docker compose up -d --build`, `stop` = снять дампы Postgres/Qdrant в
  `./dumps/` и `docker compose down`. Это рекомендованная точка входа.
- **`scripts/init.sh` запускает сам Docker** — внутри контейнера `postgres`,
  автоматически, только при первой инициализации (пустой volume `pgdata`). Руками его
  вызывать не нужно.

Можно поднимать и напрямую через `docker compose up -d` — результат тот же. Но
`backup.sh` удобнее: даёт парный `stop` со снятием дампов и пересобирает образ `api`
(`--build`). Обратной петли «Docker вызывает backup.sh» **нет**.

### 3. GPU-хост — модели + RAG

`docker-compose.gpu.yml` поднимает сервис `rag` (образ `Dockerfile.rag` с CUDA-сборкой
`torch`). Перед запуском укажи в `.env` адреса VPS (Postgres/Qdrant) и локального Ollama.

```bash
# на GPU-хосте
docker compose -f docker-compose.gpu.yml up -d --build
```

RAG-сервис слушает **:8001** и читает Postgres/Qdrant с VPS по сети. Модели
кэшируются в volume `hf-cache`, чтобы не качать при каждом старте.

> Тег базового образа в `Dockerfile.rag` (`pytorch/pytorch:2.4.1-cuda12.1-...`) при
> необходимости подгони под версию CUDA на хосте.

### 4. Связать VPS и GPU-хост

На VPS пропиши адрес RAG-сервиса и Ollama (в `.env` рядом с `docker-compose.yml`):

```dotenv
RAG_URL=http://GPU_HOST_IP:8001
OLLAMA_URL=http://GPU_HOST_IP:11434
OLLAMA_EMBED_MODEL=bge-m3
```

После этого `/query` с VPS пойдёт на GPU-хост, а гибридный поиск будет брать
эмбеддинги у Ollama.

### Где «сайт»?

Отдельный контейнер для фронтенда **не нужен**. Фронт — это статический
`frontend/index.html`, который раздаёт сам контейнер `api` (FastAPI отдаёт `/` и
`/static`). То есть сайт уже «в Докере» — внутри образа `api`. Открывается на
`http://VPS_IP:8000`. Если позже понадобится отдельный nginx/CDN — можно добавить,
но для текущей задачи это лишнее.

---

## Переменные окружения

Берутся из `.env` (см. `.env.example`). В Docker подставляются через `environment:`
в compose-файлах.

| Переменная | Где нужна | Назначение |
|---|---|---|
| `POSTGRES_DSN` | api, rag | DSN PostgreSQL. Внутри VPS-сети: `postgresql://user:password@postgres:5432/mydb`. С GPU-хоста: адрес VPS. |
| `QDRANT_URL` | api, rag | URL Qdrant. Внутри VPS-сети: `http://qdrant:6333`. С GPU-хоста: адрес VPS. |
| `QDRANT_API_KEY` | api, rag | API-ключ Qdrant (`password` по умолчанию). |
| `RAG_URL` | api (VPS) | Адрес RAG-сервиса GPU-хоста. Если задан — `/query` проксируется туда. Пусто → локальный RAG. |
| `OLLAMA_URL` | api, rag | URL Ollama (генерация + эмбеддинги). На GPU-хосте обычно `http://host.docker.internal:11434`. |
| `OLLAMA_MODEL` | rag | LLM для генерации (`qwen3.5:32b`). |
| `OLLAMA_EMBED_MODEL` | api | Эмбеддинг-модель для семантической части поиска (`bge-m3`). |
| `GRAPH_WORKING_DIR` | rag | Рабочая директория графа знаний (RAGU). |
| `BGE_MODEL_PATH`, `RERANKER_MODEL_PATH` | rag | Локальные пути к моделям, если скачаны вручную. |

---

## REST API

Базовый URL: `http://VPS_IP:8000`. Интерактивная схема: `/docs`.

| Метод | Путь | Назначение |
|---|---|---|
| `GET` | `/` | Веб-интерфейс (лента + чат). |
| `GET` | `/api/articles` | Лента. Параметры: `limit` (≤100), `cursor` (article_id, keyset-пагинация), `theme` (id, можно несколько), `type` (id), `q` (строка → гибридный поиск). Ответ: `{items, next_cursor}`. |
| `GET` | `/api/articles/{id}` | Полная статья (заголовок, текст, источник, темы, оценка). |
| `GET` | `/api/themes` | Темы (разделы) для фильтра, с числом статей. |
| `GET` | `/api/types` | Типы (`Новость` / `Отзыв`). |
| `POST` | `/query` | RAG-ответ ассистента. Тело: `{query, top_k}`. Проксируется на GPU-хост. |
| `POST` | `/index/article` | Добавить статью в граф знаний (нужны RAG-зависимости). |
| `GET` | `/health` | Проверка живости. |

Быстрая проверка:
```bash
curl http://VPS_IP:8000/api/themes
curl "http://VPS_IP:8000/api/articles?limit=5"
curl "http://VPS_IP:8000/api/articles?q=кредит&limit=5"
```

---

## Парсинг и загрузка в БД

### Первый запуск (полный архив)

```bash
# Поднять только БД
docker compose up -d postgres

# Парсить + занести в БД (по каждому источнику)
python3 parser/parser/main.py parser/lenta.ru all
python3 db/insertnews.py parser/lenta.ru/parsed_articles.json

python3 parser/parser/main.py parser/komsomolskaya_pravda all
python3 db/insertnews.py parser/komsomolskaya_pravda/parsed_articles.json

python3 parser/parser/main.py parser/sravni.ru all
python3 db/insertnews.py parser/sravni.ru/parsed_articles.json

python3 parser/parser/main.py parser/banki.ru sitemap
python3 db/insertnews.py parser/banki.ru/parsed_articles.json
```

### Ежедневное обновление (новые статьи)

Скрипт `daily.sh` подхватывает только новые статьи (lenta.ru и КП), пропуская уже
обработанные.

```bash
bash daily.sh
```

**Cron** — каждый день в 6:00:
```
0 6 * * * cd /Users/ukqueen/Projects/Python/news-project && bash daily.sh >> logs/daily.log 2>&1
```
```bash
crontab -e
```

> sravni.ru и banki.ru запускаются вручную — парсинг занимает несколько часов.

### Индексация в Qdrant (для семантического поиска и RAG)

Лента и FTS-поиск работают сразу после загрузки в Postgres. Семантическая часть
поиска и RAG требуют разбиения статей на чанки и индексации в Qdrant:

```bash
python3 scripts/run_indexing.py   # чанкинг + вставка в таблицу chunk
python3 scripts/index_chunks.py   # эмбеддинги чанков → Qdrant
```

---

## Бэкап и восстановление

```bash
bash backup.sh stop    # pg_dump → dumps/latest.sql, копия Qdrant → dumps/qdrant/, затем down
bash backup.sh start   # поднять стек (на первом старте — авто-восстановление дампа)
```

Данные Postgres хранятся в volume `pgdata`, Qdrant — в `qdrantdata`. `docker compose
down` их не удаляет; `down -v` — удаляет (нужно для полного перезалива).

---

## Локальная разработка (без разделения на хосты)

Можно поднять всё на одной машине. Если не задавать `RAG_URL`, API сам поднимет
RAG-цепочку в своём процессе (понадобится полный `requirements.txt` и модели):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt           # полный набор (с torch)
docker compose up -d postgres qdrant       # только инфраструктура
uvicorn api.main:app --reload              # API + сайт на http://localhost:8000
```

Для лёгкого API без моделей (только лента/поиск): `pip install -r requirements-api.txt`.

---

## Структура репозитория

| Путь | Назначение |
|---|---|
| `api/` | FastAPI: лента, поиск, темы/типы (`articles.py`, `search.py`, `db.py`, `schemas.py`, `main.py`). |
| `rag/` | RAG-цепочка (`chain.py`) и RAG-сервис для GPU-хоста (`server.py`). |
| `embeddings/` | Эмбеддинги/индексация. `remote.py` — клиент Ollama для VPS (без torch). |
| `graph/` | Граф знаний (RAGU): построение и поиск. |
| `db/` | Схема (`bdpsql.sql`), загрузка (`insertnews.py`), миграции (`migrations/`). |
| `frontend/` | Веб-интерфейс (один `index.html`), раздаётся контейнером `api`. |
| `parser/` | Парсеры источников (общий код — **не менять без необходимости**). |
| `scripts/` | `init.sh` (восстановление при первом старте), индексация. |
| `Dockerfile.api` / `Dockerfile.rag` | Лёгкий VPS-образ / тяжёлый GPU-образ. |
| `docker-compose.yml` / `docker-compose.gpu.yml` | Стек VPS / стек GPU-хоста. |
| `backup.sh` / `daily.sh` | Управление стеком / ежедневный парсинг. |

---

## Траблшутинг

- **Лента пустая / `Ничего не найдено`** — проверь, что Postgres восстановил дамп
  (`docker compose logs postgres`) и API стартовал (`docker compose logs api`).
- **Поиск находит только по словам, не по смыслу** — не проиндексированы чанки в
  Qdrant (см. «Индексация в Qdrant») либо недоступен Ollama (`OLLAMA_URL`). Поиск в
  этом случае работает в режиме FTS.
- **`/query` отвечает 502** — недоступен RAG-сервис на GPU-хосте; проверь `RAG_URL` и
  `docker compose -f docker-compose.gpu.yml logs rag`.
- **RAG-контейнер не видит GPU** — установлен ли NVIDIA Container Toolkit; совпадает
  ли тег CUDA в `Dockerfile.rag` с хостом.

---

## 📋 Task Board

| Статус | Задача | Приоритет | Исполнитель |
| :---: | :--- | :---: | :---: |
| 📅  | Загрузить несколько одинаковых статей с разных источников и посмотреть как с этимм бороться | 🟢 | кто-то |
| 🚧  | Сделать ER диаграмму | 🟢 | Ольга Системный аналитик |
| 😳  | Нужно обсудить какие сущности будет выделять GliNER помимо основных PER/ORG/LOC | 🟡 | Кирилл БД Сева |
| 😶‍🌫️  | Необходимо выбрать какие метаданные передаем в payload | 🟡 | Кирилл БД Сева |

> **Легенда:** ✅ Готово | 🚧 В работе | 📅 Запланировано
> 🔴 Высокий приоритет | 🟡 Средний | 🟢 Низкий
