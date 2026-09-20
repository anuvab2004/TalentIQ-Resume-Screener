# ==============================================================================
# TalentIQ - AI Resume Screener & Job Matcher
# Dockerfile for containerized deployment
# ==============================================================================

FROM python:3.11-slim

# Build argument to optionally install sentence-transformers embeddings
ARG INSTALL_EMBEDDINGS=false

# Prevent Python from writing .pyc files and configure Streamlit
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    TALENTIQ_DATA_DIR=/app/data

WORKDIR /app

# Install system dependencies (curl for container healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt requirements-embeddings.txt ./

# Install python dependencies with extended network timeout
RUN pip install --no-cache-dir --default-timeout=100 -r requirements.txt && \
    if [ "$INSTALL_EMBEDDINGS" = "true" ]; then \
        pip install --no-cache-dir --default-timeout=100 -r requirements-embeddings.txt ; \
    fi

# Create non-root user and persistent directories
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/data /home/appuser/.talentiq && \
    chown -R appuser:appuser /app /home/appuser/.talentiq

# Copy application files
COPY --chown=appuser:appuser app.py .
COPY --chown=appuser:appuser .streamlit .streamlit
COPY --chown=appuser:appuser src src
COPY --chown=appuser:appuser sample_data sample_data

# Run as non-root user for security
USER appuser

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl --fail http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
