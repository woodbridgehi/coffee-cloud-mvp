# Coffee Cloud MVP

[简体中文](README.zh-CN.md) · [Documentation](docs/README.md)

Coffee Cloud is the FastAPI/PostgreSQL backend for the companion Coffee Terminal Simulator. It provides customer ordering, payments/refunds, serial device queues, device identity and commands, and a multi-tenant merchant portal. This checkout's API version is `0.4.0`; the migration list currently ends at **23**. Neither the version string nor historical release notes establish the state of a running deployment.

## Current architecture

- PostgreSQL stores orders, production jobs, payment/refund records, Inbox/Outbox and device snapshots.
- Redis holds transient task progress and hot device telemetry. PostgreSQL NOTIFY and Redis Pub/Sub feed customer SSE connections; neither notification channel is a replay log.
- Compose separates the API, MQTT gateway and domain worker. PostgreSQL and EMQX are external to the main compose file; EMQX has separate deployment files.
- The simulator owns timed recipe execution and local SQLite stock. Its Three.js viewer illustrates reported execution; it does not control real arms.
- Merchant accounting stock, cloud admission commitments and device stock are different data models.

## Entry points

| Surface | Path | Authentication |
| --- | --- | --- |
| Customer menu | `/order?device_id=<deviceId>` | Public menu; order reads require an order access token |
| Customer status | `/order/status` | `X-Order-Access-Token` for API/SSE |
| Platform administration | `/admin` | Admin Bearer token and permissions |
| Merchant portal | `/assets/merchant.html` | Session cookie, tenant/store scope; CSRF on writes |
| OpenAPI | `/docs`, `/openapi.json` | Generated from registered routes |
| Probes | `/health`, `/ready` | Liveness / cached database readiness |

## Local development

Run from this repository. Configure a dedicated local PostgreSQL database and a local `.env` using [the operations guide](docs/operations.md); do not reuse production credentials.

```bash
uv venv --managed-python --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.lock
.venv/bin/python -m app.migrate
RUN_DATABASE_MIGRATIONS=false .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8788
```

A single development API process runs background workers by default. Compose disables them in API workers and runs a separate worker instead. Do not run both against the same deployment as if the worker had automatic singleton election.

```bash
.venv/bin/python -m pytest -q
node --test tests/*.mjs
.venv/bin/python scripts/export_openapi.py
```

PostgreSQL tests require a dedicated `TEST_DATABASE_URL`; Redis integration tests additionally require a disposable `TEST_REDIS_URL`. Skips do not prove integration passed. The export command updates the tracked OpenAPI file.

## Read next

- [Current capabilities and boundaries](docs/current-state.md)
- [Architecture and code map](docs/application-architecture.md)
- [Production, HOLD and refunds](docs/production-consistency.md)
- [Identity and pairing](docs/device-registration-pairing-design.md)
- [Deployment, configuration and troubleshooting](docs/operations.md)
- [Documentation audit and follow-up work](docs/documentation-audit-2026-09-17.md)

Actual payment enablement, merchant permissions and simulator pairing depend on configuration. No WeChat payment provider or real robot/RS-485 driver is implemented in these two projects. No fleet-capacity, physical exactly-once or current production-deployment claim is made by this README.
