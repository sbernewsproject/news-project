"""
from __future__ import annotations
import re
from gliner import GLiNER

MODEL_NAME = "urchade/gliner_multi-v2.1"
LABELS = ["person", "organization", "location", "event"]
LABEL_MAP = {"person": "PER", "organization": "ORG", "location": "LOC", "event": "EVENT"}

# множители для нормализации сумм
_MULTIPLIERS = {"тыс": 1_000, "млн": 1_000_000, "млрд": 1_000_000_000, "трлн": 1_000_000_000_000}
_CURRENCY_MAP = {"₽": "RUB", "руб": "RUB", "рублей": "RUB", "рубл": "RUB", "$": "USD", "€": "EUR"}

_MONEY_RE = re.compile(
    r"([$€₽]?)\s*([\d\s]+(?:[.,]\d+)?)\s*(тыс|млн|млрд|трлн)?\s*"
    r"([$€₽]|руб(?:лей|ля|ль)?|долларов?|евро)?",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b"          # 01.01.2025
    r"|\b(\d{4})-(\d{2})-(\d{2})\b"                    # 2025-01-01
    r"|\bQ([1-4])\s+(\d{4})\b"                         # Q1 2025
    r"|\b(\d{4})\s+год[уа]?\b",                        # 2025 году
    re.IGNORECASE,
)

_QUARTER_MONTHS = {"1": ("01", "03"), "2": ("04", "06"), "3": ("07", "09"), "4": ("10", "12")}


def _parse_money(m: re.Match) -> dict | None:
    prefix_cur, digits, mult, suffix_cur = m.group(1), m.group(2), m.group(3), m.group(4)
    digits = digits.replace(" ", "").replace(",", ".")
    try:
        amount = float(digits)
    except ValueError:
        return None
    if mult:
        amount *= _MULTIPLIERS[mult.lower()]
    raw_cur = (prefix_cur or suffix_cur or "").strip().lower()
    currency = next((v for k, v in _CURRENCY_MAP.items() if raw_cur.startswith(k)), None)
    if not currency and not mult:
        return None  # скорее всего просто число, не деньги
    return {"amount": amount, "currency": currency or "UNKNOWN", "label": "MONEY"}


def _parse_date(m: re.Match) -> dict | None:
    if m.group(1):  # dd.mm.yyyy
        return {"date": f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}", "label": "DATE"}
    if m.group(4):  # yyyy-mm-dd
        return {"date": f"{m.group(4)}-{m.group(5)}-{m.group(6)}", "label": "DATE"}
    if m.group(7):  # Q1 2025
        q, year = m.group(7), m.group(8)
        start, end = _QUARTER_MONTHS[q]
        return {"date_range": [f"{year}-{start}-01", f"{year}-{end}-30"], "label": "DATE"}
    if m.group(9):  # 2025 году
        return {"date": f"{m.group(9)}-01-01", "label": "DATE"}
    return None


def extract_money(text: str) -> list[dict]:
    results = []
    for m in _MONEY_RE.finditer(text):
        parsed = _parse_money(m)
        if parsed:
            results.append(parsed)
    return results


def extract_dates(text: str) -> list[dict]:
    results = []
    for m in _DATE_RE.finditer(text):
        parsed = _parse_date(m)
        if parsed:
            results.append(parsed)
    return results


class EntityExtractor:
    def __init__(self):
        self.model = GLiNER.from_pretrained(MODEL_NAME)

    def extract(self, text: str) -> dict:
        ner = self.model.predict_entities(text, LABELS, threshold=0.5)
        return {
            "ner": [{"text": e["text"], "label": LABEL_MAP[e["label"]]} for e in ner],
            "money": extract_money(text),
            "dates": extract_dates(text),
        }
"""