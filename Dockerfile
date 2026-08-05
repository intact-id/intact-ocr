FROM python:3.10-slim

# System deps for OpenCV headless + PaddleOCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Upgrade pip and pre-install build tools so setuptools>=68 resolves correctly
RUN pip install --no-cache-dir --upgrade pip setuptools>=68 wheel

# Install Python deps (layer caching — only re-runs when pyproject.toml/src changes)
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Copy start script
COPY scripts/ ./scripts/
RUN chmod +x ./scripts/start.sh

ENV PORT=8000

EXPOSE ${PORT}

# start-period gives the model time to load on first boot before failed
# checks count against the container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health', timeout=3)" || exit 1

CMD ["./scripts/start.sh"]
