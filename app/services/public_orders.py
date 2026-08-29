from __future__ import annotations

import logging
import secrets
import uuid
from typing import Any, Callable

from ..db import UnitOfWork
from ..order_logic import public_menu
from ..protocol import PublicOrderCreateRequest, canonical_digest, utc_now
from ..repositories import OrderRepository, PaymentRepository, TerminalRepository
from ..security import derive_order_access_token, hash_token, tokens_equal
from ..settings import Settings
from .errors import ServiceError
from .order_state import transition_order
from .presenters import iso, payment_payload


log = logging.getLogger("coffee-cloud-mvp.public-orders")


class PublicOrderService:
    def __init__(
        self,
        uow: UnitOfWork,
        settings: Settings,
        *,
        request_dispatch: Callable[[Any, int, str], None],
        payment_provider: Callable[[str], Any],
    ) -> None:
        self.uow = uow
        self.settings = settings
        self.request_dispatch = request_dispatch
        self.payment_provider = payment_provider

    @staticmethod
    def _terminal(repository: TerminalRepository, identifier: str, *, for_update: bool = False) -> dict[str, Any]:
        terminal = repository.find(identifier, for_update=for_update)
        if terminal is None:
            raise ServiceError(404, "device not found")
        return terminal

    @staticmethod
    def _authenticate(repository: OrderRepository, order_id: uuid.UUID, token: str | None, *, for_update: bool = False) -> dict[str, Any]:
        if not token:
            raise ServiceError(401, "missing order access token")
        order = repository.find_with_terminal(order_id, for_update=for_update)
        if order is None or not tokens_equal(order["access_token_hash"].strip(), hash_token(token)):
            raise ServiceError(404, "order not found")
        return order

    @staticmethod
    def _payload(orders: OrderRepository, payments: PaymentRepository, order: dict[str, Any]) -> dict[str, Any]:
        projected = "job_json" in order
        job = order.get("job_json") if projected else orders.job(order["id"])
        payment = order.get("payment_json") if projected else payments.latest_for_order(order["id"])
        transitions = order.get("transitions_json") if projected else orders.transitions(order["id"])
        return {
            "orderId": str(order["id"]), "orderNo": order["order_no"],
            "deviceId": order.get("device_id"), "storeId": order.get("store_id"),
            "status": order["status"], "paymentMode": order["payment_mode"],
            "paymentStatus": order["payment_status"],
            "payment": payment_payload(payment) if payment else None,
            "totalAmountMinor": order["total_amount_minor"], "currency": order["currency"],
            "product": order["product_snapshot"],
            "queuePosition": int(order["queue_position_value"]) if projected else orders.queue_position(order),
            "failure": {"code": order["failure_code"], "message": order["failure_message"]}
                if order["failure_code"] else None,
            "production": {
                "taskId": job["task_id"], "status": job["status"],
                "progress": job["progress"], "overallProgress": job["progress"],
                "stepProgress": job["step_progress"], "currentStepId": job["current_step_id"],
                "currentStepName": job["current_step_name"],
                "plannedDurationSeconds": job["planned_duration_seconds"],
                "elapsedSeconds": job["elapsed_seconds"], "remainingSeconds": job["remaining_seconds"],
                "stepPlan": job["step_durations"], "stepDurations": job["step_durations"],
                "acceptedAt": iso(job["accepted_at"]), "startedAt": iso(job["started_at"]),
                "completedAt": iso(job["completed_at"]),
            } if job else None,
            "createdAt": iso(order["created_at"]), "updatedAt": iso(order["updated_at"]),
            "startedAt": iso(order["started_at"]), "completedAt": iso(order["completed_at"]),
            "timeline": [
                {"revision": item["revision"], "from": item["from_status"], "to": item["to_status"],
                 "reason": item["reason"], "createdAt": iso(item["created_at"])}
                for item in transitions
            ],
        }

    def menu(self, identifier: str) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            terminals = TerminalRepository(connection)
            terminal = self._terminal(terminals, identifier)
            capabilities = terminals.snapshot(terminal["id"], "capabilities")
            inventory = terminals.snapshot(terminal["id"], "inventory")
        return {
            **public_menu(
                terminal, capabilities, inventory, self.settings.offline_threshold_seconds,
                self.settings.default_product_price_minor, self.settings.payment_currency,
                self.settings.public_payment_mode,
            ),
            "serverTime": iso(utc_now()),
        }

    def create(
        self, identifier: str, payload: PublicOrderCreateRequest, idempotency_key: str | None
    ) -> dict[str, Any]:
        if not idempotency_key or len(idempotency_key) > 160:
            raise ServiceError(400, "Idempotency-Key is required and must be <= 160 characters")
        if payload.paymentMode != self.settings.public_payment_mode:
            raise ServiceError(409, "payment mode changed; refresh the menu")
        digest = canonical_digest(payload.model_dump(mode="json"))
        with self.uow.transaction() as connection:
            terminals = TerminalRepository(connection)
            orders = OrderRepository(connection)
            payments = PaymentRepository(connection)
            terminal = self._terminal(terminals, identifier, for_update=True)
            access_token = derive_order_access_token(
                self.settings.order_access_secret or self.settings.admin_token,
                terminal["device_id"], idempotency_key,
            )
            existing = orders.find_idempotent(terminal["id"], idempotency_key)
            if existing:
                if existing["request_digest"].strip() != digest:
                    raise ServiceError(409, "Idempotency-Key payload conflict")
                return {**self._payload(orders, payments, existing), "accessToken": access_token, "duplicate": True}
            capabilities = terminals.snapshot(terminal["id"], "capabilities")
            inventory = terminals.snapshot(terminal["id"], "inventory")
            menu = public_menu(
                terminal, capabilities, inventory, self.settings.offline_threshold_seconds,
                self.settings.default_product_price_minor, self.settings.payment_currency,
                self.settings.public_payment_mode,
            )
            product = next((item for item in menu["products"] if item["recipeId"] == payload.recipeId), None)
            if not product or product["recipeVersion"] != payload.recipeVersion:
                raise ServiceError(409, "recipe is missing or version changed; refresh the menu")
            if not product["available"]:
                raise ServiceError(409, {"code": "PRODUCT_UNAVAILABLE", "reasons": product["unavailableReasons"]})
            if orders.active_count(terminal["id"]) >= self.settings.public_order_queue_limit:
                raise ServiceError(429, "device order queue is full")
            order_id = uuid.uuid4()
            task_id = f"task-{uuid.uuid4()}"
            order_status = "QUEUED" if payload.paymentMode == "TEST_FREE" else "CREATED"
            payment_status = "NOT_REQUIRED" if payload.paymentMode == "TEST_FREE" else "NOT_STARTED"
            product_snapshot = {**product, "quantity": 1}
            orders.insert(
                order_id=order_id, order_no=f"C{utc_now().strftime('%m%d')}-{secrets.token_hex(3).upper()}",
                terminal_id=terminal["id"], access_token_hash=hash_token(access_token),
                idempotency_key=idempotency_key, request_digest=digest, order_status=order_status,
                payment_mode=payload.paymentMode, payment_status=payment_status, product=product_snapshot,
            )
            orders.insert_initial_transition(
                order_id, order_status,
                "test-free order accepted" if payload.paymentMode == "TEST_FREE" else "order created awaiting payment",
                {"recipeId": payload.recipeId, "inventoryVersion": menu.get("inventoryVersion")},
            )
            if payload.paymentMode == "TEST_FREE":
                orders.insert_test_free_job(
                    job_id=uuid.uuid4(), task_id=task_id, order_id=order_id, terminal_id=terminal["id"],
                    planned_duration_seconds=product.get("estimatedDurationSeconds"),
                )
                self.request_dispatch(connection, terminal["id"], "test-free-order")
            created = orders.find_with_terminal(order_id)
            assert created is not None
            response = self._payload(orders, payments, created)
        return {**response, "accessToken": access_token}

    def get(self, order_id: uuid.UUID, access_token: str | None) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            orders = OrderRepository(connection)
            if not access_token:
                raise ServiceError(401, "missing order access token")
            order = orders.public_view(order_id)
            if order is None or not tokens_equal(order["access_token_hash"].strip(), hash_token(access_token)):
                raise ServiceError(404, "order not found")
            return self._payload(orders, PaymentRepository(connection), order)

    def cancel(self, order_id: uuid.UUID, access_token: str | None) -> dict[str, Any]:
        payment_to_close: dict[str, Any] | None = None
        with self.uow.transaction() as connection:
            orders = OrderRepository(connection)
            payments = PaymentRepository(connection)
            order = self._authenticate(orders, order_id, access_token, for_update=True)
            if order["status"] not in {"CREATED", "AWAITING_PAYMENT", "QUEUED"}:
                raise ServiceError(409, "only unpaid or queued orders can be cancelled safely")
            if order["status"] in {"CREATED", "AWAITING_PAYMENT"}:
                payment_to_close = payments.latest_open_for_order(order_id, for_update=True)
            transition_order(connection, order, "CANCELLED", "customer", reason="cancelled before dispatch")
            orders.cancel_job(order_id)
        if payment_to_close:
            try:
                result = self.payment_provider(payment_to_close["provider"]).close_payment(
                    payment_to_close["merchant_payment_no"]
                )
                with self.uow.transaction() as connection:
                    payments = PaymentRepository(connection)
                    current = payments.find(payment_to_close["id"], for_update=True)
                    if current and current["status"] in {"CREATED", "PENDING"}:
                        from ..payment_service import transition_payment

                        transition_payment(connection, current, "CLOSED", actor="customer-cancel", payload=result.raw)
                        OrderRepository(connection).update_payment_status(order_id, "CLOSED")
            except Exception as exc:
                log.warning("payment close deferred after order cancellation payment=%s: %s", payment_to_close["id"], exc)
        return self.get(order_id, access_token)
