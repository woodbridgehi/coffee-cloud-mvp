from __future__ import annotations

import uuid
from typing import Any

from ..db import UnitOfWork
from ..command_state import decide_transition
from ..production_state import device_is_busy
from ..protocol import OrderAdjudicationRequest, canonical_digest, utc_now
from ..repositories import (
    AdminAccessRepository,
    CommandRepository,
    OrderRepository,
    TerminalRepository,
)
from ..repositories.adjudications import AdjudicationRepository
from .admin_access import AdminAccessService
from .command_state import transition_command
from .errors import ServiceError
from .order_state import transition_order
from .production import ProductionService


class OrderAdjudicationService:
    """Human-confirmed business resolution, never an instruction to move hardware."""

    def __init__(self, uow: UnitOfWork, production: ProductionService) -> None:
        self.uow = uow
        self.production = production

    def adjudicate(
        self,
        order_id: uuid.UUID,
        payload: OrderAdjudicationRequest,
        key: str,
        principal: dict[str, Any],
        request_id: str | None = None,
    ) -> dict[str, Any]:
        # Also enforce permissions here: non-HTTP callers cannot bypass them.
        AdminAccessService.require(principal, "commands.execute")
        AdminAccessService.require(principal, "refunds.manage")
        if not isinstance(key, str) or not key.strip() or len(key) > 160:
            raise ServiceError(422, "Idempotency-Key must contain 1 to 160 characters")
        body = payload.model_dump(mode="json")
        digest = canonical_digest(body)
        with self.uow.transaction() as connection:
            orders = OrderRepository(connection)
            order = orders.find_with_terminal(order_id, for_update=True)
            if not order:
                raise ServiceError(404, "order not found")
            adjudications = AdjudicationRepository(connection)
            previous = adjudications.find(order_id, key)
            if previous:
                if previous["request_digest"].strip() != digest:
                    raise ServiceError(409, "Idempotency-Key payload conflict")
                return previous["response_json"]
            located = orders.job(order_id)
            job = orders.lock_job(located["id"]) if located else None
            if not job or job["task_id"] != payload.taskId:
                raise ServiceError(409, "task does not belong to this order")
            if job["revision"] != payload.expectedRevision:
                raise ServiceError(
                    409, "production job revision changed; refresh before adjudication"
                )
            if (
                order["status"] != "HOLD"
                or job["status"] != "HOLD"
                or not job["manual_review_required"]
            ):
                raise ServiceError(409, "order is not awaiting manual review")
            command = (
                CommandRepository(connection).by_db_id(job["command_id"])
                if job["command_id"]
                else None
            )
            if (
                not command
                or command["command_type"] != "MAKE_DRINK"
                or command["terminal_id"] != order["terminal_id"]
                or command["payload_json"].get("taskId") != payload.taskId
            ):
                raise ServiceError(409, "production command association mismatch")
            if not decide_transition(command["status"], payload.outcome).allowed:
                raise ServiceError(409, "command cannot accept this adjudication")
            succeeded = payload.outcome == "SUCCEEDED"
            order_status = "READY" if succeeded else payload.outcome
            actor = f"admin:{principal['actorId']}"
            now = utc_now()
            transition_command(
                connection,
                command,
                payload.outcome,
                actor,
                reason=payload.reason,
                payload=body,
            )
            orders.update_job_terminal(
                job["id"],
                status=payload.outcome,
                progress=1.0 if succeeded else float(job["progress"] or 0),
                step_progress=1.0 if succeeded else float(job["step_progress"] or 0),
                planned=None,
                steps=None,
                failure=None
                if succeeded
                else {"code": "MANUAL_ADJUDICATION", "reason": payload.reason},
                elapsed=job.get("elapsed_seconds"),
                remaining=0.0 if succeeded else job.get("remaining_seconds"),
                device_revision=None,
                accepted_at=job.get("accepted_at"),
                started_at=job.get("started_at"),
                completed_at=now,
            )
            orders.clear_job_hold(job["id"])
            orders.update_failure(
                order_id,
                None if succeeded else "MANUAL_ADJUDICATION",
                None if succeeded else payload.reason,
            )
            order = transition_order(
                connection,
                order,
                order_status,
                actor,
                reason=payload.reason,
                payload=body,
            )
            if not succeeded:
                self.production.create_automatic_refund_record(
                    connection, order, job, "manual-adjudication"
                )
            # No terminal row lock after the order lock. This is an advisory
            # projection only; the dispatcher independently rechecks device state.
            terminal = TerminalRepository(connection).by_id(order["terminal_id"])
            result = {
                "orderId": str(order_id),
                "taskId": payload.taskId,
                "status": order_status,
                "productionStatus": payload.outcome,
                "productionRevision": int(job["revision"]) + 1,
                "deviceReleasePending": terminal is None
                or device_is_busy(terminal.get("reported_status")),
                "physicalStopConfirmedByServer": False,
            }
            self.production.request_dispatch(
                connection, order["terminal_id"], "manual-adjudication"
            )
            AdminAccessRepository(connection).write_audit(
                principal,
                "order.adjudicate",
                "order",
                str(order_id),
                {**body, "result": result},
                request_id,
            )
            adjudications.insert(order_id, payload.taskId, key, digest, result)
            return result
