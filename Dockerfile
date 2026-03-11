FROM python:3.12-slim

WORKDIR /app

# Install Playwright system deps
RUN apt-get update && apt-get install -y \
    wget curl gnupg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium --with-deps

COPY src/ ./src/

EXPOSE 8383

CMD ["python", "-m", "src.server"]
