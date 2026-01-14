FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Install the actual Chromium browser ---
RUN playwright install chromium --with-deps

# Copy the app code
COPY ./app /app
RUN mkdir -p /app/data /app/screenshots

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
