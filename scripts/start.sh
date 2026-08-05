#!/bin/bash
set -e

PORT="${PORT:-8000}"
WORKERS="${WORKERS:-1}"
# Kill a worker that stops responding to the master heartbeat (stuck event
# loop, runaway native call) so it doesn't sit dead and eat request slots.
WORKER_TIMEOUT="${WORKER_TIMEOUT:-60}"
GRACEFUL_TIMEOUT="${GRACEFUL_TIMEOUT:-30}"
# Recycle workers periodically to bound slow memory growth from Paddle/OpenCV
# over the container's lifetime. Jitter staggers restarts across workers.
MAX_REQUESTS="${MAX_REQUESTS:-500}"
MAX_REQUESTS_JITTER="${MAX_REQUESTS_JITTER:-100}"

# PaddleOCR's model downloader has no locking: if the cache volume is empty
# and multiple gunicorn workers boot at once, they race to download/extract
# the same tar file and whichever finishes first deletes it out from under
# the others, crashing them. Warm the cache in a single process up front so
# workers only ever read already-present files from disk.
echo "Warming up OCR model cache..."
python -c "
from paddleocr_service.config import settings
from paddleocr_service.service import PaddleOcrService
PaddleOcrService(use_angle_cls=settings.use_angle_cls, lang=settings.ocr_lang)
print('Model cache ready.')
"

echo "Starting PaddleOCR Service on port ${PORT} with ${WORKERS} worker(s)..."

exec gunicorn paddleocr_service.main:app \
    --bind "0.0.0.0:${PORT}" \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers "${WORKERS}" \
    --timeout "${WORKER_TIMEOUT}" \
    --graceful-timeout "${GRACEFUL_TIMEOUT}" \
    --max-requests "${MAX_REQUESTS}" \
    --max-requests-jitter "${MAX_REQUESTS_JITTER}" \
    --log-level info
