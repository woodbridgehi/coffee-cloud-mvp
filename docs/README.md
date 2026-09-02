# Documentation index

This directory contains the design, architecture, operations, release, and handoff documents for Coffee Cloud MVP. The root [README](../README.md) is the English entry point; the detailed Chinese guide is [README.zh-CN.md](../README.zh-CN.md).

## Start here

- [Application architecture](application-architecture.md) — module boundaries, request flow, and transaction ownership.
- [Device registration and pairing design](device-registration-pairing-design.md) — factory state, activation, claim codes, IDs, and merchant binding.
- [Production consistency](production-consistency.md) — order, task, command, device-event, HOLD, and refund rules.
- [Current v0.4–v0.5 state](v0.4-v0.5-current-state.md) — implemented features and known boundaries.
- [Optimization roadmap](optimization-roadmap-2026-08-30.md) — prioritized follow-up work.

## Architecture and backend

- [Application-layer refactor plan](application-layer-refactor-plan.md)
- [MQTT lifecycle review](mqtt-lifecycle-review-2026-08-30.md)
- [Dual-channel SSE](dual-channel-sse.md)
- [Capacity and fault test plan](capacity-and-fault-test-plan.md)
- [v0.4–v0.5 implementation plan](v0.4-v0.5-implementation-plan.md)

## Payments and operations

- [Mock payment cutover](mock-pay-cutover-2026-08-31.md)
- [B2B implementation plan](b2b-implementation-plan-2026-08-31.md)
- [B2B username release](b2b-username-release.md)

## UI and Open Design

- [UI/UX redesign specification](UI_UX_REDESIGN_SPEC.md)
- [Open Design cloud-to-code brief](open-design-code-to-code-brief.md)
- [Open Design frontend revamp](open-design-frontend-revamp-2026-09-01.md)
- [Open Design code port plan](open-design-cc-port-plan-2026-09-02.md)
- [Open Design merge review](open-design-merge-review-2026-08-31.md)
- [Design tokens](design-tokens.json)

## Releases

Release notes are kept under [`releases/`](releases/):

- [2026-09-02 — Coffee Cloud UI port](releases/2026-09-02-cc-ui-port.md)
- [2026-09-01 — Open Design frontend](releases/2026-09-01-open-design-frontend.md)
- [2026-09-01 — Forest Cream frontend](releases/2026-09-01-forest-cream-frontend.md)
- [2026-08-30 — A1/A2](releases/2026-08-30-a1-a2.md)
- [2026-08-30 — B11](releases/2026-08-30-b11.md)

## Handoffs and historical notes

These documents preserve context from earlier implementation and design sessions. They are reference material rather than the source of truth for current behavior:

- [GPT handoff — 2026-09-02](gpt-handoff-2026-09-02.md)
- [v0.4–v0.5 handoff](v0.4-v0.5-handoff.md)
- [B2B handoff](b2b-handoff-2026-08-31.md)
- [Frontend task and delivery notes](pi-frontend-redesign-prompt.md), [B2B task](pi-b2b-frontend-task.md), and [B2B delivery](pi-b2b-frontend-delivery.md)
- [Release delivery notes](pi-username-release-task.md), [delivery](pi-username-release-delivery.md)

When a historical handoff conflicts with code or the current release notes, prefer the implementation and the latest release documentation.
