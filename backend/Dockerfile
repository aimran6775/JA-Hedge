FROM python:3.11-slim

WORKDIR /app

# System deps for cryptography, asyncpg, numpy, xgboost (libgomp)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev libpq-dev libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency spec first for Docker layer caching
COPY backend/pyproject.toml ./

# Install Python deps (non-editable for production)
RUN pip install --no-cache-dir .

# Copy application code (from backend/ subdirectory — build context is repo root)
COPY backend/ .

# Create keys dir — private key injected at runtime via KALSHI_PRIVATE_KEY_BASE64
RUN mkdir -p /app/keys

# Make entrypoint executable (already copied by COPY backend/ .)
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
