from __future__ import annotations

import re
from typing import Optional


def norm_text(s: str) -> str:
    """Lowercase and strip whitespace/punctuation separators.
    'DATE OFBIRTH' and 'date of birth' both become 'dateofbirth'."""
    return re.sub(r"[\s.\-_']+", '', s.lower())


MONTH_MAP = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}

# Use (?<!\d) / (?!\d) instead of \b so patterns work when date is
# immediately adjacent to letters (e.g. "04-03-2004Goma").
# Day and month allow 1 or 2 digits.

# D[D]/M[M]/YYYY
_DMY4 = re.compile(r'(?<!\d)(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})(?!\d)')
# YYYY/M[M]/D[D]
_YMD = re.compile(r'(?<!\d)(\d{4})[/\-\.](\d{1,2})[/\-\.](\d{1,2})(?!\d)')
# D[D] MMM YYYY  e.g. "15 JAN 1990"
_DMONTH = re.compile(
    r'(?<!\d)(\d{1,2})\s+(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+(\d{4})(?!\d)',
    re.IGNORECASE,
)
# D[D]/M[M]/YY  (short year, checked last)
_DMY2 = re.compile(r'(?<!\d)(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{2})(?!\d)')

_ALL_PATTERNS = [_DMONTH, _DMY4, _YMD, _DMY2]


def _expand_year(yy: int) -> int:
    return 1900 + yy if yy > 30 else 2000 + yy


def parse_date(text: str) -> Optional[str]:
    """Return the first date found in *text* as ISO YYYY-MM-DD, or None."""
    upper = text.upper()

    m = _DMONTH.search(upper)
    if m:
        day, mon, year = m.group(1), m.group(2).upper(), m.group(3)
        return f"{year}-{MONTH_MAP[mon]}-{day.zfill(2)}"

    m = _DMY4.search(upper)
    if m:
        day, month, year = m.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    m = _YMD.search(upper)
    if m:
        year, month, day = m.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    m = _DMY2.search(upper)
    if m:
        day, month, yy = m.groups()
        return f"{_expand_year(int(yy))}-{month.zfill(2)}-{day.zfill(2)}"

    return None


def extract_date_and_remainder(text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extract a date from *text* and return (iso_date, leftover_text).
    Useful when OCR merges date and place on the same line, e.g. '04-03-2004Goma'.
    """
    upper = text.upper()
    for pat, handler in [
        (_DMONTH, lambda m: f"{m.group(3)}-{MONTH_MAP[m.group(2).upper()]}-{m.group(1).zfill(2)}"),
        (_DMY4,   lambda m: f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"),
        (_YMD,    lambda m: f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"),
        (_DMY2,   lambda m: f"{_expand_year(int(m.group(3)))}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"),
    ]:
        m = pat.search(upper)
        if m:
            iso = handler(m)
            leftover = (text[: m.start()] + text[m.end() :]).strip(" ,/-.")
            return iso, leftover or None
    return None, None


# Characters stripped by norm_text — keep in sync with the regex above
_STRIP_CHARS = set(" .-_'")


def extract_inline_value(line: str, norm_labels: list[str]) -> Optional[str]:
    """
    Extract a value merged with its label on the same line.

    Examples:
      "NomMBAYA"                         → label "nom" → value "MBAYA"
      "Date/Lieu de naissance02/07/2002" → label "datelieudenaissance" → value "02/07/2002"
      "Postnomi/PrenomTSHIBANGU/DAN"    → label "postnomiprenom" → value "TSHIBANGU/DAN"

    Returns None if no label matches or the label covers the entire line.
    """
    nl = norm_text(line)
    for lbl in sorted(norm_labels, key=len, reverse=True):
        pos = nl.find(lbl)
        if pos == -1:
            continue
        end_pos = pos + len(lbl)
        if end_pos >= len(nl):
            continue  # label IS the whole line — no inline value

        # Map normalized end position back to original string offset
        norm_idx = 0
        orig_idx = len(line)  # default: end of line
        for i, ch in enumerate(line):
            if norm_idx >= end_pos:
                orig_idx = i
                break
            if ch.lower() not in _STRIP_CHARS:
                norm_idx += 1

        remainder = line[orig_idx:].strip(" :-/.'")
        if remainder and len(remainder) >= 1:
            return remainder
    return None

