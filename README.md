# news-rag

## О проекте

Представьте, что у вас есть личный аналитик, который каждый день читает тысячи новостей и отзывов о банках — и в любой момент готов ответить на ваш вопрос. Именно это делает news-rag.

Система автоматически собирает статьи из крупных российских источников: **Lenta.ru**, **Комсомольская правда**, а также отзывы с финансовых порталов **Banki.ru** и **Sravni.ru**. На сегодня в базе более **1,5 миллиона материалов** — новости, аналитика и живые отзывы реальных клиентов банков за несколько лет. Каждый день база пополняется новыми материалами автоматически.

### Как это работает для пользователя

Вы открываете сайт и видите ленту последних новостей. Её можно фильтровать по темам — ипотека, вклады, страхование, кредиты, отзывы клиентов — и просматривать как обычный новостной портал. Можно искать по ключевым словам.

Но главное — это чат с ИИ-ассистентом, встроенный в тот же интерфейс. Вы задаёте вопрос в свободной форме:

- «Что клиенты думают о качестве обслуживания в Тинькофф?»
- «Какие банки повысили ставки по вкладам в этом году?»
- «Расскажи о последних изменениях в программе семейной ипотеки»

Система не просто ищет по словам. Она **понимает смысл вопроса**: находит десятки наиболее подходящих фрагментов из базы, отбирает самые точные из них, а затем формулирует связный ответ — со ссылками на конкретные статьи, которые стали источниками. Ответ появляется слово за словом, как в ChatGPT, прямо в браузере.

Ассистент работает строго по содержимому базы и не придумывает факты. Если информации в базе недостаточно — честно об этом сообщит.

### Для кого это полезно

Проект ориентирован на финансовую аналитику: мониторинг репутации банков, отслеживание изменений в банковских продуктах, анализ клиентских настроений. Журналист, аналитик или продуктовый менеджер могут за секунды получить сводку по любой теме вместо того, чтобы вручную просматривать сотни страниц.

### Почему без внешних ИИ-сервисов

Все языковые модели — генерация ответов, понимание смысла запроса, ранжирование результатов — работают локально на собственном GPU-сервере. Ни вопросы пользователей, ни содержимое базы не передаются в OpenAI, Яндекс или любые другие сторонние сервисы. Для работы с банковской и финансовой тематикой это принципиально важно.

Конкретно используются: **qwen3:30b-a3b** для генерации ответов, **BGE-M3** для понимания смысла запроса и **bge-reranker-v2-m3** для точного отбора нужных фрагментов из базы. Все три модели — современные открытые решения, не уступающие коммерческим аналогам на задачах работы с русскоязычным текстом.

---

## Архитектура

Проект рассчитан на **два хоста**:

- **VPS** — данные и лёгкий API: `Postgres + Qdrant + FastAPI (api:8000)`.
- **GPU-хост** — все модели: `Ollama + RAG-сервис (rag:8001)`.

```
                  БРАУЗЕР
                     │ http://VPS:8000
                     ▼
┌────────────────────────────────┐       ┌──────────────────────────────┐
│  VPS (docker-compose.yml)      │       │  GPU-хост (systemd)          │
│                                │       │                              │
│  api:8000  (FastAPI)           │       │  rag:8001  (uvicorn)         │
│   ├─ /          веб-интерфейс  │─────▶ │   ├─ гибридный поиск         │
│   ├─ /api/...   лента + фильтры│ /query│   │   Dense (Qdrant/BGE-M3)  │
│   └─ /query     прокси → rag   │       │   │   FTS  (Postgres)        │
│                                │       │   │   RRF слияние            │
│  postgres:5432  ~1.5М статей   │◀──────│   │   Reranker               │
│  qdrant:6333    векторные чанки│◀──────│   └─ генерация → Ollama      │
└────────────────────────────────┘       │                              │
                                         │  ollama:11434/11436          │
                                         │   qwen3:30b-a3b  (LLM)       │
                                         │   bge-m3         (эмбед)     │
                                         └──────────────────────────────┘
```

