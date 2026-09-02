# Coffee Cloud MVP

> Cloud backend and operations platform for automated coffee terminals.

[简体中文](README.zh-CN.md) · [Documentation index](docs/README.md)

Coffee Cloud MVP provides the cloud-side services required to operate a fleet of automated coffee terminals. It covers device registration and activation, merchant and store binding, live menus, inventory, orders, payments, production jobs, MQTT device commands, and real-time order status updates.

## Highlights

- Device registration, activation, lifecycle management, and MQTT credential rotation.
- Per-device public ordering pages with dynamically generated QR-code URLs.
- Recipe, material inventory, availability, and production task management.
- Idempotent order, payment, refund, callback, and device-event processing.
- MQTT command delivery through a multi-device gateway and command outbox.
- Real-time order progress through Server-Sent Events (SSE).
- Merchant operations pages for devices, orders, inventory, operators, permissions, and audit logs.
- Simulator-friendly `TEST_FREE` payment mode for local development; production should use `ONLINE` payments.

## Architecture

The service is a FastAPI + PostgreSQL modular monolith with Redis, MQTT/EMQX, and background workers. HTTP requests follow a layered application flow:

```text
HTTP Route → Application Service → Repository → PostgreSQL
```

The order and production flow is:

```text
Device menu → Public order → Payment → Business outbox
→ Production job → MQTT command → Device execution → SSE status updates
```

## Technology

- Python 3.12 and FastAPI
- PostgreSQL
- Redis
- MQTT / EMQX
- Vanilla JavaScript and CSS for the ordering and operations pages
- `uv` for dependency and virtual-environment management

## Quick start

```bash
uv venv --managed-python --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.lock
cp .env.example .env
.venv/bin/pytest -q
```

Configure the database, public URL, authentication token, payment mode, and MQTT settings in `.env`. The complete configuration reference is in [`.env.example`](.env.example).

## Useful endpoints

| Purpose | Endpoint |
| --- | --- |
| Public ordering | `/order?device_id=<device-id>` |
| Operations console | `/admin` |
| OpenAPI documentation | `/docs` |
| Liveness check | `/health` |
| Readiness check | `/ready` |

The public base URL and device-specific QR-code URL are configured with `PUBLIC_BASE_URL`. Administrative APIs require `Authorization: Bearer $ADMIN_TOKEN`.

## Security and configuration

Never commit `.env`, `.secrets/`, payment keys, private keys, database dumps, or production credentials. Use `.env.example` as the configuration template. Keep production secrets on the deployment host or in a dedicated secret manager.

`PUBLIC_PAYMENT_MODE=TEST_FREE` is intended only for local simulator workflows. Use `PUBLIC_PAYMENT_MODE=ONLINE` with properly configured payment credentials in production.

## Deployment

Before upgrading a deployment, back up PostgreSQL, preserve the VPS environment files, rebuild the services, and verify the health endpoints:

```bash
docker exec postgres-web pg_dump -U coffee_cloud -Fc coffee_cloud_mvp > coffee-cloud-before-upgrade.dump
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8788/health
```

Database migrations run during application startup. Review the deployment notes in [`docs/releases/`](docs/releases/) before production changes.

## Documentation

Start with the [documentation index](docs/README.md), which groups architecture, device lifecycle, payments, operations, UI, testing, deployment, and historical handoff documents. The detailed Chinese guide is available in [README.zh-CN.md](README.zh-CN.md).

## License

This repository is currently an internal project. Add a license before distributing it outside the project team.
