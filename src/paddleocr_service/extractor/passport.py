from __future__ import annotations

import re
from typing import Optional

from .mrz import find_mrz
from .date_utils import parse_date, norm_text
from .country_registry import get_field_labels
from .ocr_corrections import lookup_nationality_word
from .labels import (
    N_SURNAME, N_GIVEN_NAME, N_DOB, N_EXPIRY,
    N_ISSUE_DATE, N_NATIONALITY, N_PLACE_OF_BIRTH,
)
from ..models import DocumentFields, FieldConfidence

# Generic passport number: 1-2 letters followed by 6-9 digits (covers most countries)
_PASSPORT_NUM_RE = re.compile(r'\b([A-Z]{1,2}\d{6,9})\b')
_PASSPORT_NUM_LABELS = (
    "passport no", "passport number", "no du passeport",
    "numero de pasaporte", "passnummer",
    "numero de passeport", "n° passeport",
)
_N_PASSPORT_NUM_LABELS = [norm_text(l) for l in _PASSPORT_NUM_LABELS]

# Words that are clearly NOT names (header text, labels, etc.)
_NON_NAME_WORDS = {
    "republic", "republique", "repuslique", "democratic", "democratique",
    "passport", "passeport", "pasipoti", "congo", "comgo",
    "kenya", "identity", "card", "carte", "national", "date", "birth",
    "issue", "expiry", "place", "sex", "sexe", "nationality", "nationalite",
    "etat", "civil", "numero", "minaffet", "direction", "migration",
    "office",
}

# Words that indicate a passport header line (to skip during name scanning)
_HEADER_NORM_PATTERNS = [
    norm_text(p) for p in [
        "republic", "republique", "democratic", "democratique",
        "passport", "passeport", "pasipoti",
        "congo", "kenya", "uganda", "tanzania",
    ]
]


def _matches(line: str, norm_labels: list[str]) -> bool:
    return any(lbl in norm_text(line) for lbl in norm_labels)


def _value_after(texts: list[str], idx: int, window: int = 2) -> Optional[str]:
    for j in range(idx + 1, min(idx + window + 1, len(texts))):
        c = texts[j].strip()
        if c:
            return c
    return None


def _resolve_labels(country: Optional[str], doc_type: str, field: str, fallback: list[str]) -> list[str]:
    if not country:
        return fallback
    specific = get_field_labels(country, doc_type, field)
    if not specific:
        return fallback
    return specific + [lbl for lbl in fallback if lbl not in specific]


def _is_header_line(line: str) -> bool:
    """True if this line is a passport header (country name, doc type, etc.)."""
    n = norm_text(line)
    return any(p in n for p in _HEADER_NORM_PATTERNS)


def _is_name_candidate(text: str) -> bool:
    """
    True if text looks like a person's name — all letters + spaces/hyphens,
    not a known label/header word, reasonable length.
    """
    t = text.strip()
    if len(t) < 2 or len(t) > 50:
        return False
    # Must be mostly letters (allow hyphen, apostrophe, space)
    if not re.match(r"^[A-Za-z\s\-']+$", t):
        return False
    # Must not be a known non-name word
    words = t.lower().split()
    if any(w in _NON_NAME_WORDS for w in words):
        return False
    return True


def _is_nationality_text(text: str) -> bool:
    """True if text is a known nationality word."""
    return lookup_nationality_word(text) is not None


def _is_place_candidate(text: str) -> bool:
    """True if text looks like a place name — all caps, single word or short phrase."""
    t = text.strip()
    if len(t) < 2 or len(t) > 40:
        return False
    if not re.match(r"^[A-Za-z\s\-']+$", t):
        return False
    words = t.lower().split()
    if any(w in _NON_NAME_WORDS for w in words):
        return False
    return True


