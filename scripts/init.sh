#!/bin/bash
# Запускается автоматически при ПЕРВОЙ инициализации Postgres (пустой volume).
# Восстанавливает дамп и накатывает миграции. На последующих стартах не вызывается —
# данные лежат в persistent volume pgdata (см. docker-compose.yml).
set -e

DUMP_FILE="/dumps/latest.sql"

if [ -f "$DUMP_FILE" ]; then
  echo ">>> restore from $DUMP_FILE..."
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$DUMP_FILE"
else
  echo ">>> dump not found — start with empty schema"
fi

echo ">>> apply migrations (FTS)..."
for m in /migrations/*.sql; do
  [ -f "$m" ] && echo ">>>   $m" && psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$m"
done
