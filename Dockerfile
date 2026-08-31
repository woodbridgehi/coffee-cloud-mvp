FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

COPY requirements.txt requirements.lock ./
# Install from the lock so transitive dependencies cannot drift between
# rebuilds of the same source (see R0 in docs/optimization-roadmap-2026-08-30.md).
RUN pip install --no-cache-dir -r requirements.lock

COPY app ./app
COPY public ./public
# Local copies can carry owner-only permissions (e.g. 0600). COPY preserves
# those modes but makes root the owner; the non-root server must read every
# static module, including modules imported by the merchant entry point.
RUN chmod -R a+rX ./public

USER appuser

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8788/health', timeout=2)); assert data['status'] == 'ok'"

CMD ["sh", "-c", "uvicorn app.main:app --host ${SERVICE_HOST:-127.0.0.1} --port ${SERVICE_PORT:-8788} --workers ${API_WORKERS:-1} --log-level ${LOG_LEVEL:-info} --no-access-log"]
