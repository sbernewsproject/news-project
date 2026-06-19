# Lenta.ru

## Запуск

**Собрать ссылки (тест — 2 sitemap'а):**
```bash
python3 parser/main.py lenta.ru sitemap --limit 2
```

**Собрать ссылки (все):**
```bash
python3 parser/main.py lenta.ru sitemap
```

**Спарсить статьи (тест — 5 штук):**
```bash
python3 parser/main.py lenta.ru parse --limit 5
```

**Спарсить статьи (тест, повторно те же):**
```bash
python3 parser/main.py lenta.ru parse --limit 5 --fresh
```

**Спарсить статьи (все):**
```bash
python3 parser/main.py lenta.ru parse
```

**Оба шага подряд (все):**
```bash
python3 parser/main.py lenta.ru all
```
