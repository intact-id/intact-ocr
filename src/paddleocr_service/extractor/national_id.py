from __future__ import annotations

import re
from typing import Optional

from .date_utils import parse_date, norm_text, extract_inline_value
from .mrz import find_mrz
from .country_registry import get_field_labels
from .labels import (
    N_FULL_NAME, N_SURNAME, N_GIVEN_NAME,
    N_DOB, N_ISSUE_DATE, N_ID_NUMBER,
    N_SEX, N_NATIONALITY,
    N_PLACE_OF_ISSUE, N_DISTRICT, N_PLACE_OF_BIRTH,
)
from ..models import DocumentFields, FieldConfidence

# Generic alphanumeric ID — 5-20 chars, at least 4 digits
_ID_PATTERN = re.compile(r'\b([A-Z0-9]{5,20})\b')
# Minimum digits to be a plausible ID (avoids matching short country codes, etc.)
_MIN_DIGITS = 4

_LABEL_WORDS = {
    "republic", "national", "identity", "card", "date", "birth",
    "issue", "place", "district", "sex", "gender", "name", "number",
    "id", "nationality", "country", "passport", "licence", "license",
}


def _matches(line: str, norm_labels: list[str]) -> bool:
    nl = norm_text(line)
    return any(lbl in nl for lbl in norm_labels)


def _value_after(texts: list[str], idx: int, window: int = 3) -> Optional[str]:
    for j in range(idx + 1, min(idx + window + 1, len(texts))):
        c = texts[j].strip()
        if c:
            return c
    return None


# Card header text ("REPUBLIC OF KENYA", "JAMHURI YA KENYA", …) is all letters and several words, so
# it looks like a name. Matched as substrings because OCR often merges words ("REPUBLICOF KENYA",
# "JAMHURIYA KENYA") and whole-word checks then miss it.
_HEADER_MARKERS = ("republic", "jamhuri", "kenya", "government", "ministry")


def _is_card_header(text: str) -> bool:
    t = text.lower()
    return any(marker in t for marker in _HEADER_MARKERS)


def _looks_like_name(text: str) -> bool:
    t = text.strip().upper()
    if len(t) < 3 or len(t) > 70:
        return False
    # Mostly letters and spaces (allow hyphens and apostrophes for names like O'BRIEN, AL-RASHID)
    if not re.match(r"^[A-Z\s\-']+$", t):
        return False
    words = t.split()
    if len(words) < 2:
        return False
    if any(w.lower() in _LABEL_WORDS for w in words):
        return False
    if _is_card_header(t):
        return False
    return True


def _is_plausible_id(value: str) -> bool:
    """Value has enough digits and is not a date or pure word."""
    digits = sum(c.isdigit() for c in value)
    return digits >= _MIN_DIGITS and "/" not in value


# Labels of other numbers printed next to the ID number (e.g. the card serial on Kenyan IDs).
_OTHER_NUMBER_LABELS = ("serial", "nambari ya kadi")


def _box_center(box) -> Optional[tuple[float, float]]:
    try:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    except (TypeError, IndexError, ZeroDivisionError):
        return None


def _closest_id_value(texts: list[str], label_idx: int, line_boxes: dict[str, list]) -> Optional[str]:
    """
    The plausible ID-number line nearest (by box centre) to the label at texts[label_idx],
    skipping any number that sits closer to another number's label (e.g. "SERIAL NUMBER").
    None when positions are missing or nothing plausible is nearby.
    """
    label_c = _box_center(line_boxes.get(texts[label_idx]))
    if label_c is None:
        return None
    other_label_cs = [
        c for t in texts
        if any(lbl in norm_text(t) for lbl in _OTHER_NUMBER_LABELS)
        and (c := _box_center(line_boxes.get(t))) is not None
    ]

    def dist(a, b):
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    best, best_d = None, None
    lo, hi = max(0, label_idx - 6), min(len(texts), label_idx + 7)
    for j in range(lo, hi):
        if j == label_idx:
            continue
        m = _ID_PATTERN.search(texts[j].upper())
        if not (m and _is_plausible_id(m.group(1))) or parse_date(texts[j]):
            continue
        c = _box_center(line_boxes.get(texts[j]))
        if c is None:
            continue
        d = dist(c, label_c)
        if any(dist(c, oc) < d for oc in other_label_cs):
            continue  # belongs to the serial number (or similar), not the ID number
        if best_d is None or d < best_d:
            best, best_d = texts[j], d
    return best


