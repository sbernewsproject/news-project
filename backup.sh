#!/bin/bash
# Управление стеком на VPS (Postgres + Qdrant + API).
#
#   bash backup.sh start  — поднять стек. На ПЕРВОМ старте (пустой pgdata) Postgres
#                           сам восстановит dumps/latest.sql и накатит миграции
#                           через scripts/init.sh. Данные сохраняются в volume,
#                           поэтому повторный старт не переимпортирует дамп.
#   bash backup.sh stop   — снять дамп Postgres и Qdrant в ./dumps и остановить стек.
#
# Чтобы заставить переимпортировать свежий дамп: docker compose down -v && bash backup.sh start

if [ "$1" = "stop" ]; then
  echo ">>> dump postgres..."
  docker exec postgres pg_dump -U user -d mydb -F p -f /dumps/latest.sql
  echo ">>> dump qdrant..."
  docker cp qdrant:/qdrant/storage/. ./dumps/qdrant/
  docker compose down

elif [ "$1" = "start" ]; then
  docker compose up -d --build
  echo ">>> стек поднят. На первом старте идёт восстановление дампа — следи за логами:"
  echo ">>>   docker compose logs -f postgres"

else
  echo "help:"
  echo "  bash backup.sh start   — start (auto-restore on first boot) and build API"
  echo "  bash backup.sh stop    — dump postgres+qdrant and stop"
fi
