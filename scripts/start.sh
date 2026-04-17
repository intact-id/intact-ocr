#!/bin/bash
set -e

PORT="${PORT:-8000}"
WORKERS="${WORKERS:-1}"

echo "Starting PaddleOCR Service on port ${PORT} with ${WORKERS} worker(s)..."

exec uvicorn paddleocr_service.main:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --workers "${WORKERS}" \
    --log-level info
