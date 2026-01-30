FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    sqlite3 \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy source
COPY . /app

# Optional: install virtualenv
# RUN pip install virtualenv && virtualenv /venv && . /venv/bin/activate

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install -r requirements.txt || true  # If requirements.txt is missing

# Make CLI tools executable
RUN chmod +x filehash_tool.py
RUN chmod +x tests/*.sh
RUN chmod +x tests/smoke/*
RUN chmod +x db_migration.py
RUN chmod +x export.py
RUN chmod +x scan.py

# Entry point for testing (can be overridden)
ENTRYPOINT ["python3", "filehash_tool.py"]
