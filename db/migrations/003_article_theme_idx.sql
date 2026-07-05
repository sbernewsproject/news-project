-- Составной индекс для быстрой фильтрации по теме с сортировкой по article_id DESC.
-- Позволяет эффективно выбирать последние статьи конкретной темы без seq scan.
CREATE INDEX IF NOT EXISTS idx_arttheme_theme_article
    ON article_theme (theme_id, article_id DESC);