### RAG-пайплайн

1. **Роутинг** — тип запроса (local / global / dense).
2. **Гибридный поиск** — dense (Qdrant) + FTS (Postgres tsvector); результаты сливаются через RRF.
3. **Reranker** (`bge-reranker-v2-m3`) — TOP\_K=15 → TOP\_N=5 лучших чанков.
4. **Генерация** — `qwen3:30b-a3b` через Ollama с потоковой передачей (SSE).
5. **Ответ** — токены + ссылки на источники [N] в интерфейсе.

---

## Быстрый старт

### VPS — данные + API

```bash
# Скопировать .env.example в .env и заполнить адреса GPU-хоста
cp .env.example .env

# Поднять стек (Postgres, Qdrant, API)
bash backup.sh start
```

Что происходит на первом старте:
1. `docker compose up -d --build`
2. Postgres при первой инициализации запускает `scripts/init.sh`:
   восстанавливает `dumps/latest.sql.gz` (или `latest.sql`) и накатывает миграции из `db/migrations/`.
3. Данные сохраняются в volume `pgdata` — повторный `start` дамп **не** перезаливает.

```bash
docker compose logs -f postgres   # следить за восстановлением
```

Сайт и API: **http://VPS_IP:8000**

> Принудительно перезалить дамп:
> ```bash
> docker compose down -v && bash backup.sh start
> ```

### GPU-хост — модели + RAG

