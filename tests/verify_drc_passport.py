"""
Verification script: feed the real DRC passport OCR JSON through extract_document().
"""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from paddleocr_service.extractor import extract_document

OCR_RESULT = {
    "line_count": 17,
    "text": "REPUSLIQUE DEMOCRATIQUE_OU CONGO-DEMOCRATIC REPUSLIC OF THE COMGO\nPASSEPORTPASSPORT\nCOD\nOP1551652\nPANKWA\nLUSI\nJOEL\n16/01/1903\nCONGOLAISE\nS7 Natioe\nKINSHASA\n18/12/2023\n110808792\n17/12/2028\nMINAFFET\nPCODPANKWA<JOEL<LUBI<<<<\nOP15616527C0D9301168M2812173110808792<<<<<24",
    "lines": [
        {"text": "REPUSLIQUE DEMOCRATIQUE_OU CONGO-DEMOCRATIC REPUSLIC OF THE COMGO", "confidence": 0.897, "box": []},
        {"text": "PASSEPORTPASSPORT", "confidence": 0.975, "box": []},
        {"text": "COD", "confidence": 0.973, "box": []},
        {"text": "OP1551652", "confidence": 0.964, "box": []},
        {"text": "PANKWA", "confidence": 0.997, "box": []},
        {"text": "LUSI", "confidence": 0.973, "box": []},
        {"text": "JOEL", "confidence": 0.998, "box": []},
        {"text": "16/01/1903", "confidence": 0.990, "box": []},
        {"text": "CONGOLAISE", "confidence": 0.998, "box": []},
        {"text": "S7 Natioe", "confidence": 0.586, "box": []},
        {"text": "KINSHASA", "confidence": 0.964, "box": []},
        {"text": "18/12/2023", "confidence": 0.995, "box": []},
        {"text": "110808792", "confidence": 0.962, "box": []},
        {"text": "17/12/2028", "confidence": 0.988, "box": []},
        {"text": "MINAFFET", "confidence": 0.985, "box": []},
        {"text": "PCODPANKWA<JOEL<LUBI<<<<", "confidence": 0.891, "box": []},
        {"text": "OP15616527C0D9301168M2812173110808792<<<<<24", "confidence": 0.937, "box": []},
    ],
}

result = extract_document(OCR_RESULT)

print("=" * 60)
print("EXTRACTION RESULT")
print("=" * 60)
print(f"document_type:       {result.document_type}")
print(f"type_confidence:     {result.document_type_confidence}")
print(f"country_iso3:        {result.country_iso3}")
print(f"overall_confidence:  {result.overall_confidence}")
print()
print("--- FIELDS ---")
for field, value in result.fields.model_dump().items():
    marker = "✓" if value else "✗"
    print(f"  {marker} {field:20s} = {value}")
print()
print("--- FIELD CONFIDENCE ---")
for field, value in result.field_confidence.model_dump().items():
    if value is not None:
        print(f"  {field:20s} = {value}")
