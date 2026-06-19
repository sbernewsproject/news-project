#!/bin/bash
set -e

DUMP_FILE="/dumps/latest.sql"

if [ -f "$DUMP_FILE" ]; then
  echo ">>> restore from $DUMP_FILE..."
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$DUMP_FILE"
else
  echo ">>> start with init"
fi