FROM python:3.11-slim

WORKDIR /app

# System deps for cryptography, asyncpg, numpy, xgboost (libgomp)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev libpq-dev libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency spec first for Docker layer caching
COPY pyproject.toml ./

# Install Python deps (non-editable for production)
RUN pip install --no-cache-dir .

# Copy application code
COPY . .

# Create keys dir — private key injected at runtime via KALSHI_PRIVATE_KEY_BASE64
RUN mkdir -p /app/keys

# Entrypoint script writes key file from env var, then starts uvicorn
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
