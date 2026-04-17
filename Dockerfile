FROM python:3.10-slim

# System deps for OpenCV headless + PaddleOCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer caching — only re-runs when pyproject.toml changes)
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Copy start script
COPY scripts/ ./scripts/
RUN chmod +x ./scripts/start.sh

# Pre-download PaddleOCR models at build time so startup is fast
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=True, lang='en')"

ENV PORT=8000

EXPOSE ${PORT}

CMD ["./scripts/start.sh"]