def _resolve_labels(country: Optional[str], doc_type: str, field: str, fallback: list[str]) -> list[str]:
    """
    Return country-specific labels from the registry when available, merged
    with the global fallback list so we never lose coverage.
    """
    if not country:
        return fallback
    specific = get_field_labels(country, doc_type, field)
    if not specific:
        return fallback
    # Merge: country-specific first (higher priority in matching order)
    combined = specific + [lbl for lbl in fallback if lbl not in specific]
    return combined


class NationalIdExtractor:
    """
    Generic national ID extractor.
    Works for any country — uses international label vocabulary and
    MRZ where available (some countries put TD1 MRZ on ID cards).
    When a country is detected, country-specific labels from documents.yaml
    are used first, then the global vocabulary as fallback.
    """

    _DOC_TYPE = "national_id"

    def extract(
        self,
        texts: list[str],
        line_conf: dict[str, float],
        country: Optional[str] = None,
        line_boxes: Optional[dict[str, list]] = None,
    ) -> tuple[DocumentFields, FieldConfidence]:
        """line_boxes: OCR box (4 corner points) per line text, when available — used to pick
        the value that sits next to its label on multi-column cards."""
        fields = DocumentFields()
        conf = FieldConfidence()

        def labels(field: str, fallback: list[str]) -> list[str]:
            return _resolve_labels(country, self._DOC_TYPE, field, fallback)

        # --- MRZ (TD1 on ID cards) ---
        mrz = find_mrz(texts)
        if mrz and mrz.valid:
            fields.id_number   = mrz.document_number
            fields.date_of_birth = mrz.date_of_birth
            fields.sex         = mrz.sex
            fields.expiry_date = mrz.expiry_date
            fields.nationality = mrz.nationality
            fields.surname     = mrz.surname
            fields.given_names = mrz.given_names
            fields.full_name   = mrz.full_name
            conf.id_number     = 0.98 if mrz.document_number else None
            conf.date_of_birth = 0.98 if mrz.date_of_birth else None
            conf.sex           = 0.98 if mrz.sex else None
            conf.expiry_date   = 0.98 if mrz.expiry_date else None
            conf.nationality   = 0.95 if mrz.nationality else None
            conf.full_name     = 0.95 if mrz.full_name else None

        # --- ID number ---
        if not fields.id_number:
            id_labels = labels("id_number", N_ID_NUMBER)
            for i, line in enumerate(texts):
                if _matches(line, id_labels):
                    found = False
                    # Inline (value merged on same line e.g. "NOMC1003123")
                    inline = extract_inline_value(line, id_labels)
                    if inline:
                        m = _ID_PATTERN.search(inline.upper())
                        if m and _is_plausible_id(m.group(1)):
                            fields.id_number = m.group(1)
                            conf.id_number = round(line_conf.get(line, 0.9), 3)
                            found = True
                    # By position: on two-column cards (Kenya: serial number left, ID number
                    # right) OCR interleaves the columns, so the nearest number in reading order
                    # can be the serial. Take the number physically closest to the label instead.
                    if not found and line_boxes:
                        value_line = _closest_id_value(texts, i, line_boxes)
                        if value_line is not None:
                            fields.id_number = _ID_PATTERN.search(value_line.upper()).group(1)
                            conf.id_number = round(line_conf.get(value_line, 0.9), 3)
                            found = True
                    # Forward (value below label)
                    if not found:
                        for j in range(i + 1, min(i + 5, len(texts))):
                            m = _ID_PATTERN.search(texts[j].upper())
                            if m and _is_plausible_id(m.group(1)):
                                fields.id_number = m.group(1)
                                conf.id_number = round(line_conf.get(texts[j], 0.9), 3)
                                found = True
                                break
                    # Backward (value above label — e.g. side-by-side columns)
                    if not found:
                        for j in range(i - 1, max(i - 5, -1), -1):
                            m = _ID_PATTERN.search(texts[j].upper())
                            if m and _is_plausible_id(m.group(1)):
                                fields.id_number = m.group(1)
                                conf.id_number = round(line_conf.get(texts[j], 0.85), 3)
                                break
                    break
            # Fallback: first plausible standalone ID on any line
            if not fields.id_number:
                candidates = []
                for line in texts:
                    m = _ID_PATTERN.search(line.upper())
                    if m and _is_plausible_id(m.group(1)) and not parse_date(line):
                        candidates.append((m.group(1), line))
                # No label was read. On Kenyan IDs the ID number has at most 8 digits and the
                # card serial printed beside it has 9, so prefer a 7-8 digit all-numeric value
                # over simply the first number in reading order (which can be the serial).
                if country == "KEN":
                    kenyan = [c for c in candidates if c[0].isdigit() and 7 <= len(c[0]) <= 8]
                    candidates = kenyan + [c for c in candidates if c not in kenyan]
                if candidates:
                    value, line = candidates[0]
                    fields.id_number = value
                    conf.id_number = round(line_conf.get(line, 0.7), 3)

        # --- Full name ---
        if not fields.full_name:
            surname_labels = labels("surname", N_SURNAME)
            given_labels   = labels("given_names", N_GIVEN_NAME)
            full_labels    = labels("full_name", N_FULL_NAME)

            def _is_name_value(v: str) -> bool:
                """Reject values that look like ID numbers, not names."""
                digits = sum(c.isdigit() for c in v)
                return digits < 4 and len(v) >= 2

            # Try surname + given names separately first
            for i, line in enumerate(texts):
                if _matches(line, surname_labels) and not fields.surname:
                    # Inline first (e.g. "NomMBAYA")
                    v = extract_inline_value(line, surname_labels)
                    if v and _is_name_value(v):
                        fields.surname = v.replace('/', ' ').strip().upper()
                    elif not fields.surname:
                        v = _value_after(texts, i, 1)
                        if v and _is_name_value(v) and _looks_like_name(v):
                            fields.surname = v.strip().upper()
                if _matches(line, given_labels) and not fields.given_names:
                    # Inline first (e.g. "Postnomi/PrenomTSHIBANGU/DAN")
                    v = extract_inline_value(line, given_labels)
                    if v and _is_name_value(v):
                        fields.given_names = v.replace('/', ' ').strip().upper()
                    elif not fields.given_names:
                        v = _value_after(texts, i, 1)
                        if v and _is_name_value(v) and _looks_like_name(v):
                            fields.given_names = v.strip().upper()

            if fields.surname and fields.given_names:
                fields.full_name = f"{fields.given_names} {fields.surname}"
                conf.full_name = 0.85
            elif fields.surname:
                fields.full_name = fields.surname
                conf.full_name = 0.75
            else:
                # Look for "FULL NAME" label
                for i, line in enumerate(texts):
                    if _matches(line, full_labels):
                        # Inline first (e.g. "FRLNAVESJOHN DOE"). A plural label leaves junk
                        # behind ("FULL NAMES" minus "full name" = "S"), so only trust the inline
                        # value when it's name-like; otherwise read the lines below the label.
                        v = extract_inline_value(line, full_labels)
                        if not (v and _looks_like_name(v)):
                            v = next(
                                (c.strip() for c in texts[i + 1:i + 3] if _looks_like_name(c)),
                                None,
                            )
                        if v and _looks_like_name(v):
                            fields.full_name = v.upper()
                            conf.full_name = round(line_conf.get(v, 0.85), 3)
                            break

                # Last resort: scan for any name-looking line
                if not fields.full_name:
                    for line in texts:
                        if _looks_like_name(line):
                            fields.full_name = line.strip().upper()
                            conf.full_name = round(line_conf.get(line, 0.6), 3)
                            break

        # --- Date of birth ---
        if not fields.date_of_birth:
            dob_labels = labels("date_of_birth", N_DOB)
            for i, line in enumerate(texts):
                if _matches(line, dob_labels):
                    # Inline date (e.g. "Date/Lieu de naissance02/07/2002")
                    dob = parse_date(line)
                    if not dob:
                        inline = extract_inline_value(line, dob_labels)
                        if inline:
                            dob = parse_date(inline)
                    if not dob and i + 1 < len(texts):
                        dob = parse_date(texts[i + 1])
                    if dob:
                        fields.date_of_birth = dob
                        conf.date_of_birth = round(line_conf.get(line, 0.9), 3)
                        break
            if not fields.date_of_birth:
                for line in texts:
                    dob = parse_date(line)
                    if dob:
                        fields.date_of_birth = dob
                        conf.date_of_birth = round(line_conf.get(line, 0.6), 3)
                        break

        # --- Sex ---
        if not fields.sex:
            sex_labels = labels("sex", N_SEX)
            _MALE_VALUES = {"M", "MALE", "MASCULIN"}
            _FEMALE_VALUES = {"F", "FEMALE", "FEMININ", "FÉMININ"}
            _ALL_SEX_VALUES = _MALE_VALUES | _FEMALE_VALUES
            for i, line in enumerate(texts):
                if _matches(line, sex_labels):
                    # Inline value (e.g. "Sexe:M" or "SexeM")
                    inline = extract_inline_value(line, sex_labels)
                    if inline and inline.strip().upper() in _ALL_SEX_VALUES:
                        fields.sex = "M" if inline.strip().upper() in _MALE_VALUES else "F"
                        conf.sex = 0.95
                        break
                    m = re.search(r'\b(M|F)\b', line.upper())
                    if m:
                        fields.sex = m.group(1)
                        conf.sex = 0.95
                        break
                    nxt = _value_after(texts, i, 1)
                    if nxt and nxt.strip().upper() in _ALL_SEX_VALUES:
                        fields.sex = "M" if nxt.strip().upper() in _MALE_VALUES else "F"
                        conf.sex = 0.95
                        break

        # --- Nationality ---
        if not fields.nationality:
            nat_labels = labels("nationality", N_NATIONALITY)
            for i, line in enumerate(texts):
                if _matches(line, nat_labels):
                    # Inline value
                    inline = extract_inline_value(line, nat_labels)
                    if inline and re.match(r'^[A-Z][A-Z\s]+$', inline.upper()) and len(inline) > 2:
                        fields.nationality = inline.strip().upper()
                        conf.nationality = 0.85
                        break
                    m = re.search(r'[:\s]+([A-Z][A-Z\s]{1,30})', line.upper())
                    if m:
                        fields.nationality = m.group(1).strip()
                        conf.nationality = 0.85
                    else:
                        v = _value_after(texts, i, 1)
                        if v and re.match(r'^[A-Z][A-Z\s]+$', v.upper()) and len(v) > 2:
                            fields.nationality = v.upper()
                            conf.nationality = 0.8
                    break

        # --- Date of issue ---
        issue_labels = labels("date_of_issue", N_ISSUE_DATE)
        for i, line in enumerate(texts):
            if _matches(line, issue_labels):
                date = parse_date(line) or (parse_date(texts[i + 1]) if i + 1 < len(texts) else None)
                if date:
                    fields.date_of_issue = date
                    conf.date_of_issue = round(line_conf.get(line, 0.85), 3)
                    break

        # --- Place of issue ---
        poi_labels = labels("place_of_issue", N_PLACE_OF_ISSUE)
        for i, line in enumerate(texts):
            if _matches(line, poi_labels):
                v = _value_after(texts, i, 1)
                if v and len(v) > 2 and not parse_date(v):
                    fields.place_of_issue = v.upper()
                    conf.place_of_issue = round(line_conf.get(v, 0.8), 3)
                break

        # --- Place of birth ---
        pob_labels = labels("place_of_birth", N_PLACE_OF_BIRTH)
        for i, line in enumerate(texts):
            if _matches(line, pob_labels):
                v = _value_after(texts, i, 1)
                if v and len(v) > 2 and not parse_date(v):
                    fields.place_of_birth = v.upper()
                    conf.place_of_birth = round(line_conf.get(v, 0.8), 3)
                break

        # --- District of birth ---
        dist_labels = labels("district_of_birth", N_DISTRICT)
        for i, line in enumerate(texts):
            if _matches(line, dist_labels):
                v = _value_after(texts, i, 1)
                if v and len(v) > 2 and not parse_date(v):
                    fields.district_of_birth = v.upper()
                    conf.district_of_birth = round(line_conf.get(v, 0.8), 3)
                break

        return fields, conf