Необходим [Ollama](https://ollama.ai) с моделями:

```bash
ollama pull qwen3:30b-a3b   # LLM для генерации
ollama pull bge-m3           # эмбеддинги
```

RAG-сервис запускается напрямую (не Docker):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Заполнить .env (POSTGRES_DSN, QDRANT_URL, OLLAMA_URL, ...)
uvicorn rag.server:app --host 0.0.0.0 --port 8001
```

На VPS прописать в `.env`:

```dotenv
RAG_URL=http://GPU_HOST_IP:8001
OLLAMA_URL=http://GPU_HOST_IP:11434   # или через SSH-туннель
OLLAMA_EMBED_MODEL=bge-m3
```

---

## Переменные окружения

Берутся из `.env` (см. `.env.example`).

| Переменная | Где нужна | Описание |
|---|---|---|
| `POSTGRES_DSN` | api, rag | DSN PostgreSQL. На VPS внутри docker-сети: `postgresql://user:password@postgres:5432/mydb`. |
| `QDRANT_URL` | api, rag | URL Qdrant. Внутри VPS-сети: `http://qdrant:6333`. |
| `QDRANT_API_KEY` | api, rag | API-ключ Qdrant (по умолчанию `password`). |
| `RAG_URL` | api (VPS) | Адрес RAG-сервиса GPU-хоста. Если не задан — `/query` пытается поднять RAG локально. |
| `OLLAMA_URL` | api, rag | URL Ollama (генерация + эмбеддинги). |
| `OLLAMA_MODEL` | rag | LLM для генерации (по умолчанию `qwen3:30b-a3b`). |
| `OLLAMA_EMBED_MODEL` | api | Эмбеддинг-модель для семантической части поиска (`bge-m3`). |
| `BGE_MODEL_PATH` | rag | Локальный путь к BGE-M3 (если скачан вручную). |
| `RERANKER_MODEL_PATH` | rag | Локальный путь к reranker (если скачан вручную). |

---

## REST API

Базовый URL: `http://VPS_IP:8000`. Интерактивная схема: `/docs`.

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/` | Веб-интерфейс. |
| `GET` | `/api/articles` | Лента. Параметры: `limit` (≤100), `cursor` (keyset), `theme` (id, несколько), `type` (id), `q` (гибридный поиск). |
| `GET` | `/api/articles/{id}` | Полная статья. |
| `GET` | `/api/themes` | Темы для фильтра, с числом статей. |
| `GET` | `/api/types` | Типы статей (`Новость` / `Отзыв`). |
| `GET` | `/api/stats` | Статистика БД: статей всего, по типам, дата последней, чанков. |
| `POST` | `/query` | RAG-ответ (проксируется на GPU-хост). Тело: `{query, top_k}`. |
| `POST` | `/query/stream` | Потоковый RAG-ответ (SSE). |
| `GET` | `/health` | Проверка живости. |

```bash
curl http://VPS_IP:8000/api/stats
curl "http://VPS_IP:8000/api/articles?q=кредит&limit=5"
curl http://VPS_IP:8000/api/themes
```

---

## Парсинг и загрузка данных

### Первичная загрузка (полный архив)

```bash
source .venv/bin/activate

# lenta.ru
python3 parser/parser/main.py parser/lenta.ru all
python3 db/insertnews.py parser/lenta.ru/parsed_articles.json

# Комсомольская правда
python3 parser/parser/main.py parser/komsomolskaya_pravda all
python3 db/insertnews.py parser/komsomolskaya_pravda/parsed_articles.json

# sravni.ru (занимает несколько часов)
python3 parser/parser/main.py parser/sravni.ru all
python3 db/insertnews.py parser/sravni.ru/parsed_articles.json

# banki.ru (занимает несколько часов)
python3 parser/parser/main.py parser/banki.ru sitemap
python3 db/insertnews.py parser/banki.ru/parsed_articles.json
```

### Ежедневное обновление

`daily.sh` подхватывает только новые статьи из lenta.ru, КП, banki.ru и sravni.ru:

```bash
bash daily.sh
```

systemd-таймер (каждый день в 06:00):

```bash
# /etc/systemd/system/news-daily.service + news-daily.timer
systemctl enable --now news-daily.timer
```

### Индексация в Qdrant

FTS работает сразу после загрузки в Postgres. Для семантического поиска и RAG нужна индексация чанков:

```bash
python3 scripts/run_indexing.py   # чанкинг + вставка в таблицу chunk
# эмбеддинги чанков → Qdrant создаются внутри run_indexing.py
```

---

## Бэкап и восстановление

```bash
bash backup.sh backup   # дамп Postgres → dumps/latest.sql.gz (без остановки)
bash backup.sh stop     # дамп + остановить стек
bash backup.sh start    # поднять стек (первый старт — авто-восстановление дампа)
```

Хранятся последние 7 дампов (`dumps/postgres_YYYYMMDD_HHMMSS.sql.gz`).
Qdrant не бэкапится — 7 ГБ векторов, восстанавливаются повторной индексацией.

systemd-таймер бэкапа (каждый день в 03:00):

```bash
systemctl enable --now news-backup.timer
```

---

## Структура репозитория

```
api/              FastAPI: лента, поиск, темы/типы/статистика
rag/              RAG-цепочка (chain.py) и GPU-сервис (server.py)
embeddings/       Индексация чанков + Ollama-клиент для эмбеддингов
db/               SQL-схема (bdpsql.sql), загрузка (insertnews.py), миграции
frontend/         Веб-интерфейс (один index.html), раздаётся api-контейнером
parser/           Парсеры: lenta.ru, komsomolskaya_pravda, sravni.ru, banki.ru
scripts/          init.sh (авто-восстановление при старте), run_indexing.py
docker-compose.yml  VPS-стек: postgres + qdrant + api
backup.sh         Управление стеком и дампами
daily.sh          Ежедневный парсинг
.env.example      Шаблон переменных окружения
```

---

## Траблшутинг

**Лента пустая** — проверь восстановление дампа:
```bash
docker compose logs postgres
```

**Поиск только по словам, не по смыслу** — Qdrant не проиндексирован или недоступен Ollama (`OLLAMA_URL`). Поиск автоматически деградирует на чистый FTS.

**`/query` отвечает 502** — RAG-сервис недоступен. Проверь `RAG_URL` и статус `rag.service` на GPU-хосте.

**RAG медленно отвечает при первом запросе** — BGE-M3 и reranker загружаются в память. Последующие запросы быстрые (`keep_alive=60m` для Ollama).