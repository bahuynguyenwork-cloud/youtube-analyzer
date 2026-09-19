FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (curl, git)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Expose port (default 8000 or from ENV)
EXPOSE 8000

ENV PORT=8000

CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}
