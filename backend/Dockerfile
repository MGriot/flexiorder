# Backend Dockerfile
FROM python:3.11-slim

# Install system dependencies for any potential needs (though win32gui won't work on Linux)
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
# pywin32 will fail to install on Linux. We'll use a conditional install or just let it fail if not on Windows.
# For Docker (Linux), we'll install a mock or just skip it if we want the API to start.
RUN sed -i '/pywin32/d' requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code
COPY . .

# Expose the port
EXPOSE 8000

# Run the application
# We use 0.0.0.0 to allow external access
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
