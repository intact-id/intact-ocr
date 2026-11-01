"""Field extraction from OCR'd text lines (no OCR model needed)."""
from paddleocr_service.extractor.national_id import NationalIdExtractor, _looks_like_name


def full_name(texts):
    fields, _ = NationalIdExtractor().extract(texts, {}, "KEN")
    return fields.full_name


# Line structure as PaddleOCR returned it for real Kenyan ID captures; personal values replaced.
KEN_FULL_NAMES_LABEL = [
    "REPUBLIC OF KENYA", "JAMHURIYA KENYA", "12345678", "900000001", "DNEE", "SERIAL NUMBE",
    "FULL NAMES", "JANE WANJIRU OTIENO", "DATE OFBIRTH", "01.01.1990", "SEX", "MALE",
]
KEN_MERGED_HEADER = [
    "REPUBLICOF KENYA", "JAMHURIYA KENYA", "12345678", "900000001", "DNUMBER", "SERIAL NUMBER",
    "FULL NAMES", "JANE WANJIRU OTIENO", "DATE OFBIRTH", "01.01.1990",
]
KEN_GARBLED_LABEL = [
    "JAMHURIYAKENYA", "REPUBLIC OFKENYA", "900000001", "12345678", "SERANN", "IDNUMBER",
    "FRLNAVES", "JANE WANJIRU OTIENO", "DATE OFBIRTH", "01.01.1990",
]


def test_plural_full_names_label_reads_the_line_below():
    # "FULL NAMES" used to yield the inline value "S", skip the next line and fall back to the
    # first name-looking line on the card: the header "JAMHURIYA KENYA".
    assert full_name(KEN_FULL_NAMES_LABEL) == "JANE WANJIRU OTIENO"


def test_merged_header_words_are_not_a_name():
    assert full_name(KEN_MERGED_HEADER) == "JANE WANJIRU OTIENO"


def test_garbled_label_still_finds_the_name():
    assert full_name(KEN_GARBLED_LABEL) == "JANE WANJIRU OTIENO"


def test_card_headers_never_look_like_names():
    for header in ["REPUBLIC OF KENYA", "REPUBLICOF KENYA", "JAMHURIYA KENYA", "JAMHURI YA KENYA"]:
        assert not _looks_like_name(header), header
    assert _looks_like_name("JANE WANJIRU OTIENO")
