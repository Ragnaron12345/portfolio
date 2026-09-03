FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN addgroup --system evalforge && adduser --system --ingroup evalforge evalforge

COPY requirements.txt pyproject.toml ./
RUN pip install --upgrade pip && pip install -r requirements.txt pytest pytest-asyncio ruff

COPY app ./app
COPY tests ./tests
RUN mkdir -p /app/data && chown -R evalforge:evalforge /app

USER evalforge
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
