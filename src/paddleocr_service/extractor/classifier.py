from __future__ import annotations

from typing import Literal
from .date_utils import norm_text
from .mrz import find_mrz
from .country_registry import get_all_classifier_keywords, detect_country

DocumentType = Literal["national_id", "passport", "drivers_license", "residence_permit", "unknown"]

# ---------------------------------------------------------------------------
# Global (country-agnostic) fallback keyword vocabulary
# International keywords — English + French + Spanish + German + Swahili + Arabic transliterations
# Normalized (spaces removed) at startup for fast matching
# ---------------------------------------------------------------------------
_GLOBAL_KEYWORDS: dict[str, list[str]] = {
    "passport": [
        "passport", "passeport", "pasaporte", "reisepass", "pasipoti",
        "passaporto", "paszport", "паспорт",
    ],
    "national_id": [
        "national identity card", "national id card", "identity card",
        "identification card", "id card", "carte nationale", "carte d identite",
        "documento nacional", "documento de identidad", "personalausweis",
        "carta de identidade", "kitambulisho cha taifa", "national id",
        "id number", "identity number", "identification number",
    ],
    "drivers_license": [
        "driving licence", "driving license", "driver license",
        "drivers license", "permis de conduire", "licencia de conducir",
        "fuhrerschein", "carta de conducao", "leseni ya udereva",
        "vehicle class", "categories", "licence categories",
    ],
    "residence_permit": [
        "residence permit", "resident permit", "alien registration",
        "alien card", "foreigner", "refugee", "foreign national",
        "permis de sejour", "permiso de residencia", "aufenthaltstitel",
        "certificate of registration", "leave to remain",
    ],
}

_NORM_GLOBAL_KEYWORDS: dict[str, list[str]] = {
    doc_type: [norm_text(kw) for kw in kws]
    for doc_type, kws in _GLOBAL_KEYWORDS.items()
}


def _build_country_keyword_pool() -> dict[str, list[str]]:
    """
    Merge all country-specific classifier keywords from the registry into a
    flat {doc_type: [norm_kw, ...]} mapping for use when country is unknown.
    """
    pool: dict[str, list[str]] = {dt: [] for dt in _NORM_GLOBAL_KEYWORDS}
    all_kws = get_all_classifier_keywords()
    for _country, doc_map in all_kws.items():
        for doc_type, kws in doc_map.items():
            if doc_type not in pool:
                pool[doc_type] = []
            pool[doc_type].extend(kws)
    # De-duplicate
    return {dt: list(dict.fromkeys(kws)) for dt, kws in pool.items()}


_COUNTRY_KW_POOL: dict[str, list[str]] = _build_country_keyword_pool()


def classify(texts: list[str]) -> tuple[DocumentType, float]:
    """
    Classify document type from OCR lines.

    Uses three signals (in order of priority):
    1. MRZ presence — TD3 line starting with 'P<' is always a passport;
       any valid MRZ boosts the score of national_id / passport.
    2. Country-specific keywords from documents.yaml (via country_registry).
    3. Global fallback keyword vocabulary (language-agnostic).
    """
    full_norm = norm_text("".join(texts))

    # --- MRZ signal ---
    mrz = find_mrz(texts)
    mrz_boost: dict[str, int] = {}
    if mrz and mrz.valid:
        for line in texts:
            stripped = line.strip()
            if len(stripped) >= 44 and stripped[1] == "<":
                if stripped[0] == "P":
                    mrz_boost["passport"] = 3      # strong signal
                else:
                    mrz_boost["national_id"] = 2   # TD1 on ID cards
                break

    scores: dict[str, int] = {dt: 0 for dt in _NORM_GLOBAL_KEYWORDS}

    # --- Country-specific keywords (higher weight: 2 points each) ---
    country = detect_country(texts)
    if country:
        all_kws = get_all_classifier_keywords()
        country_docs = all_kws.get(country, {})
        for doc_type, norm_kws in country_docs.items():
            if doc_type not in scores:
                scores[doc_type] = 0
            for nkw in norm_kws:
                if nkw in full_norm:
                    scores[doc_type] += 2          # country match is worth double
    else:
        # No country detected — use merged pool at normal weight
        for doc_type, norm_kws in _COUNTRY_KW_POOL.items():
            if doc_type not in scores:
                scores[doc_type] = 0
            for nkw in norm_kws:
                if nkw in full_norm:
                    scores[doc_type] += 1

    # --- Global fallback keywords (1 point each) ---
    for doc_type, norm_kws in _NORM_GLOBAL_KEYWORDS.items():
        for nkw in norm_kws:
            if nkw in full_norm:
                scores[doc_type] += 1
        scores[doc_type] += mrz_boost.get(doc_type, 0)

    best_type = max(scores, key=lambda k: scores[k])
    best_score = scores[best_type]

    if best_score == 0:
        return "unknown", 0.0

    max_kws = len(_NORM_GLOBAL_KEYWORDS.get(best_type, ["_"]))
    raw_conf = best_score / max(max_kws, 1)
    # Apply a floor of 0.5 when the type was positively identified but keyword
    # coverage is sparse (e.g. doc only has 1 of 12 keywords).
    confidence = round(min(max(raw_conf, 0.5), 1.0), 2)
    return best_type, confidence  # type: ignore[return-value]
