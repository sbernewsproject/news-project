-- FTS-индекс для полнотекстового поиска по статьям (русский словарь).
-- ВНИМАНИЕ: на 1.45М строк построение generated-колонки и GIN-индекса
-- занимает время и место на диске — запускать в окно низкой нагрузки.

-- Полнотекстовый вектор по заголовку и тексту статьи.
ALTER TABLE article
    ADD COLUMN IF NOT EXISTS tsv tsvector
    GENERATED ALWAYS AS (
        to_tsvector('russian',
            coalesce(title, '') || ' ' || coalesce(arttext, ''))
    ) STORED;

-- GIN-индекс для быстрого @@ websearch_to_tsquery.
CREATE INDEX IF NOT EXISTS idx_article_tsv ON article USING GIN (tsv);
