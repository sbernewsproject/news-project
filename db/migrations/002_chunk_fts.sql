-- FTS-индекс для полнотекстового поиска по чанкам (русский словарь).
-- ВНИМАНИЕ: на 1.7М строк построение GIN-индекса занимает несколько минут
-- и блокирует таблицу — запускать в окно низкой нагрузки или использовать
-- CREATE INDEX CONCURRENTLY (тогда убрать IF NOT EXISTS).

ALTER TABLE chunk
    ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('russian', coalesce(chunk_text, ''))) STORED;

CREATE INDEX IF NOT EXISTS idx_chunk_tsv ON chunk USING GIN (tsv);