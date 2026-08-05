# Intact ID — PaddleOCR Service

Document OCR microservice for the Intact ID KYC platform. Extracts structured identity fields (name, date of birth, ID number, nationality, dates) from uploaded document images using PaddleOCR, with intelligent country detection and document type classification.

**Stack:** Python 3.10 · FastAPI · PaddleOCR 2.7.3 · PaddlePaddle 2.6.2 · OpenCV  
**Port:** `8000`  
**Health:** `GET /health`  
**API Docs:** `GET /docs` (Swagger UI)

---
n2smIT64nTUB7hDeek8F7
069e9cf8-bb06-4244-b2d2-59092ca4fcdf
## Table of Contents

1. [Architecture](#architecture)
2. [Project Structure](#project-structure)
3. [API Endpoints](#api-endpoints)
4. [Authentication](#authentication)
5. [Extraction Pipeline](#extraction-pipeline)
6. [Document Classification](#document-classification)
7. [Country Detection](#country-detection)
8. [MRZ Parsing](#mrz-parsing)
9. [Field Extractors](#field-extractors)
10. [Country Registry (documents.yaml)](#country-registry-documentsyaml)
11. [Date Parsing](#date-parsing)
12. [OCR Error Corrections](#ocr-error-corrections)
13. [Response Schema](#response-schema)
14. [Error Handling](#error-handling)
15. [Configuration](#configuration)
16. [Running Locally](#running-locally)
17. [Docker](#docker)
18. [CI/CD](#cicd)
19. [Performance](#performance)
20. [Production Checklist](#production-checklist)

---

## Architecture

```
                  Auth Server (Spring Boot)
                         │
             X-API-Key + X-API-Secret headers
             + document image (multipart)
                         │
             ┌───────────▼────────────┐
             │    PaddleOCR Service   │
             │    FastAPI / Port 8000 │
             │                        │
             │  ┌──────────────────┐  │
             │  │ verify_api_key   │  │
             │  └────────┬─────────┘  │
             │           │             │
             │  ┌────────▼─────────┐  │
             │  │  POST /ocr       │  │
             │  │  POST /ocr/      │  │
             │  │       extract    │  │
             │  └────────┬─────────┘  │
             │           │             │
             │  ┌────────▼─────────┐  │
             │  │ PaddleOcrService │  │
             │  │ asyncio.to_thread│  │
             │  └────────┬─────────┘  │
             │           │             │
             │  ┌────────▼─────────┐  │
             │  │  PaddleOCR.ocr() │  │
             │  │  (CPU-bound)     │  │
             │  └────────┬─────────┘  │
             │           │             │
             │  ┌────────▼─────────┐  │
             │  │ extract_document │  │
             │  │  ├ detect_country│  │
             │  │  ├ classify()    │  │
             │  │  └ Extractor     │  │
             │  └──────────────────┘  │
             └────────────────────────┘
```

---

## Project Structure

```
src/paddleocr_service/
├── main.py                        # FastAPI app, routes
├── models.py                      # Pydantic response schemas
├── config.py                      # Settings (env vars via Pydantic)
├── service.py                     # PaddleOcrService (wraps PaddleOCR)
├── security.py                    # API key/secret header validation
└── extractor/
    ├── __init__.py                # extract_document() entry point
    ├── classifier.py              # Document type classification
    ├── country_registry.py        # Country detection + label lookups
    ├── documents.yaml             # Country-specific doc definitions
    ├── labels.py                  # Global multilingual label vocabularies
    ├── date_utils.py              # Date parsing + text normalization
    ├── ocr_corrections.py         # MRZ char confusion fixes + nationality map
    ├── mrz.py                     # TD1 (ID cards) + TD3 (passports) MRZ parser
    ├── national_id.py             # NationalIdExtractor
    ├── passport.py                # PassportExtractor (MRZ-first → label → positional)
    ├── drivers_license.py         # DriversLicenseExtractor
    └── residence_permit.py        # ResidencePermitExtractor (delegates to NationalId)

scripts/
└── start.sh                       # Uvicorn startup

tests/
├── test_extractor.py              # (placeholder)
└── verify_drc_passport.py         # Manual DRC passport verification script
```

---

## API Endpoints

### GET `/health`

Health check — no authentication required.

```json
{ "status": "ok" }
```

---

### POST `/ocr`

Raw PaddleOCR extraction — returns all detected text lines with bounding boxes. No field classification.

**Auth:** Required (`X-API-Key`, `X-API-Secret`)  
**Content-Type:** `multipart/form-data`

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `file` | File | Yes | `image/*` only, max `MAX_FILE_SIZE_MB` |

**Response:**

```json
{
  "line_count": 17,
  "text": "REPUBLIC OF KENYA\nNATIONAL IDENTITY CARD\nFULL NAME\nFRANCIS MWANGI\n...",
  "lines": [
    {
      "text": "REPUBLIC OF KENYA",
      "confidence": 0.987,
      "box": [[10,5], [320,5], [320,28], [10,28]]
    }
  ]
}
```

---

### POST `/ocr/extract`

Full pipeline — OCR + country detection + document classification + field extraction.

**Auth:** Required  
**Content-Type:** `multipart/form-data`

| Field | Type | Required |
|-------|------|----------|
| `file` | File | Yes |

**Response:** See [Response Schema](#response-schema).

**Pipeline:**
1. Image → PaddleOCR → raw text lines
2. Detect country from OCR text (MRZ, ISO codes, nationality words, fuzzy keywords)
3. Classify document type (MRZ signal + country-specific + global keywords)
4. Extract structured fields using country-appropriate labels and MRZ
5. Return `ExtractedDocument` with fields, confidences, and raw OCR

---

## Authentication

Two headers required on all protected endpoints:

```
X-API-Key: your_api_key
X-API-Secret: your_api_secret
```

Configured via `API_KEY` and `API_SECRET` env vars. Missing or wrong headers return:

```json
{ "detail": "Missing X-API-Key or X-API-Secret header" }
// or
{ "detail": "Invalid API credentials" }
```

HTTP **401** in both cases.

---

## Extraction Pipeline

The full `POST /ocr/extract` pipeline in detail:

```
1. Validate file (type, size, not empty)
        ↓
2. PaddleOcrService.extract_from_bytes_async(image_bytes)
   └─ asyncio.to_thread → PaddleOCR.ocr(numpy_array, cls=True)
   └─ Normalize → list of {text, confidence, box}
        ↓
3. detect_country(texts)
   ├─ MRZ nationality field (highest priority)
   ├─ Standalone 3-letter ISO code on its own line
   ├─ Nationality word mapping (e.g. "CONGOLAISE" → "COD")
   └─ Fuzzy keyword scoring (trigram similarity, threshold 0.55)
        ↓
4. classify(texts)  →  (document_type, confidence)
   ├─ MRZ signal:  "P<" = passport +3pts, TD1 = national_id +2pts
   ├─ Country-specific keywords: +2pts each
   └─ Global fallback keywords: +1pt each
        ↓
5. get_extractor(document_type)
   ├─ national_id      → NationalIdExtractor
   ├─ passport         → PassportExtractor
   ├─ drivers_license  → DriversLicenseExtractor
   └─ residence_permit → ResidencePermitExtractor (→ NationalIdExtractor)
        ↓
6. extractor.extract(texts, line_confidences, country_iso3)
   ├─ Resolve labels: country-specific first, global fallback
   ├─ MRZ fields (highest confidence: 0.95–0.98)
   ├─ Label-based fields (inline, forward, backward extraction)
   └─ Heuristic fallbacks (pattern matching, positional)
        ↓
7. overall_confidence = mean(populated field confidences)
        ↓
8. Return ExtractedDocument
```

---

## Document Classification

**`classifier.py` — `classify(texts) → (document_type, confidence)`**

### Supported Document Types

`national_id` · `passport` · `drivers_license` · `residence_permit` · `unknown`

### Scoring System (3 tiers)

| Signal | Points | Source |
|--------|--------|--------|
| MRZ `P<` prefix (TD3) | +3 | → passport |
| MRZ TD1 format | +2 | → national_id |
| Country-specific keyword match | +2 each | `documents.yaml` |
| Global keyword match | +1 each | `labels.py` |

All text is normalized before matching: lowercase, punctuation stripped, whitespace removed.

### Confidence Calculation

```python
raw_conf = best_score / max_keywords_for_type
confidence = min(max(raw_conf, 0.5), 1.0)
# Floor of 0.5 applied when type identified but with sparse keyword coverage
```

### Global Fallback Keywords (examples)

| Type | Keywords |
|------|---------|
| `passport` | passport, passeport, pasaporte, reisepass, paszport, paspoort |
| `national_id` | national id, national identity, carte nationale, cedula, kitambulisho |
| `drivers_license` | driving licence, driving license, permis de conduire, fuhrerschein |
| `residence_permit` | residence permit, alien card, titre de sejour, aufenthaltstitel |

---

## Country Detection

**`country_registry.py` — `detect_country(texts) → Optional[str]`**

Returns ISO-3166-1 alpha-3 code.

### Detection Priority

| Priority | Method | Example |
|----------|--------|---------|
| 1 (highest) | MRZ nationality field (TD1/TD3) | `COD` extracted from passport MRZ |
| 2 | Standalone 3-letter ISO code on its own line | Line containing only `KEN` |
| 3 | Nationality word mapping | `CONGOLAISE` → `COD` |
| 4 (lowest) | Fuzzy keyword scoring per country | Scores each country's keywords, picks highest |

### Fuzzy Matching

For keyword scoring, uses **trigram similarity** (Jaccard index on character trigrams):

```python
# Threshold: 0.55
# Exact match: +2 pts  |  Fuzzy match: +1 pt
```

Handles OCR typos gracefully (e.g., "NATIDNAL" still matches "NATIONAL").

### Supported Nationality Words

| Word | → ISO |
|------|-------|
| CONGOLAISE / CONGOLAIS / CONGOLESE | COD |
| KENYAN / KENYANE | KEN |
| OUGANDAISE / OUGANDAIS | UGA |
| SOUTH AFRICAN | ZAF |

### Pre-registered ISO-3166-1 Codes (83 total)

Africa: `COD KEN UGA TZA RWA BDI ZAF NGA GHA ETH CMR SEN CIV MLI AGO MOZ ZMB ZWE MWI NAM BWA LSO SWZ MDG MUS DJI ERI SOM SDN SSD TCD CAF GAB COG GNQ BEN BFA NER GIN SLE LBR GMB CPV MRT`

Others: `FRA GBR USA BEL DEU IND CHN PAK` + more

---

## MRZ Parsing

**`mrz.py` — Parses ISO 9303 MRZ zones**

### Supported Formats

| Format | Document | Lines | Chars/line |
|--------|----------|-------|------------|
| TD3 | Passports | 2 | 44 |
| TD1 | ID cards | 3 | 30 |

### Partial MRZ Recovery

PaddleOCR sometimes truncates MRZ lines. The parser recovers gracefully:

| Situation | Recovery |
|-----------|---------|
| Both lines 44 chars | Full parse |
| Line 1 truncated, line 2 intact | Pad line 1 with `<`, parse line 2 for dates/ID |
| Single 44-char line | Parse line 2 only (no names) |
| Candidate lines (≥20 chars) | Attempt TD3 with padding |

### TD3 Field Layout (Passports)

```
Line 1: [0]Type [1]Subtype [2-4]Country [5-43]Names(<<separated)
Line 2: [0-8]DocNumber [10-12]Nationality [13-18]DOB [20]Sex
        [21-26]Expiry [28-41]PersonalNumber
```

### TD1 Field Layout (ID Cards)

```
Line 1: [5-13]DocNumber
Line 2: [0-5]DOB [7]Sex [8-13]Expiry [15-17]Nationality
Line 3: Names
```

### MrzData Fields

```python
@dataclass
class MrzData:
    surname: Optional[str]
    given_names: Optional[str]
    full_name: Optional[str]
    document_number: Optional[str]
    nationality: Optional[str]     # ISO-3166-1 alpha-3
    date_of_birth: Optional[str]   # ISO YYYY-MM-DD
    sex: Optional[str]             # "M" or "F"
    expiry_date: Optional[str]     # ISO YYYY-MM-DD
    personal_number: Optional[str]
    valid: bool
```

MRZ fields carry confidence **0.95–0.98** (highest in the system).

---

## Field Extractors

All extractors follow the same interface:

```python
extractor.extract(texts, line_conf, country) → (DocumentFields, FieldConfidence)
```

### Label Resolution

```
country-specific labels  ← checked first (higher priority)
        +
global fallback labels   ← appended as safety net
```

### Value Extraction Patterns

**Inline** — label and value on the same line:
```
"NomMBAYA"  →  label="Nom", value="MBAYA"
```

**Forward** — value on the next line after the label:
```
Line i:   "FULL NAME"
Line i+1: "FRANCIS MWANGI"  →  value="FRANCIS MWANGI"
```

**Backward** — value on the previous line (side-by-side column layouts):
```
Line i-1: "MWANGI"
Line i:   "SURNAME"  →  value="MWANGI"
```

---

### NationalIdExtractor

**Strategy (in order):**
1. **MRZ** (TD1) → highest confidence (0.95–0.98)
2. **Label-based** — inline, forward, backward search
3. **Fallback heuristics** — ID number regex, name-like line scan

| Field | Primary Source | Confidence |
|-------|----------------|------------|
| id_number | Label + regex `[A-Z0-9]{5,20}` (≥4 digits) | 0.7–0.98 |
| full_name | Surname + given_names merge | 0.6–0.95 |
| surname | Surname label + next-line | 0.75–0.9 |
| given_names | Given label + next-line | 0.75–0.9 |
| date_of_birth | DOB label + date parser | 0.6–0.95 |
| sex | Sex label + M/F regex | 0.95 |
| nationality | Nationality label + `[A-Z]+` word | 0.8–0.85 |
| date_of_issue | Issue label + date parser | 0.85–0.95 |
| place_of_issue | POI label + next non-date line | 0.8 |
| place_of_birth | POB label + next line | 0.8 |
| district_of_birth | District label + next line | 0.8 |

---

### PassportExtractor

**Strategy (3-tier):**

1. **MRZ** (TD3) — always attempted first
   - If MRZ line 1 truncated → names get confidence 0.4 (allows positional override)
2. **Label-based** — visual zone labels
3. **Positional state machine** — exploits standard passport layout when no labels

#### Positional State Machine

Tracks expected document order through states: `names → post_names → post_nationality → done`

```
Header (country name, "PASSPORT")  →  skip
Passport number regex              →  skip
1st date encountered               →  date_of_birth
Nationality word                   →  nationality; transition state
2nd date                           →  date_of_issue
3rd date                           →  expiry_date
Name lines (state=names)           →  surname, then given_names
Post-nationality names             →  place_of_birth
```

Positional values get confidence ≤ 0.55 (flagged as uncertain).

| Field | MRZ | Label | Positional | Max Conf |
|-------|-----|-------|------------|---------|
| id_number | Line 2 [0-8] | Passport no regex | — | 0.98 |
| surname | Line 1 pre-`<<` | Surname label | 1st name line | 0.95 |
| given_names | Line 1 post-`<<` | Given label | 2nd+ name lines | 0.95 |
| date_of_birth | Line 2 [13-18] | DOB label | 1st date | 0.98 |
| expiry_date | Line 2 [21-26] | Expiry label | 3rd date | 0.98 |
| date_of_issue | — | Issue label | 2nd date | 0.98 |
| nationality | Line 2 [10-12] | Nationality label | Nationality word | 0.95 |
| sex | Line 2 [20] | Sex label | — | 0.98 |

**Name validation** — excludes header words from name extraction:  
`republic, republique, democratic, democratique, passport, passeport, congo, kenya, ...`

---

### DriversLicenseExtractor

No MRZ on driver's licences — label-based only with DL-specific label set.

**DL-specific ID labels:**
`licence no, license no, dl no, driver no, permit no, permis no, numero de permis, fuhrerscheinnummer`

**Dual label matching:** When both `SURNAME` and `GIVEN NAMES` appear on the same line, `GIVEN NAMES` wins (more specific).

| Field | Confidence |
|-------|------------|
| id_number | 0.85–0.9 |
| date_of_birth | 0.9 |
| expiry_date | 0.9 |
| date_of_issue | 0.85 |
| sex | 0.95 |
| nationality | 0.8–0.85 |

---

### ResidencePermitExtractor

Delegates entirely to `NationalIdExtractor` — residence permits share the same field structure and label vocabularies as national IDs.

---

## Country Registry (documents.yaml)

Defines country-specific document keywords and field label vocabularies. Loaded at import time into a singleton registry.

### Structure

```yaml
countries:
  KEN:
    name: Kenya
    languages: [en, sw]
    documents:
      national_id:
        classifier_keywords:
          - "NATIONAL IDENTITY CARD"
          - "KITAMBULISHO CHA TAIFA"
          - "JAMHURI YA KENYA"
        fields:
          id_number:
            - "ID. NO."
            - "ID NO"
            - "NAMBARI YA KITAMBULISHO"
          full_name:
            - "FULL NAME"
            - "JINA KAMILI"
          date_of_birth:
            - "DATE OF BIRTH"
            - "TAREHE YA KUZALIWA"
          # ... more fields
```

### Currently Supported Countries

| ISO | Country | Documents | Languages |
|-----|---------|-----------|-----------|
| KEN | Kenya | national_id, passport, drivers_license, residence_permit | English, Swahili |
| COD | DR Congo | national_id, passport, drivers_license | French |

**Adding a new country:** Copy the YAML template, fill in ISO-3166-1 alpha-3, name, language codes, document types, classifier keywords, and field label variants. Matching is case-insensitive and punctuation-normalized.

### Field Names (must match `DocumentFields` attributes exactly)

`full_name` · `surname` · `given_names` · `id_number` · `date_of_birth` · `sex` · `nationality` · `expiry_date` · `date_of_issue` · `place_of_birth` · `district_of_birth` · `place_of_issue`

### Matching Rules

All labels are pre-normalized at load time:

| Input | Normalized |
|-------|-----------|
| `"DATE OF BIRTH"` | `dateofbirth` |
| `"Date-Of-Birth"` | `dateofbirth` |
| `"DATE.OF.BIRTH"` | `dateofbirth` |

---

## Date Parsing

**`date_utils.py`**

### Supported Formats

| Format | Example | Output |
|--------|---------|--------|
| `DD MMM YYYY` | `15 JAN 1990` | `1990-01-15` |
| `D[D]/M[M]/YYYY` | `4/3/2004` | `2004-03-04` |
| `YYYY/M[M]/D[D]` | `2004-03-04` | `2004-03-04` |
| `D[D]/M[M]/YY` | `4/3/04` | `2004-03-04` |
| `YYMMDD` (MRZ) | `900115` | `1990-01-15` |

**Separators:** `/`, `-`, `.`  
**2-digit year:** YY ≤ 30 → 20YY, YY > 30 → 19YY

### Key Functions

| Function | Returns | Purpose |
|----------|---------|---------|
| `parse_date(text)` | `Optional[str]` | Find first date in text → ISO YYYY-MM-DD |
| `extract_date_and_remainder(text)` | `(date, remainder)` | Split `"04-03-2004Goma"` → `("2004-03-04", "Goma")` |
| `norm_text(s)` | `str` | Lowercase + strip punctuation/spaces — used everywhere for label matching |

---

## OCR Error Corrections

**`ocr_corrections.py`**

PaddleOCR commonly confuses visually similar characters in MRZ zones.

### Character Confusion Maps

**Alpha positions** (should be letters — fix digit→letter):

| OCR output | Corrected |
|-----------|-----------|
| `0` | `O` |
| `1` | `I` |
| `5` | `S` |
| `8` | `B` |

**Digit positions** (should be digits — fix letter→digit):

| OCR output | Corrected |
|-----------|-----------|
| `O` | `0` |
| `I` | `1` |
| `S` | `5` |
| `B` | `8` |

### Functions

| Function | Input | Output |
|----------|-------|--------|
| `fix_mrz_alpha(text)` | `"C0D5"` | `"CODS"` |
| `fix_mrz_digits(text)` | `"20O1"` | `"2001"` |
| `fix_nationality_code(code)` | `"C0D"` | `"COD"` |

---

## Response Schema

### `ExtractedDocument`

```json
{
  "document_type": "national_id",
  "document_type_confidence": 0.92,
  "country_iso3": "KEN",
  "fields": {
    "full_name": "FRANCIS MWANGI",
    "surname": "MWANGI",
    "given_names": "FRANCIS",
    "id_number": "12345678",
    "date_of_birth": "1990-05-15",
    "sex": "M",
    "nationality": "KENYAN",
    "expiry_date": null,
    "date_of_issue": "2015-03-10",
    "place_of_birth": "NAIROBI",
    "district_of_birth": null,
    "place_of_issue": null
  },
  "field_confidence": {
    "full_name": 0.92,
    "surname": 0.88,
    "given_names": 0.88,
    "id_number": 0.95,
    "date_of_birth": 0.91,
    "sex": 0.95,
    "nationality": 0.82,
    "expiry_date": null,
    "date_of_issue": 0.87,
    "place_of_birth": 0.80,
    "district_of_birth": null,
    "place_of_issue": null
  },
  "overall_confidence": 0.89,
  "raw_text": "REPUBLIC OF KENYA\nNATIONAL IDENTITY CARD\n...",
  "line_count": 17,
  "lines": [
    {
      "text": "REPUBLIC OF KENYA",
      "confidence": 0.987,
      "box": [[10, 5], [320, 5], [320, 28], [10, 28]]
    }
  ]
}
```

### Confidence Scale

| Range | Meaning |
|-------|---------|
| 0.95–1.0 | MRZ-extracted (highest reliability) |
| 0.85–0.94 | Label-based with clear match |
| 0.6–0.84 | Label-based with fallback or ambiguous match |
| 0.5–0.59 | Positional heuristic (uncertain) |
| `null` | Field not found |

---

## Error Handling

| Status | Cause | Response |
|--------|-------|----------|
| 200 | Success | `ExtractedDocument` or raw OCR result |
| 400 | Non-image file | `{"detail": "Only image uploads are supported"}` |
| 400 | File too large | `{"detail": "File exceeds maximum size of 10MB"}` |
| 400 | Empty file | `{"detail": "Uploaded file is empty"}` |
| 401 | Missing headers | `{"detail": "Missing X-API-Key or X-API-Secret header"}` |
| 401 | Wrong credentials | `{"detail": "Invalid API credentials"}` |
| 422 | Malformed form | FastAPI validation error |
| 500 | Unexpected error | FastAPI error handler |

---

## Configuration

All settings via environment variables (Pydantic Settings, reads `.env` automatically).

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEY` | `"test_ocr_key"` | **Change in production** |
| `API_SECRET` | `"test_ocr_secret"` | **Change in production** |
| `OCR_LANG` | `"en"` | PaddleOCR language code (`en`, `ch`, `fr`, etc.) |
| `USE_ANGLE_CLS` | `true` | Enable orientation classification (corrects rotated text) |
| `MAX_FILE_SIZE_MB` | `10` | Max upload size in MB |

### `.env.example`

```env
API_KEY=your_ocr_api_key
API_SECRET=your_ocr_api_secret
OCR_LANG=en
USE_ANGLE_CLS=true
MAX_FILE_SIZE_MB=10
```

---

## Running Locally

### Prerequisites

- Python **3.10 exactly** — `pyproject.toml` pins `>=3.7,<3.11`. PaddlePaddle is incompatible with 3.11+
- 4GB+ RAM
- 3GB+ disk (model cache)

```bash
cd paddleocr-service

# Create virtualenv with Python 3.10
python3.10 -m venv venv
source venv/bin/activate

# Install
pip install --upgrade pip "setuptools>=68" wheel
pip install -e .

# Configure
cp .env.example .env

# Start
uvicorn paddleocr_service.main:app --host 0.0.0.0 --port 8000 --reload
```

> First run downloads PaddleOCR models (~500MB) to `~/.paddleocr/`. Subsequent starts are fast.

### Test the API

```bash
# Health
curl http://localhost:8000/health

# Raw OCR
curl -X POST http://localhost:8000/ocr \
  -H "X-API-Key: test_ocr_key" \
  -H "X-API-Secret: test_ocr_secret" \
  -F "file=@id_card.jpg"

# Full extraction
curl -X POST http://localhost:8000/ocr/extract \
  -H "X-API-Key: test_ocr_key" \
  -H "X-API-Secret: test_ocr_secret" \
  -F "file=@passport.jpg" | jq .
```

### Manual Verification (DRC Passport)

```bash
python tests/verify_drc_passport.py
```

Runs a hard-coded DRC passport OCR result through `extract_document()` and prints the full extraction output — useful for validating extractor changes without a real API call.

---

## Docker

```bash
# Requires shared network
docker network create app-net

# Build + start
docker compose up -d

# Logs
docker logs -f paddleocr-service

# Health
curl http://localhost:8000/health
```

### docker-compose.yml summary

| Setting | Value |
|---------|-------|
| Image | `frankmwangi8118/paddleocr-service:latest` |
| Port | `8000:8000` |
| Restart | `unless-stopped` |
| `shm_size` | **2GB** — required for PaddlePaddle tensor ops |
| Workers | 1 (single process; async I/O handles concurrency) |
| Network | `app-net` (external), aliased as `ocr-service` |
| Watchtower | Enabled (auto-updates on new image push) |

### Dockerfile (single-stage)

```
Base: python:3.10-slim
System deps: libgomp1, libglib2.0-0, libsm6, libxext6, libxrender1, libgl1
pip install: setuptools>=68, wheel, then project
CMD: ./scripts/start.sh → uvicorn
```

### `scripts/start.sh`

```bash
uvicorn paddleocr_service.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${WORKERS:-1}" \
    --log-level info
```

Single worker is intentional — PaddlePaddle model state is not safe to share across forked processes without careful setup. Concurrency comes from asyncio + `asyncio.to_thread` offloading CPU work.

---

## CI/CD

GitHub Actions workflow (`.github/workflows/docker-build.yml`):

**Trigger:** Push or PR to `main` / `master` / `develop`

| Step | Details |
|------|---------|
| Checkout | actions/checkout@v4 |
| Docker Buildx | Multi-platform build support |
| Docker Hub login | Uses `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN` secrets |
| Metadata extract | Tags: `latest`, short SHA, branch name |
| Build & push | Pushes on push events only; uses GitHub Actions cache |

**Published tags:**
- `frankmwangi8118/paddleocr-service:latest`
- `frankmwangi8118/paddleocr-service:{sha}`
- `frankmwangi8118/paddleocr-service:{branch}`

---

## Performance

### Throughput

| Scenario | Rate |
|----------|------|
| CPU-only, single image | ~1–3 images/min |
| Multiple concurrent requests | Queue behind single OCR thread |
| With `asyncio.to_thread` | Event loop stays responsive while OCR runs |

### Bottleneck

PaddleOCR inference is CPU-bound. Scaling options:
- **Horizontal:** Multiple container instances behind a load balancer
- **GPU:** Replace `paddlepaddle` with `paddlepaddle-gpu` (not in current setup)
- **Image pre-processing:** Crop to document region before uploading → smaller image → faster OCR

### Memory

| Component | Size |
|-----------|------|
| PaddleOCR model cache | ~1GB |
| Per-request buffers | ~50–200MB |
| Docker `shm_size` | 2GB required |
| Recommended host RAM | ≥4GB |

---

## Production Checklist

- [ ] Set strong `API_KEY` and `API_SECRET` (not the defaults)
- [ ] Ensure Python 3.10 — do **not** use 3.11+
- [ ] Docker `shm_size: 2gb` — mandatory for PaddlePaddle
- [ ] Host RAM ≥ 4GB
- [ ] Disk ≥ 3GB for model cache (`~/.paddleocr/`)
- [ ] Set `USE_ANGLE_CLS=true` for rotated document handling
- [ ] Set `OCR_LANG=en` (or appropriate language for your documents)
- [ ] Implement HTTPS via reverse proxy (nginx / Traefik)
- [ ] Ship logs to centralised aggregator
- [ ] Monitor `/health` endpoint with uptime tooling
- [ ] Add new countries to `documents.yaml` as needed
- [ ] Run `tests/verify_drc_passport.py` after extractor changes

---

## Contact

**Email:** contact@intact-io.com  
**Documentation:** https://docs.intact-io.com

&copy; 2026 Intact ID Inc. — Laws of Kenya
