from __future__ import annotations

import re
from typing import Optional

from .date_utils import parse_date, norm_text, extract_date_and_remainder
from .country_registry import get_field_labels
from .labels import (
    N_FULL_NAME, N_SURNAME, N_GIVEN_NAME,
    N_DOB, N_EXPIRY, N_ISSUE_DATE, N_SEX, N_NATIONALITY,
    N_ID_NUMBER, N_PLACE_OF_BIRTH,
)
from ..models import DocumentFields, FieldConfidence


def _resolve_labels(country: Optional[str], doc_type: str, field: str, fallback: list[str]) -> list[str]:
    if not country:
        return fallback
    specific = get_field_labels(country, doc_type, field)
    if not specific:
        return fallback
    return specific + [lbl for lbl in fallback if lbl not in specific]

# Flexible license/ID number: alphanumeric, 5-20 chars, at least 3 digits
_NUM_PATTERN = re.compile(r'\b([A-Z0-9]{5,20})\b')
_MIN_DIGITS = 3

_LICENSE_NUM_LABELS = (
    "licence no", "license no", "licence number", "license number",
    "dl no", "dl number", "driver no", "permit no", "permit number",
    "permis no", "numero de permis", "numero de licencia",
    "fuhrerscheinnummer",
)
_N_LIC_LABELS = [norm_text(l) for l in _LICENSE_NUM_LABELS]

_LABEL_WORDS = {
    "date", "birth", "sex", "gender", "nationality", "address",
    "issue", "expiry", "place", "district", "province", "republic",
}


def _matches(line: str, norm_labels: list[str]) -> bool:
    nl = norm_text(line)
    return any(lbl in nl for lbl in norm_labels)


def _value_after(texts: list[str], idx: int, window: int = 2) -> Optional[str]:
    for j in range(idx + 1, min(idx + window + 1, len(texts))):
        c = texts[j].strip()
        if c:
            return c
    return None


def _is_name_value(text: str) -> bool:
    """
    Accept label-directed name values — allows single words (surname alone),
    letters, hyphens and apostrophes only.
    """
    t = text.strip().upper()
    return (
        2 < len(t) < 70
        and bool(re.match(r"^[A-Z\s\-']+$", t))
        and not any(kw in t.lower() for kw in _LABEL_WORDS)
    )


def _is_plausible_id(value: str) -> bool:
    return sum(c.isdigit() for c in value) >= _MIN_DIGITS


def _find_id_near_label(texts: list[str], label_idx: int) -> Optional[tuple[str, int]]:
    """Search forward then backward from label_idx for a plausible ID value."""
    for j in range(label_idx + 1, min(label_idx + 5, len(texts))):
        m = _NUM_PATTERN.search(texts[j].upper())
        if m and _is_plausible_id(m.group(1)):
            return m.group(1), j
    for j in range(label_idx - 1, max(label_idx - 5, -1), -1):
        m = _NUM_PATTERN.search(texts[j].upper())
        if m and _is_plausible_id(m.group(1)):
            return m.group(1), j
    return None


