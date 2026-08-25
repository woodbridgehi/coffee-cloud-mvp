FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

USER appuser

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8788/health', timeout=2)); assert data['status'] == 'ok'"

CMD ["sh", "-c", "uvicorn app.main:app --host ${SERVICE_HOST:-127.0.0.1} --port ${SERVICE_PORT:-8788} --log-level ${LOG_LEVEL:-info}"]

