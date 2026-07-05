#!/bin/bash
# Управление стеком на VPS (Postgres + Qdrant + API).
#
# Qdrant НЕ бэкапится — 7 ГБ векторов, восстанавливаются повторным
# индексированием из Postgres (scripts/run_indexing.py).
#
#   bash backup.sh start    — поднять стек
#   bash backup.sh stop     — дамп postgres + остановить стек
#   bash backup.sh backup   — дамп postgres без остановки (для cron)

set -euo pipefail

DUMPS_DIR="./dumps"
KEEP=7   # хранить последних N дампов

_dump_postgres() {
  mkdir -p "$DUMPS_DIR"
  local STAMP
  STAMP=$(date +%Y%m%d_%H%M%S)
  local FILE="$DUMPS_DIR/postgres_${STAMP}.sql.gz"
  echo ">>> dump postgres → $FILE"
  docker exec postgres pg_dump -U user -d mydb -F p | gzip > "$FILE"
  ln -sf "postgres_${STAMP}.sql.gz" "$DUMPS_DIR/latest.sql.gz"
  # Удалить старые дампы
  ls -t "$DUMPS_DIR"/postgres_*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --
  echo ">>> готово"
}

case "${1:-}" in
  stop)
    _dump_postgres
    docker compose down
    ;;
  start)
    docker compose up -d --build
    echo ">>> стек поднят. На первом старте идёт восстановление дампа:"
    echo ">>>   docker compose logs -f postgres"
    ;;
  backup)
    _dump_postgres
    ;;
  *)
    echo "usage:"
    echo "  bash backup.sh start    — поднять стек"
    echo "  bash backup.sh stop     — дамп postgres и остановить стек"
    echo "  bash backup.sh backup   — дамп postgres без остановки (для cron)"
    ;;
esac