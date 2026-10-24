# Multi-platform production container for Interactive Knowledge Base
FROM python:3.11-slim

# Prevent Python from writing .pyc and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV HOST=0.0.0.0

WORKDIR /app

# Install system dependencies (build-essential for numpy/scipy if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY Phase1/ Phase1/
COPY Phase2/ Phase2/
COPY Phase3/ Phase3/
COPY Phase4/ Phase4/
COPY run_app.py .
COPY test_all_phases.py .
COPY config/ pipeline-lock.json* ./config/

EXPOSE 8080

# Run unified server
CMD ["python", "run_app.py"]
