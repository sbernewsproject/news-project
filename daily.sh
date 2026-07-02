#!/bin/bash
# Ежедневный запуск: собирает новые статьи и заносит в БД.
# Запуск: bash daily.sh
# Cron (каждый день в 6:00): 0 6 * * * cd /путь/к/проекту && bash daily.sh >> logs/daily.log 2>&1

set -e
cd "$(dirname "$0")"

VENV=".venv/bin/python3"
PARSER="$VENV parser/parser/main.py"
INSERT="$VENV db/insertnews.py"

echo "=============================="
echo "daily.sh — $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================="

# --- Lenta.ru ---
echo ""
echo ">>> Lenta.ru: sitemap..."
$PARSER parser/lenta.ru sitemap

echo ">>> Lenta.ru: parse..."
$PARSER parser/lenta.ru parse

echo ">>> Lenta.ru: insertnews..."
$INSERT parser/lenta.ru/parsed_articles.json

# --- Комсомольская Правда ---
echo ""
echo ">>> Комсомольская Правда: sitemap..."
$PARSER parser/komsomolskaya_pravda sitemap

echo ">>> Комсомольская Правда: parse..."
$PARSER parser/komsomolskaya_pravda parse

echo ">>> Комсомольская Правда: insertnews..."
$INSERT parser/komsomolskaya_pravda/parsed_articles.json

echo ""
echo ">>> Индексация новых статей в Qdrant..."
QDRANT_URL=http://localhost:6333 \
QDRANT_API_KEY=password \
POSTGRES_DSN=postgresql://user:password@localhost:5432/mydb \
BGE_MODEL_PATH=$HOME/models/bge-m3 \
PYTHONPATH=. \
$VENV scripts/run_indexing.py

echo ""
echo ">>> Инкрементальное обновление графа знаний (статьи за последние 2 дня)..."
OLLAMA_URL=${OLLAMA_URL:-http://localhost:11436} \
POSTGRES_DSN=postgresql://user:password@localhost:5432/mydb \
GRAPH_WORKING_DIR=${GRAPH_WORKING_DIR:-./ragu_working_dir} \
GRAPH_DAYS=2 \
PYTHONPATH=. \
$VENV -m graph.build_graph

echo ""
echo "=============================="
echo "Готово: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================="
