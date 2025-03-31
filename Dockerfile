# Base image
FROM python:3.12-slim

# Install required dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsqlite3-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy script
COPY filehash_tool.py .

# Install required Python packages
RUN pip install --no-cache-dir tqdm psutil

# Allow overriding DB and commands at runtime
ENTRYPOINT ["python", "filehash_tool.py"]
CMD ["--help"]
