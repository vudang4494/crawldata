FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

WORKDIR /app

# Workspace install
COPY pyproject.toml uv.lock* ./
COPY libs ./libs
COPY apps ./apps
COPY configs ./configs

RUN uv sync --all-extras --all-groups || uv sync

EXPOSE 8000

CMD ["uv", "run", "--package", "service", "uvicorn", \
     "crawl_datasets_service.main:app", \
     "--host", "0.0.0.0", "--port", "8000"]