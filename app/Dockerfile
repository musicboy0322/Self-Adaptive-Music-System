# ================================
# Dockerfile for CarTunes Backend
# ================================
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy dependency files first (for better caching)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Optional: copy a default config if you want to bake it into the image
# (you can also mount config.yml later via ConfigMap)
COPY config.yml /app/config.yml

# Ensure OpenShift can run as arbitrary user
RUN chmod -R g+rwX /app

# Expose app port (OpenShift standard)
EXPOSE 8080

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    ENV=production \
    PORT=8080 \
    HOST=0.0.0.0

# Run the FastAPI app via main.py
CMD ["python", "main.py"]
