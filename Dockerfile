FROM python:3.12-slim

WORKDIR /app

# README.md is required at build time — pyproject.toml declares it as the readme.
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

EXPOSE 8383

USER 1000:1000
CMD ["jobsearch-mcp"]
