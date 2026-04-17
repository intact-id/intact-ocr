"""
ocr_corrections.py
~~~~~~~~~~~~~~~~~~~
Context-aware OCR error corrections for document extraction.

Two main areas:
1. MRZ character fixes — alpha/digit confusion based on known field positions.
2. Nationality word mapping — e.g. "CONGOLAISE" → "COD".
"""
from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# MRZ character confusion maps
# ---------------------------------------------------------------------------

# Alpha positions: digit → letter (common OCR confusions)
_DIGIT_TO_ALPHA: dict[str, str] = {
    "0": "O",
    "1": "I",
    "5": "S",
    "8": "B",
}

# Digit positions: letter → digit
_ALPHA_TO_DIGIT: dict[str, str] = {v: k for k, v in _DIGIT_TO_ALPHA.items()}


def fix_mrz_alpha(text: str) -> str:
    """Fix OCR errors in MRZ fields that should be all-alpha (e.g. nationality)."""
    return "".join(_DIGIT_TO_ALPHA.get(c, c) for c in text.upper())


def fix_mrz_digits(text: str) -> str:
    """Fix OCR errors in MRZ fields that should be all-digit (e.g. dates)."""
    return "".join(_ALPHA_TO_DIGIT.get(c, c) for c in text.upper())


def fix_nationality_code(code: str) -> str:
    """
    Best-effort correction for a 3-letter ISO nationality code.
    E.g. 'C0D' → 'COD', '1ND' → 'IND'.
    """
    if not code or len(code) != 3:
        return code
    return fix_mrz_alpha(code)


# ---------------------------------------------------------------------------
# Nationality word → ISO-3166-1 alpha-3
# Maps demonym/adjective forms to their country code.
# ---------------------------------------------------------------------------

NATIONALITY_WORDS: dict[str, str] = {
    # DRC Congo
    "CONGOLAISE": "COD",
    "CONGOLAIS": "COD",
    "CONGOLESE": "COD",
    "RD CONGO": "COD",
    "RDC": "COD",
    "REPUBLIQUE DEMOCRATIQUE DU CONGO": "COD",

    # Kenya
    "KENYAN": "KEN",
    "KENYANE": "KEN",
    "KENYA": "KEN",

    # Uganda
    "UGANDAN": "UGA",
    "OUGANDAISE": "UGA",
    "OUGANDAIS": "UGA",

    # Tanzania
    "TANZANIAN": "TZA",
    "TANZANIENNE": "TZA",
    "TANZANIEN": "TZA",

    # Rwanda
    "RWANDAN": "RWA",
    "RWANDAISE": "RWA",
    "RWANDAIS": "RWA",

    # Burundi
    "BURUNDIAN": "BDI",
    "BURUNDAISE": "BDI",
    "BURUNDAIS": "BDI",

    # South Africa
    "SOUTH AFRICAN": "ZAF",
    "SUD-AFRICAINE": "ZAF",
    "SUD-AFRICAIN": "ZAF",

    # Nigeria
    "NIGERIAN": "NGA",
    "NIGERIANE": "NGA",

    # Ghana
    "GHANAIAN": "GHA",
    "GHANEENNE": "GHA",
    "GHANEEN": "GHA",

    # Ethiopia
    "ETHIOPIAN": "ETH",
    "ETHIOPIENNE": "ETH",
    "ETHIOPIEN": "ETH",

    # Cameroon
    "CAMEROONIAN": "CMR",
    "CAMEROUNAISE": "CMR",
    "CAMEROUNAIS": "CMR",

    # Senegal
    "SENEGALESE": "SEN",
    "SENEGALAISE": "SEN",
    "SENEGALAIS": "SEN",

    # Ivory Coast
    "IVORIAN": "CIV",
    "IVOIRIENNE": "CIV",
    "IVOIRIEN": "CIV",

    # Mali
    "MALIAN": "MLI",
    "MALIENNE": "MLI",
    "MALIEN": "MLI",

    # Togo
    "TOGOLESE": "TGO",
    "TOGOLAISE": "TGO",
    "TOGOLAIS": "TGO",

    # Generic
    "FRANCAISE": "FRA",
    "FRANCAIS": "FRA",
    "FRENCH": "FRA",
    "BRITISH": "GBR",
    "AMERICAN": "USA",
    "BELGIQUE": "BEL",
    "BELGE": "BEL",
    "BELGIAN": "BEL",
}

# Pre-build normalised lookup (uppercase, stripped)
_NORM_NAT_WORDS: dict[str, str] = {k.upper().strip(): v for k, v in NATIONALITY_WORDS.items()}


def lookup_nationality_word(text: str) -> Optional[str]:
    """
    Try to map a nationality word/demonym to an ISO-3166-1 alpha-3 code.
    Returns None if no match found.
    """
    cleaned = text.strip().upper()
    return _NORM_NAT_WORDS.get(cleaned)


# ---------------------------------------------------------------------------
# Known ISO-3166-1 alpha-3 codes (common subset for detection)
# ---------------------------------------------------------------------------

KNOWN_ISO3_CODES: set[str] = {
    "COD", "KEN", "UGA", "TZA", "RWA", "BDI", "ZAF", "NGA", "GHA",
    "ETH", "CMR", "SEN", "CIV", "MLI", "TGO", "AGO", "MOZ", "ZMB",
    "ZWE", "MWI", "NAM", "BWA", "LSO", "SWZ", "MDG", "COM", "MUS",
    "SYC", "DJI", "ERI", "SOM", "SDN", "SSD", "TCD", "CAF", "GAB",
    "COG", "GNQ", "STP", "BEN", "BFA", "NER", "GIN", "GNB", "SLE",
    "LBR", "GMB", "CPV", "MRT",
    # Non-African (common)
    "FRA", "GBR", "USA", "BEL", "DEU", "IND", "CHN", "PAK",
}


def is_standalone_iso3(line: str) -> Optional[str]:
    """
    Check if a line is a standalone 3-letter ISO code.
    Returns the code if matched, None otherwise.
    """
    cleaned = line.strip().upper()
    # Must be exactly 3 alpha chars (allow OCR digit confusion)
    if len(cleaned) != 3:
        return None
    corrected = fix_mrz_alpha(cleaned)
    if corrected in KNOWN_ISO3_CODES:
        return corrected
    return None
