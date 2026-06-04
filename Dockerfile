# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip wheel && pip wheel --wheel-dir /wheels .

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --create-home --shell /usr/sbin/nologin sol
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
COPY --chown=sol:sol src /app/src
COPY --chown=sol:sol alembic /app/alembic
COPY --chown=sol:sol alembic.ini /app/alembic.ini
WORKDIR /app
USER sol
ENV PYTHONPATH=/app/src SOL_PORT=9320
EXPOSE 9320
ENTRYPOINT ["uvicorn", "sol.main:app", "--host", "0.0.0.0", "--port", "9320", "--workers", "4"]
