#!/bin/bash

if [ "$1" = "stop" ]; then
  echo ">>> dump postgres..."
  docker exec postgres pg_dump -U user -d mydb -F p -f /dumps/latest.sql
  echo ">>> dump qdrant..."
  docker cp qdrant:/qdrant/storage/. ./dumps/qdrant/
  docker compose down

elif [ "$1" = "start" ]; then
  docker compose up -d
  sleep 5
  if [ -f "./dumps/latest.sql" ]; then
    docker exec -i postgres psql -U user -d mydb < ./dumps/latest.sql
  else
    echo ">>> dump not found"
  fi

else
  echo "help:"
  echo "  bash backup.sh start   — start and restore"
  echo "  bash backup.sh stop    — dump and stop"
fi