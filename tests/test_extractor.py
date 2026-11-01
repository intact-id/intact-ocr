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


# Kenyan ID, two columns: serial number top-left, ID number top-right. OCR interleaves the
# columns, so in reading order the serial (900000001) is the number nearest the ID label.
# Positions and structure from a real capture; personal values replaced.
KEN_TWO_COLUMN_LINES = [
    {'text': 'REPUBLIC OF KENYA', 'confidence': 0.955, 'box': [[552, 83], [939, 52], [941, 84], [554, 114]]},
    {'text': 'JAMHURIYA KENYA', 'confidence': 0.962, 'box': [[69, 111], [404, 94], [405, 124], [71, 141]]},
    {'text': '12345678', 'confidence': 0.998, 'box': [[662, 131], [827, 122], [829, 157], [664, 166]]},
    {'text': '900000001', 'confidence': 0.994, 'box': [[208, 155], [374, 147], [375, 178], [209, 186]]},
    {'text': 'IDNUMBER', 'confidence': 0.975, 'box': [[542, 156], [641, 148], [643, 167], [543, 175]]},
    {'text': 'SERIAL NUMBER:', 'confidence': 0.939, 'box': [[65, 175], [202, 166], [203, 187], [66, 195]]},
    {'text': 'FULL NAMES', 'confidence': 0.952, 'box': [[65, 210], [160, 204], [161, 220], [66, 225]]},
    {'text': 'JANE WANJIRU OTIENO', 'confidence': 0.941, 'box': [[64, 229], [486, 211], [488, 240], [65, 258]]},
    {'text': 'DATE OFBIRTH', 'confidence': 0.922, 'box': [[354, 251], [482, 246], [483, 265], [355, 270]]},
    {'text': '01.01.1990', 'confidence': 0.989, 'box': [[354, 275], [510, 270], [511, 297], [355, 302]]},
    {'text': 'SEX', 'confidence': 0.996, 'box': [[356, 308], [390, 308], [390, 326], [356, 326]]},
    {'text': 'MALE', 'confidence': 0.999, 'box': [[351, 332], [418, 329], [419, 359], [352, 361]]},
    {'text': 'DISTRICT OF BIRTH', 'confidence': 0.933, 'box': [[352, 363], [512, 360], [512, 380], [352, 384]]},
    {'text': 'NAIROBI', 'confidence': 0.952, 'box': [[352, 391], [568, 385], [568, 412], [353, 418]]},
    {'text': 'PLACE OF ISSUE', 'confidence': 0.943, 'box': [[351, 423], [488, 421], [488, 440], [351, 442]]},
    {'text': 'NAIROBI', 'confidence': 0.961, 'box': [[351, 449], [548, 445], [548, 472], [351, 476]]},
    {'text': 'DATE OF ISSUE', 'confidence': 0.936, 'box': [[351, 483], [477, 480], [477, 499], [351, 502]]},
    {'text': '02.02.2015', 'confidence': 0.993, 'box': [[351, 509], [506, 506], [506, 534], [351, 537]]},
    {'text': "HOLDER'S SIGN", 'confidence': 0.959, 'box': [[350, 576], [481, 576], [481, 592], [350, 592]]},
]


def test_id_number_is_the_one_next_to_its_label_not_the_serial():
    from paddleocr_service.extractor import extract_document

    doc = extract_document({"lines": KEN_TWO_COLUMN_LINES, "text": "", "line_count": len(KEN_TWO_COLUMN_LINES)})
    assert doc.fields.id_number == "12345678"
    assert doc.fields.full_name == "JANE WANJIRU OTIENO"
