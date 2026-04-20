# DAWN (ForgeChain) Docker Image
# Deterministic Auditable Workflow Network
# Headless service for SAM Agent integration

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies (if needed for pdfplumber, opencv, etc.)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install pytest for testing inside container
RUN pip install --no-cache-dir pytest==9.0.2

# Copy application code
COPY dawn/ ./dawn/
COPY forgechain_console/ ./forgechain_console/

# Create projects directory as mount point
# This directory should be mounted as a volume at runtime
RUN mkdir -p /app/projects

# Expose API port
EXPOSE 3434

# Run the FastAPI server
CMD ["python3", "-m", "uvicorn", "forgechain_console.server:app", "--host", "0.0.0.0", "--port", "3434"]
