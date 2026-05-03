# =============================================================
# Dockerfile — virgo-recsys FastAPI Service
# =============================================================

FROM python:3.11-slim

# Metadata
LABEL maintainer="Geraldin Gysrawa, Ikhsan Zuhri, M. Harish Al Rasyidi"
LABEL description="Virgo Talent Recommendation System — TA D3 Teknik Informatika POLBAN"

# Hindari .pyc dan pastikan stdout/stderr langsung tampil di log
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install OS dependencies (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    openjdk-21-jre \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies dulu (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/
COPY configs/ ./configs/
COPY ontology/ttl/ ./ontology/ttl/

# Non-root user untuk keamanan
RUN adduser --disabled-password --gecos "" appuser
USER appuser

EXPOSE 8000

# Health check — pastikan service up
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Jalankan FastAPI via uvicorn
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
