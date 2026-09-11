FROM python:3.11-slim

WORKDIR /app

# System dependency for CAPTCHA OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright's own installer pulls Chromium + every OS library it needs
RUN playwright install --with-deps chromium

# App code
COPY . .

ENV SCRAPER_HEADLESS=true
ENV HOST=0.0.0.0

EXPOSE 8000
CMD ["python", "web.py"]