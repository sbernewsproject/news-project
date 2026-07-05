#!/bin/bash
# Запускается автоматически при ПЕРВОЙ инициализации Postgres (пустой volume).
# Восстанавливает дамп и накатывает миграции. На последующих стартах не вызывается —
# данные лежат в persistent volume pgdata (см. docker-compose.yml).
set -e

if [ -f "/dumps/latest.sql.gz" ]; then
  echo ">>> restore from latest.sql.gz..."
  zcat /dumps/latest.sql.gz | psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
elif [ -f "/dumps/latest.sql" ]; then
  echo ">>> restore from latest.sql..."
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /dumps/latest.sql
else
  echo ">>> dump not found — start with empty schema"
fi

echo ">>> apply migrations..."
for m in /migrations/*.sql; do
  [ -f "$m" ] && echo ">>>   $m" && psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$m"
done