class PassportExtractor:
    """
    Passport field extractor.
    MRZ (ISO 9303 TD3) is the primary source — it works for every country.
    Visual zone text (label-based) is the secondary source.
    Positional heuristics are the tertiary fallback when no labels exist.
    Country-specific label vocabulary is merged with global labels.
    """

    _DOC_TYPE = "passport"

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

        # --- MRZ first (most reliable, universal) ---
        mrz = find_mrz(texts)
        mrz_names_reliable = False
        if mrz and mrz.valid:
            if mrz.full_name:
                fields.full_name   = mrz.full_name
            if mrz.surname:
                fields.surname     = mrz.surname
            if mrz.given_names:
                fields.given_names = mrz.given_names
            if mrz.document_number:
                fields.id_number   = mrz.document_number
            if mrz.date_of_birth:
                fields.date_of_birth = mrz.date_of_birth
            if mrz.sex:
                fields.sex         = mrz.sex
            if mrz.expiry_date:
                fields.expiry_date = mrz.expiry_date
            if mrz.nationality:
                fields.nationality = mrz.nationality

            # If MRZ had proper given_names, names are reliable (full line 1 parsed).
            # Otherwise names came from a truncated/garbled MRZ line 1 — lower confidence.
            mrz_names_reliable = mrz.given_names is not None
            if mrz_names_reliable:
                conf.full_name     = 0.95 if fields.full_name else None
            else:
                # Truncated MRZ line 1: names may be wrong — set low confidence
                # so positional heuristics can override
                conf.full_name     = 0.4 if fields.full_name else None
            conf.id_number     = 0.98 if fields.id_number else None
            conf.date_of_birth = 0.98 if fields.date_of_birth else None
            conf.sex           = 0.98 if fields.sex else None
            conf.expiry_date   = 0.98 if fields.expiry_date else None
            conf.nationality   = 0.95 if fields.nationality else None

        # --- Visual zone: label-based extraction to fill gaps ---
        self._extract_label_based(texts, line_conf, fields, conf, labels)

        # --- Positional heuristics: last-resort fallback ---
        self._extract_positional(texts, line_conf, fields, conf)

        return fields, conf

    def _extract_label_based(
        self,
        texts: list[str],
        line_conf: dict[str, float],
        fields: DocumentFields,
        conf: FieldConfidence,
        labels,
    ) -> None:
        """Extract fields using labelled text (e.g. "Surname:", "Date of Birth:")."""

        if not fields.full_name:
            surname_labels = labels("surname", N_SURNAME)
            given_labels   = labels("given_names", N_GIVEN_NAME)
            surname, given = None, None
            for i, line in enumerate(texts):
                if _matches(line, surname_labels):
                    v = _value_after(texts, i, 1)
                    if v:
                        surname = v.upper()
                if _matches(line, given_labels):
                    v = _value_after(texts, i, 1)
                    if v:
                        given = v.upper()
            if surname and given:
                fields.surname = surname
                fields.given_names = given
                fields.full_name = f"{given} {surname}"
                conf.full_name = 0.85
            elif surname:
                fields.surname = surname
                fields.full_name = surname
                conf.full_name = 0.75

        if not fields.id_number:
            id_labels = labels("id_number", _N_PASSPORT_NUM_LABELS)
            for i, line in enumerate(texts):
                if _matches(line, id_labels):
                    m = _PASSPORT_NUM_RE.search(line.upper())
                    if not m:
                        v = _value_after(texts, i, 1)
                        if v:
                            m = _PASSPORT_NUM_RE.search(v.upper())
                    if m:
                        fields.id_number = m.group(1)
                        conf.id_number = 0.9
                        break
            if not fields.id_number:
                for line in texts:
                    m = _PASSPORT_NUM_RE.search(line.upper())
                    if m:
                        fields.id_number = m.group(1)
                        conf.id_number = round(line_conf.get(line, 0.7), 3)
                        break

        if not fields.date_of_birth:
            dob_labels = labels("date_of_birth", N_DOB)
            for i, line in enumerate(texts):
                if _matches(line, dob_labels):
                    dob = parse_date(line) or (parse_date(texts[i + 1]) if i + 1 < len(texts) else None)
                    if dob:
                        fields.date_of_birth = dob
                        conf.date_of_birth = 0.85
                        break

        if not fields.expiry_date:
            exp_labels = labels("expiry_date", N_EXPIRY)
            for i, line in enumerate(texts):
                if _matches(line, exp_labels):
                    exp = parse_date(line) or (parse_date(texts[i + 1]) if i + 1 < len(texts) else None)
                    if exp:
                        fields.expiry_date = exp
                        conf.expiry_date = 0.85
                        break

        if not fields.nationality:
            nat_labels = labels("nationality", N_NATIONALITY)
            for i, line in enumerate(texts):
                if _matches(line, nat_labels):
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

        if not fields.place_of_birth:
            pob_labels = labels("place_of_birth", N_PLACE_OF_BIRTH)
            for i, line in enumerate(texts):
                if _matches(line, pob_labels):
                    v = _value_after(texts, i, 1)
                    if v and not parse_date(v):
                        fields.place_of_birth = v.upper()
                    break

        if not fields.date_of_issue:
            issue_labels = labels("date_of_issue", N_ISSUE_DATE)
            for i, line in enumerate(texts):
                if _matches(line, issue_labels):
                    date = parse_date(line) or (parse_date(texts[i + 1]) if i + 1 < len(texts) else None)
                    if date:
                        fields.date_of_issue = date
                        conf.date_of_issue = 0.85
                        break

    def _extract_positional(
        self,
        texts: list[str],
        line_conf: dict[str, float],
        fields: DocumentFields,
        conf: FieldConfidence,
    ) -> None:
        """
        Last-resort positional heuristics for passports without labels.

        Uses order-aware state machine matching the standard passport layout:
          header → passport_no → surname → given_names → DOB → nationality
          → place_of_birth → issue_date → [personal_no] → expiry_date → [authority]

        Lines are processed IN ORDER. Each classified line advances the state.
        """
        # Determine what we still need
        name_override = (conf.full_name is not None and conf.full_name < 0.5)
        need_surname    = not fields.surname or name_override
        need_given      = not fields.given_names or name_override
        need_dob        = not fields.date_of_birth
        need_nationality = not fields.nationality
        need_pob        = not fields.place_of_birth
        need_issue      = not fields.date_of_issue
        need_expiry     = not fields.expiry_date

        # State machine: tracks what we expect next
        # States: "names", "post_names", "post_nationality", "done"
        state = "names"

        collected_names: list[tuple[str, float]] = []
        date_count = 0  # how many dates we've seen so far in the visual zone

        for line in texts:
            stripped = line.strip()
            if not stripped:
                continue

            # Skip MRZ lines
            if "<" in stripped and len(stripped) >= 20:
                continue

            # Skip header lines
            if _is_header_line(stripped):
                continue

            # Skip passport number
            if _PASSPORT_NUM_RE.match(stripped.upper()):
                continue

            # Skip standalone ISO codes (e.g. "COD" on its own)
            from .ocr_corrections import is_standalone_iso3
            if is_standalone_iso3(stripped):
                continue

            # Skip pure digit strings (personal numbers like "110808792")
            if stripped.replace(" ", "").isdigit() and len(stripped) >= 5:
                continue

            line_c = line_conf.get(line, 0.5)

            # --- Try to parse as date ---
            date_val = parse_date(stripped)
            if date_val:
                date_count += 1

                if state == "names":
                    # We hit a date — names phase is over
                    state = "post_names"

                # Passport date order: 1st=DOB, 2nd=issue, 3rd=expiry
                if date_count == 1:
                    # First date = DOB
                    if need_dob:
                        fields.date_of_birth = date_val
                        conf.date_of_birth = round(min(line_c, 0.55), 3)
                        need_dob = False
                    # If MRZ already filled DOB, skip this (it's the visual zone duplicate)
                elif date_count == 2:
                    if need_issue:
                        fields.date_of_issue = date_val
                        conf.date_of_issue = round(min(line_c, 0.5), 3)
                        need_issue = False
                elif date_count == 3:
                    if need_expiry:
                        fields.expiry_date = date_val
                        conf.expiry_date = round(min(line_c, 0.5), 3)
                        need_expiry = False
                continue

            # --- Try as nationality word ---
            if _is_nationality_text(stripped):
                iso = lookup_nationality_word(stripped)
                if iso:
                    state = "post_nationality"
                    if need_nationality:
                        fields.nationality = iso
                        conf.nationality = round(min(line_c, 0.6), 3)
                        need_nationality = False
                continue

            # --- Try as name or place (depends on state) ---
            if _is_name_candidate(stripped):
                if state == "names":
                    collected_names.append((stripped.upper(), line_c))
                elif state in ("post_names", "post_nationality"):
                    # After nationality → this is likely a place, not a name
                    if need_pob:
                        fields.place_of_birth = stripped.upper()
                        conf.place_of_birth = round(min(line_c, 0.5), 3)
                        need_pob = False
                continue

            # --- Place candidate (after nationality) ---
            if state in ("post_names", "post_nationality") and _is_place_candidate(stripped):
                if need_pob:
                    fields.place_of_birth = stripped.upper()
                    conf.place_of_birth = round(min(line_c, 0.5), 3)
                    need_pob = False
                continue

        # --- Assign collected names ---
        if collected_names and (need_surname or need_given):
            if need_surname:
                fields.surname = collected_names[0][0]
                conf.surname = round(min(collected_names[0][1], 0.6), 3)

            if need_given and len(collected_names) > 1:
                given_parts = [n[0] for n in collected_names[1:]]
                fields.given_names = " ".join(given_parts)
                avg_c = sum(n[1] for n in collected_names[1:]) / len(collected_names[1:])
                conf.given_names = round(min(avg_c, 0.6), 3)

            if (not fields.full_name or name_override) and fields.surname:
                if fields.given_names:
                    fields.full_name = f"{fields.given_names} {fields.surname}"
                else:
                    fields.full_name = fields.surname
                conf.full_name = round(min(conf.surname or 0.5, 0.6), 3)

