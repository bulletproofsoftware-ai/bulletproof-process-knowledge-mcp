FROM python:3.11-slim

WORKDIR /app

# Install system deps for sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download embedding model so first request doesn't hang
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

COPY server.py /app/server.py

ENV PYTHONUNBUFFERED=1
ENV QDRANT_URL=http://qdrant:6333

CMD ["python", "/app/server.py"]
