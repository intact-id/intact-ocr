"""
country_registry.py
~~~~~~~~~~~~~~~~~~~~
Loads ``documents.yaml`` once at import time and exposes two main helpers:

  detect_country(texts)  →  ISO-3166-1 alpha-3 code or None
  get_field_labels(country, doc_type, field_name) → list[str] (normalised)
  get_classifier_keywords(country, doc_type) → list[str] (normalised)

The module is intentionally stateless after init — everything is read-only
dicts so it is safe to use from async workers without locks.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from .date_utils import norm_text
from .ocr_corrections import is_standalone_iso3, fix_nationality_code, lookup_nationality_word

logger = logging.getLogger(__name__)

_YAML_PATH = Path(__file__).with_name("documents.yaml")


# ---------------------------------------------------------------------------
# Internal data structures after loading the YAML
# ---------------------------------------------------------------------------

class _DocEntry:
    """One document-type entry within a country."""

    def __init__(self, raw: dict) -> None:
        # Normalised classifier keywords
        self.classifier_keywords: list[str] = [
            norm_text(kw) for kw in raw.get("classifier_keywords", [])
        ]
        # Raw (un-normalised) classifier keywords for fuzzy matching
        self.classifier_keywords_raw: list[str] = [
            kw.upper() for kw in raw.get("classifier_keywords", [])
        ]
        # {field_name: [normalised_label, ...]}
        raw_fields: dict[str, list[str]] = raw.get("fields", {})
        self.fields: dict[str, list[str]] = {
            field: [norm_text(lbl) for lbl in labels]
            for field, labels in raw_fields.items()
        }


class _CountryEntry:
    """One country block from the YAML."""

    def __init__(self, iso3: str, raw: dict) -> None:
        self.iso3 = iso3
        self.name: str = raw.get("name", iso3)
        self.languages: list[str] = raw.get("languages", [])
        self.documents: dict[str, _DocEntry] = {
            doc_type: _DocEntry(doc_data)
            for doc_type, doc_data in raw.get("documents", {}).items()
        }


# ---------------------------------------------------------------------------
# Load at import time
# ---------------------------------------------------------------------------

def _load_registry() -> dict[str, _CountryEntry]:
    try:
        with open(_YAML_PATH, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        countries_raw: dict = raw.get("countries", {})
        registry: dict[str, _CountryEntry] = {}
        for iso3, country_data in countries_raw.items():
            registry[iso3.upper()] = _CountryEntry(iso3.upper(), country_data)
        logger.info("country_registry: loaded %d countries from %s", len(registry), _YAML_PATH)
        return registry
    except Exception as exc:  # pragma: no cover
        logger.error("country_registry: failed to load %s — %s", _YAML_PATH, exc)
        return {}


_REGISTRY: dict[str, _CountryEntry] = _load_registry()

# MRZ nationality → ISO-3166-1 alpha-3 (they're the same for most countries;
# a small mapping for exceptions is listed here).
_MRZ_TO_ISO3: dict[str, str] = {
    "KEN": "KEN",
    "COD": "COD",
    "ZAF": "ZAF",
    "UGA": "UGA",
    "TZA": "TZA",
    "NGA": "NGA",
    "GHA": "GHA",
    "ETH": "ETH",
    "RWA": "RWA",
    "BDI": "BDI",
    "CMR": "CMR",
    "SEN": "SEN",
    "CIV": "CIV",
    "MLI": "MLI",
    "TGO": "TGO",
    "AGO": "AGO",
    "MOZ": "MOZ",
    "ZMB": "ZMB",
    "ZWE": "ZWE",
    # add more as needed
}


# ---------------------------------------------------------------------------
# Fuzzy matching helpers
# ---------------------------------------------------------------------------

def _trigrams(s: str) -> set[str]:
    """Generate character trigrams from a string."""
    s = s.upper()
    if len(s) < 3:
        return {s}
    return {s[i:i+3] for i in range(len(s) - 2)}


def _trigram_similarity(a: str, b: str) -> float:
    """Jaccard similarity on trigrams. Returns 0.0–1.0."""
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    intersection = len(ta & tb)
    union = len(ta | tb)
    return intersection / union if union else 0.0


def _fuzzy_keyword_score(full_text: str, keywords_raw: list[str], threshold: float = 0.55) -> int:
    """
    Count how many keywords fuzzy-match against the full text.
    Uses trigram similarity with the given threshold.
    """
    score = 0
    text_upper = full_text.upper()
    for kw in keywords_raw:
        # First try exact substring (fast path)
        if kw in text_upper:
            score += 1
            continue
        # Fuzzy: compare keyword trigrams against a sliding window in the text
        kw_len = len(kw)
        if kw_len < 4:
            continue  # too short for meaningful fuzzy matching
        best_sim = 0.0
        for i in range(max(1, len(text_upper) - kw_len + 1)):
            window = text_upper[i:i + kw_len + 5]  # slightly wider window
            sim = _trigram_similarity(kw, window)
            if sim > best_sim:
                best_sim = sim
        if best_sim >= threshold:
            score += 1
    return score


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_countries() -> list[str]:
    """Return all known ISO-3166-1 alpha-3 codes."""
    return list(_REGISTRY.keys())


def detect_country(texts: list[str]) -> Optional[str]:
    """
    Best-effort country detection from OCR lines.

    Strategy (in priority order):
    1. MRZ nationality field — most reliable when present.
    2. Standalone ISO-3166-1 alpha-3 code on its own line (e.g. "COD").
    3. Nationality word detection (e.g. "CONGOLAISE" → COD).
    4. Fuzzy keyword scoring against each country's classifier_keywords.

    Returns ISO-3166-1 alpha-3 or None if no country is identified.
    """
    # --- 1. MRZ nationality ---
    # Import here to avoid circular import at module level
    from .mrz import find_mrz
    mrz = find_mrz(texts)
    if mrz and mrz.valid and mrz.nationality:
        corrected = fix_nationality_code(mrz.nationality)
        iso3 = _MRZ_TO_ISO3.get(corrected.upper())
        if iso3 and iso3 in _REGISTRY:
            logger.debug("country_registry: MRZ nationality=%s → %s", mrz.nationality, iso3)
            return iso3

    # --- 2. Standalone ISO code on a line ---
    for line in texts:
        iso_code = is_standalone_iso3(line)
        if iso_code and iso_code in _REGISTRY:
            logger.debug("country_registry: standalone ISO code=%s", iso_code)
            return iso_code

    # --- 3. Nationality word on a line ---
    for line in texts:
        nat_iso = lookup_nationality_word(line)
        if nat_iso and nat_iso in _REGISTRY:
            logger.debug("country_registry: nationality word '%s' → %s", line.strip(), nat_iso)
            return nat_iso

    # --- 4. Fuzzy keyword scoring ---
    full_text = " ".join(texts)
    full_norm = norm_text(full_text)
    scores: dict[str, int] = {}

    for iso3, country in _REGISTRY.items():
        score = 0
        for doc in country.documents.values():
            # Exact normalised match (fast)
            for kw in doc.classifier_keywords:
                if kw in full_norm:
                    score += 2  # exact match worth 2

            # Fuzzy match on raw keywords (handles OCR typos)
            fuzzy = _fuzzy_keyword_score(full_text, doc.classifier_keywords_raw)
            score += fuzzy  # fuzzy match worth 1

        if score:
            scores[iso3] = score

    if not scores:
        return None

    best = max(scores, key=lambda k: scores[k])
    logger.debug("country_registry: fuzzy keyword scores=%s → %s", scores, best)
    return best


def get_field_labels(country_iso3: str, doc_type: str, field_name: str) -> list[str]:
    """
    Return the normalised label list for (country, doc_type, field_name).
    Returns an empty list if any level is not found.
    """
    country = _REGISTRY.get(country_iso3.upper())
    if country is None:
        return []
    doc = country.documents.get(doc_type)
    if doc is None:
        return []
    return doc.fields.get(field_name, [])


def get_classifier_keywords(country_iso3: str, doc_type: str) -> list[str]:
    """
    Return normalised classifier keywords for (country, doc_type).
    Returns an empty list if not found.
    """
    country = _REGISTRY.get(country_iso3.upper())
    if country is None:
        return []
    doc = country.documents.get(doc_type)
    if doc is None:
        return []
    return doc.classifier_keywords


@lru_cache(maxsize=None)
def get_all_classifier_keywords() -> dict[str, dict[str, list[str]]]:
    """
    Return the full {country: {doc_type: [keywords]}} mapping.
    Cached after first call.
    """
    return {
        iso3: {
            doc_type: doc.classifier_keywords
            for doc_type, doc in country.documents.items()
        }
        for iso3, country in _REGISTRY.items()
    }


def matches_any_label(line: str, country_iso3: str, doc_type: str, field_name: str) -> bool:
    """
    Convenience: True if the normalised form of *line* contains any label
    registered for this (country, doc_type, field_name) combination.
    """
    norm = norm_text(line)
    return any(lbl in norm for lbl in get_field_labels(country_iso3, doc_type, field_name))
