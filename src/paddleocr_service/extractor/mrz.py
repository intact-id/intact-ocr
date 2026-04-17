from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .ocr_corrections import fix_mrz_alpha, fix_mrz_digits, fix_nationality_code


@dataclass
class MrzData:
    surname: Optional[str] = None
    given_names: Optional[str] = None
    full_name: Optional[str] = None
    document_number: Optional[str] = None
    nationality: Optional[str] = None
    date_of_birth: Optional[str] = None   # YYYY-MM-DD
    sex: Optional[str] = None             # M or F
    expiry_date: Optional[str] = None     # YYYY-MM-DD
    personal_number: Optional[str] = None
    valid: bool = False


# MRZ lines: uppercase letters, digits, and filler char <
# Lowered minimum from 28 → 20 to capture truncated OCR lines
_MRZ_RE = re.compile(r'^[A-Z0-9<]{20,44}$')


def _yymmdd_to_iso(yymmdd: str) -> Optional[str]:
    # Apply OCR digit correction first
    corrected = fix_mrz_digits(yymmdd)
    if len(corrected) != 6 or not corrected.isdigit():
        return None
    yy, mm, dd = int(corrected[:2]), corrected[2:4], corrected[4:]
    full_year = 1900 + yy if yy > 30 else 2000 + yy
    return f"{full_year}-{mm}-{dd}"


def _parse_names(names_field: str) -> tuple[Optional[str], Optional[str]]:
    """Split MRZ name field (<<-separated) into surname, given_names."""
    cleaned = names_field.replace("<", " ").strip()
    # double-space marks the surname/given split
    if "  " in cleaned:
        parts = cleaned.split("  ", 1)
        surname = parts[0].strip()
        given = parts[1].strip() if len(parts) > 1 else None
        return surname, given
    return cleaned, None


def _parse_td3(line1: str, line2: str) -> MrzData:
    """TD3: 2 × 44 chars (passports)."""
    data = MrzData()
    try:
        surname, given = _parse_names(line1[5:44])
        data.surname = surname
        data.given_names = given
        data.full_name = f"{given} {surname}" if given else surname

        doc_num_raw = line2[0:9].replace("<", "").strip()
        data.document_number = doc_num_raw or None
        nat_raw = line2[10:13].replace("<", "").strip()
        data.nationality = fix_nationality_code(nat_raw) or None
        data.date_of_birth = _yymmdd_to_iso(line2[13:19])
        data.sex = line2[20] if line2[20] in ("M", "F") else None
        data.expiry_date = _yymmdd_to_iso(line2[21:27])
        pn = line2[28:42].replace("<", "").strip()
        data.personal_number = pn or None
        data.valid = True
    except Exception:
        pass
    return data


def _parse_td3_line2_only(line2: str) -> MrzData:
    """
    Parse only MRZ TD3 line 2 when line 1 is missing or too corrupted.
    Extracts: document_number, nationality, DOB, sex, expiry, personal_number.
    Cannot extract names (those are on line 1).
    """
    data = MrzData()
    try:
        doc_num_raw = line2[0:9].replace("<", "").strip()
        data.document_number = doc_num_raw or None
        nat_raw = line2[10:13].replace("<", "").strip()
        data.nationality = fix_nationality_code(nat_raw) or None
        data.date_of_birth = _yymmdd_to_iso(line2[13:19])
        data.sex = line2[20] if line2[20] in ("M", "F") else None
        data.expiry_date = _yymmdd_to_iso(line2[21:27])
        pn = line2[28:42].replace("<", "").strip()
        data.personal_number = pn or None
        data.valid = True
    except Exception:
        pass
    return data


def _looks_like_td3_line2(line: str) -> bool:
    """
    Heuristic: TD3 line 2 starts with doc-number (alphanumeric), has
    a sex indicator (M/F) around position 20, and has << filler at the end.
    """
    if len(line) != 44:
        return False
    # Position 20 should be M or F (sex)
    if line[20] not in ("M", "F"):
        return False
    # Should end with some < chars
    if "<" not in line[30:]:
        return False
    return True


def _looks_like_td3_line1(line: str) -> bool:
    """
    Heuristic: TD3 line 1 starts with P< or a doc type char + <.
    Allow shorter lines (OCR truncation).
    """
    if len(line) < 20:
        return False
    if len(line) > 44:
        return False
    # First char is doc type (P, I, A, C), second is <
    if line[1] == "<" and line[0] in "PIAC":
        return True
    return False


def _parse_td1(line1: str, line2: str, line3: str) -> MrzData:
    """TD1: 3 × 30 chars (ID cards)."""
    data = MrzData()
    try:
        data.document_number = line1[5:14].replace("<", "").strip() or None
        data.date_of_birth = _yymmdd_to_iso(line2[0:6])
        data.sex = line2[7] if line2[7] in ("M", "F") else None
        data.expiry_date = _yymmdd_to_iso(line2[8:14])
        nat_raw = line2[15:18].replace("<", "").strip()
        data.nationality = fix_nationality_code(nat_raw) or None

        surname, given = _parse_names(line3)
        data.surname = surname
        data.given_names = given
        data.full_name = f"{given} {surname}" if given else surname
        data.valid = True
    except Exception:
        pass
    return data


def find_mrz(texts: list[str]) -> Optional[MrzData]:
    """
    Scan OCR lines for MRZ sequences and parse the first valid one found.

    Handles:
    - Full TD3 (2 × 44 chars)
    - Full TD1 (3 × 30 chars)
    - Partial TD3: line 1 truncated but line 2 intact (44 chars)
    - Partial TD3: single 44-char line identified as line 2
    """
    candidates = [t.strip() for t in texts if _MRZ_RE.match(t.strip())]

    # TD3: two 44-char lines
    td3 = [c for c in candidates if len(c) == 44]
    if len(td3) >= 2:
        return _parse_td3(td3[0], td3[1])

    # TD1: three 30-char lines
    td1 = [c for c in candidates if len(c) == 30]
    if len(td1) >= 3:
        return _parse_td1(td1[0], td1[1], td1[2])

    # --- Partial MRZ recovery ---

    # Case A: one line is 44 chars (line 2), another is shorter (truncated line 1)
    if len(candidates) >= 2:
        # Try to identify which is line 1 and which is line 2
        for i, a in enumerate(candidates):
            for j, b in enumerate(candidates):
                if i == j:
                    continue
                if _looks_like_td3_line1(a) and _looks_like_td3_line2(b):
                    # a = line 1 (possibly truncated), b = line 2
                    padded_a = a.ljust(44, "<")[:44]
                    return _parse_td3(padded_a, b)

        # Fallback: first two candidates, pad shorter one
        a, b = candidates[0], candidates[1]
        if len(a) >= 20 and len(b) >= 20:
            return _parse_td3(a.ljust(44, "<")[:44], b.ljust(44, "<")[:44])

    # Case B: single 44-char line — try as line 2 (most valuable data)
    if len(td3) == 1 and _looks_like_td3_line2(td3[0]):
        # Check if any other candidate looks like a truncated line 1
        line1_candidates = [c for c in candidates if c != td3[0] and _looks_like_td3_line1(c)]
        if line1_candidates:
            padded = line1_candidates[0].ljust(44, "<")[:44]
            return _parse_td3(padded, td3[0])
        else:
            # No line 1 available — extract what we can from line 2 alone
            return _parse_td3_line2_only(td3[0])

    return None
