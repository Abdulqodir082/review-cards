FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

RUN useradd --create-home --uid 1000 exporter \
    && mkdir -p /data/session /data/exports \
    && chown -R exporter:exporter /data \
    && chmod 700 /data/session

COPY --chown=exporter:exporter app ./app
COPY --chown=exporter:exporter login.py .

USER exporter
ENV SESSION_DIR=/data/session \
    EXPORT_DIR=/data/exports

CMD ["python", "-m", "app.main"]
