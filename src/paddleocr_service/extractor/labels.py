"""
International label vocabulary used by all extractors.
Each tuple contains label variants in English + common translations.
All values are lowercased; matching is done on norm_text() of the OCR line.
"""
from __future__ import annotations

from .date_utils import norm_text

# fmt: off
SURNAME_LABELS = (
    "surname", "last name", "family name", "nom", "apellido",
    "nachname", "sobrenome", "cognome", "jina la ukoo",
    "nom de famille",
)
GIVEN_NAME_LABELS = (
    "given names", "given name", "first name", "first names",
    "other names", "forename", "prenoms", "prenom", "nombre",
    "vorname", "nome", "majina",
)
FULL_NAME_LABELS = (
    "full name", "full names", "name", "names",
    "jina kamili", "nom complet", "nombre completo",
)
DOB_LABELS = (
    "date of birth", "birth date", "d.o.b", "dob", "born",
    "date de naissance", "fecha de nacimiento", "geburtsdatum",
    "data de nascimento", "tarehe ya kuzaliwa",
    # single-word triggers (French/Portuguese/German docs)
    "naissance", "nascimento", "geburt",
    # bilingual label variants (e.g. DRC docs)
    "date & place of birth", "date and place of birth",
    "date et lieu de naissance",
)
EXPIRY_LABELS = (
    "date of expiry", "expiry date", "expiry", "expires",
    "valid until", "valid to", "expiration date", "expiration",
    "date d expiration", "fecha de vencimiento", "ablaufdatum",
    "data de validade", "tarehe ya kumalizika",
)
ISSUE_DATE_LABELS = (
    "date of issue", "issue date", "issued", "date issued",
    "date de delivrance", "lieu et date de delivrance",
    "date & lieu de delivrance", "date delivrance",
    "fecha de expedicion", "ausstellungsdatum",
    "tarehe ya kutolewa",
)
NATIONALITY_LABELS = (
    "nationality", "nationalite", "nationalidad", "staatsangehorigkeit",
    "nacionalidade", "nazionalita", "utaifa",
)
SEX_LABELS = (
    "sex", "gender", "sexe", "sexo", "geschlecht",
    "genere", "jinsia",
)
ID_NUMBER_LABELS = (
    "id number", "id no", "id. no", "identity number",
    "identification number", "document number", "doc no",
    "document no", "national id number", "card number",
    "nambari ya kitambulisho", "numero de documento",
    "numero d identite", "ausweisnummer",
)
PLACE_OF_BIRTH_LABELS = (
    "place of birth", "birthplace", "lieu de naissance",
    "lugar de nacimiento", "geburtsort", "mahali alipozaliwa",
)
PLACE_OF_ISSUE_LABELS = (
    "place of issue", "issued at", "issued by",
    "lieu de delivrance", "lugar de expedicion",
    "mahali pa kutolewa",
)
DISTRICT_LABELS = (
    "district of birth", "district", "county", "wilaya ya kuzaliwa",
)
# fmt: on

# Pre-normalize for fast matching
def _norm_tuple(labels: tuple[str, ...]) -> list[str]:
    return [norm_text(l) for l in labels]

N_SURNAME          = _norm_tuple(SURNAME_LABELS)
N_GIVEN_NAME       = _norm_tuple(GIVEN_NAME_LABELS)
N_FULL_NAME        = _norm_tuple(FULL_NAME_LABELS)
N_DOB              = _norm_tuple(DOB_LABELS)
N_EXPIRY           = _norm_tuple(EXPIRY_LABELS)
N_ISSUE_DATE       = _norm_tuple(ISSUE_DATE_LABELS)
N_NATIONALITY      = _norm_tuple(NATIONALITY_LABELS)
N_SEX              = _norm_tuple(SEX_LABELS)
N_ID_NUMBER        = _norm_tuple(ID_NUMBER_LABELS)
N_PLACE_OF_BIRTH   = _norm_tuple(PLACE_OF_BIRTH_LABELS)
N_PLACE_OF_ISSUE   = _norm_tuple(PLACE_OF_ISSUE_LABELS)
N_DISTRICT         = _norm_tuple(DISTRICT_LABELS)