class DriversLicenseExtractor:

    _DOC_TYPE = "drivers_license"

    def extract(
        self,
        texts: list[str],
        line_conf: dict[str, float],
        country: Optional[str] = None,
    ) -> tuple[DocumentFields, FieldConfidence]:
        fields = DocumentFields()
        conf = FieldConfidence()

        def labels(field: str, fallback: list[str]) -> list[str]:
            return _resolve_labels(country, self._DOC_TYPE, field, fallback)

        # --- License / ID number ---
        id_labels = labels("id_number", _N_LIC_LABELS)
        # 1. Look for DL-specific labels
        for i, line in enumerate(texts):
            if _matches(line, id_labels):
                hit = _find_id_near_label(texts, i)
                if hit:
                    fields.id_number = hit[0]
                    conf.id_number = round(line_conf.get(texts[hit[1]], 0.9), 3)
                break

        # 2. Fall back to generic ID number labels (e.g. "NO D'IDENTITE NATIONAL ID NO")
        if not fields.id_number:
            generic_id = labels("id_number", N_ID_NUMBER)
            for i, line in enumerate(texts):
                if _matches(line, generic_id):
                    hit = _find_id_near_label(texts, i)
                    if hit:
                        fields.id_number = hit[0]
                        conf.id_number = round(line_conf.get(texts[hit[1]], 0.85), 3)
                    break

        # --- Name (surname + given names) ---
        # A line can match both N_SURNAME ("nom" is inside "prenom") so we
        # prefer the more specific given-name match when both fire on the same line.
        surname_labels = labels("surname", N_SURNAME)
        given_labels   = labels("given_names", N_GIVEN_NAME)
        full_labels    = labels("full_name", N_FULL_NAME)
        for i, line in enumerate(texts):
            ln = norm_text(line)
            is_surname = any(lbl in ln for lbl in surname_labels)
            is_given   = any(lbl in ln for lbl in given_labels)

            if is_given:
                v = _value_after(texts, i, 1)
                if v and _is_name_value(v):
                    fields.given_names = v.strip().upper()
                    conf.given_names = round(line_conf.get(v, 0.85), 3)
            elif is_surname:
                # Only use as surname label if it does NOT also trigger given-name
                v = _value_after(texts, i, 1)
                if v and _is_name_value(v):
                    fields.surname = v.strip().upper()
                    conf.surname = round(line_conf.get(v, 0.85), 3)

            if _matches(line, full_labels) and not is_given and not is_surname:
                v = _value_after(texts, i, 1)
                if v and _is_name_value(v):
                    fields.full_name = v.strip().upper()
                    conf.full_name = round(line_conf.get(v, 0.85), 3)

        if not fields.full_name and fields.surname and fields.given_names:
            fields.full_name = f"{fields.given_names} {fields.surname}"
            conf.full_name = round(
                (conf.surname or 0.0 + conf.given_names or 0.0) / 2, 3
            )
        elif not fields.full_name and fields.surname:
            fields.full_name = fields.surname
            conf.full_name = conf.surname

        # --- Date of birth (and place of birth if merged on same line) ---
        dob_labels = labels("date_of_birth", N_DOB)
        for i, line in enumerate(texts):
            if _matches(line, dob_labels):
                # The DOB value may be on the same line or the next line
                # and may be merged with place of birth, e.g. "04-03-2004Goma"
                candidates = [line]
                if i + 1 < len(texts):
                    candidates.append(texts[i + 1])

                for candidate in candidates:
                    dob, place = extract_date_and_remainder(candidate)
                    if dob:
                        fields.date_of_birth = dob
                        conf.date_of_birth = round(line_conf.get(candidate, 0.9), 3)
                        if place and not fields.place_of_birth:
                            fields.place_of_birth = place.strip().upper()
                        break
                if fields.date_of_birth:
                    break

        # --- Place of birth (standalone label) ---
        pob_labels = labels("place_of_birth", N_PLACE_OF_BIRTH)
        if not fields.place_of_birth:
            for i, line in enumerate(texts):
                if _matches(line, pob_labels):
                    v = _value_after(texts, i, 1)
                    if v and not parse_date(v):
                        fields.place_of_birth = v.strip().upper()
                    break

        # --- Expiry date ---
        exp_labels = labels("expiry_date", N_EXPIRY)
        for i, line in enumerate(texts):
            if _matches(line, exp_labels):
                exp = parse_date(line) or (parse_date(texts[i + 1]) if i + 1 < len(texts) else None)
                if exp:
                    fields.expiry_date = exp
                    conf.expiry_date = round(line_conf.get(line, 0.9), 3)
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

        # --- Sex ---
        sex_labels = labels("sex", N_SEX)
        for i, line in enumerate(texts):
            if _matches(line, sex_labels):
                m = re.search(r'\b(M|F)\b', line.upper())
                if m:
                    fields.sex = m.group(1)
                    conf.sex = 0.95
                    break
                v = _value_after(texts, i, 1)
                if v and v.strip().upper() in ("M", "F", "MALE", "FEMALE",
                                                   "MASCULIN", "FEMININ", "FÉMININ"):
                    fields.sex = "M" if v.strip().upper() in ("M", "MALE", "MASCULIN") else "F"
                    conf.sex = 0.95
                    break

        # --- Nationality ---
        nat_labels = labels("nationality", N_NATIONALITY)
        for i, line in enumerate(texts):
            if _matches(line, nat_labels):
                # Try inline extraction (e.g. "NATIONALITY: KENYAN")
                # but skip if the extracted part is itself a nationality label word
                m = re.search(r'[:\s/]+([A-Z][A-Z\s]{2,30})', line.upper())
                if m:
                    candidate = m.group(1).strip()
                    if not any(lbl in norm_text(candidate) for lbl in N_NATIONALITY):
                        fields.nationality = candidate
                        conf.nationality = 0.85

                # Prefer the next-line value (cleaner source)
                if not fields.nationality:
                    v = _value_after(texts, i, 1)
                    if v and re.match(r'^[A-Z][A-Z\s]+$', v.upper()) and len(v) > 2:
                        fields.nationality = v.strip().upper()
                        conf.nationality = round(line_conf.get(v, 0.8), 3)
                break

        return fields, conf
