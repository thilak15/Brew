FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if any are needed for package compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the API port
EXPOSE 8000

# Command to run the application (production, no reload)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
