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
