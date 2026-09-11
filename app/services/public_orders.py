from __future__ import annotations

from ..failure_info import failure_info

import logging
import secrets
import uuid
from typing import Any, Callable

from ..customization import select_variant, issue_quote, check_quote
from ..db import UnitOfWork
from ..order_logic import public_menu, terminal_is_online
from ..material_commitments import apply_commitments
from ..payment_service import apply_paid_callback, transition_payment
from ..protocol import PublicOrderCreateRequest, canonical_digest, utc_now
from ..repositories import OrderRepository, PaymentRepository, TerminalRepository
from ..repositories.pickup import PickupRepository
from ..robot_view import public_robot_view, anonymous_robot_snapshot
from ..security import derive_order_access_token, hash_token, tokens_equal
from ..settings import Settings
from ..telemetry import TelemetryCache
from ..live_progress import merge_progress
from .errors import ServiceError
from .order_state import transition_order
from .presenters import iso, payment_payload
from .refund_intents import REFUNDABLE_PAYMENT_STATUSES, ensure_automatic_refund_intent
from ..merchant.accounts import provider_for_payment
from ..merchant.catalog import apply_merchant_catalog


log = logging.getLogger("coffee-cloud-mvp.public-orders")


class PublicOrderService:
    def __init__(
        self,
        uow: UnitOfWork,
        settings: Settings,
        *,
        request_dispatch: Callable[[Any, int, str], None],
        payment_provider: Callable[[str], Any],
        telemetry_cache: TelemetryCache | None = None,
    ) -> None:
        self.uow = uow
        self.settings = settings
        self.request_dispatch = request_dispatch
        self.payment_provider = payment_provider
        self.telemetry_cache = telemetry_cache

    @staticmethod
    def _terminal(repository: TerminalRepository, identifier: str, *, for_update: bool = False) -> dict[str, Any]:
        terminal = repository.find(identifier, for_update=for_update)
        if terminal is None:
            raise ServiceError(404, "device not found")
        terminal['pickupBlocked'] = PickupRepository(repository.connection).blocked(terminal['id'])
        return terminal

    def _payment_mode(self, terminal: dict[str, Any]) -> str:
        if (self.settings.simulator_bootstrap_enabled
                and terminal.get("device_identity_kind") == "SIMULATOR_SOFTWARE"):
            return self.settings.simulator_payment_mode
        return self.settings.public_payment_mode

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
        payment = order.get("payment_json") if projected else payments.display_for_order(order["id"])
        transitions = order.get("transitions_json") if projected else orders.transitions(order["id"])
        return {
            "orderId": str(order["id"]), "orderNo": order["order_no"],
            "deviceId": order.get("device_id"), "storeId": order.get("store_id"),
            "status": order["status"], "paymentMode": order["payment_mode"],
            "pickupRequired": bool(order.get('pickup_required')),
            "collectedAt": iso(order.get('collected_at')),
            "paymentStatus": order["payment_status"],
            "payment": payment_payload(payment) if payment else None,
            "totalAmountMinor": order["total_amount_minor"], "currency": order["currency"],
            "product": order["product_snapshot"],
            "queuePosition": int(order["queue_position_value"]) if projected else orders.queue_position(order),
            "failure": failure_info(order, job),
            "production": {
                "taskId": job["task_id"], "status": job["status"], "attempt": job.get("execution_attempt", 1),
                "deviceRevision": int(job.get("last_device_revision") or 0),
                "progress": job["progress"], "overallProgress": job["progress"],
                "stepProgress": job["step_progress"], "currentStepId": job["current_step_id"],
                "currentStepName": job["current_step_name"],
                "plannedDurationSeconds": job["planned_duration_seconds"],
                "elapsedSeconds": job["elapsed_seconds"], "remainingSeconds": job["remaining_seconds"],
                "stepPlan": job["step_durations"], "stepDurations": job["step_durations"],
                "robotView": public_robot_view(job["step_durations"]),
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
            payment_mode = self._payment_mode(terminal)
            capabilities = terminals.snapshot(terminal["id"], "capabilities")
            inventory = terminals.snapshot(terminal["id"], "inventory")
            menu = public_menu(
                terminal, capabilities, inventory, self.settings.offline_threshold_seconds,
                self.settings.default_product_price_minor, self.settings.payment_currency,
                payment_mode,
            )
            orders = OrderRepository(connection)
            commitments = orders.material_commitments(terminal['id'])
            apply_commitments(menu, inventory, commitments, orders.required_inventory_version(terminal['id']))
            if getattr(self.settings,'merchant_enabled',False):
                menu = apply_merchant_catalog(connection,terminal,menu,payment_mode)
            # A default ingredient shortage must not hide a valid no-milk/no-ice choice.
            base_menu = public_menu(terminal, capabilities, inventory, self.settings.offline_threshold_seconds,
                                    self.settings.default_product_price_minor, self.settings.payment_currency, payment_mode)
            bases = {p['recipeId']: p for p in base_menu['products']}
            for product in menu['products']:
                base = bases[product['recipeId']]
                if not product.get('optionSchema'):
                    continue
                candidates = [select_variant(base, v['customization'], inventory, menu['online']) for v in base['customizationVariants']]
                apply_commitments({'products': candidates}, inventory, commitments, orders.required_inventory_version(terminal['id']))
                if any(v['available'] for v in candidates) and not any(reason not in ('MATERIAL_INSUFFICIENT', 'QUEUE_MATERIAL_COMMITTED') for reason in product['unavailableReasons']):
                    product['available'] = True
                    product['remainingServings'] = max(v['remainingServings'] for v in candidates if v['available'])
                    product['unavailableReasons'] = []
            menu['salesEnabled'] = any(p['available'] for p in menu['products'])
        return {**menu,"serverTime":iso(utc_now())}

    def quote(self, identifier: str, payload: PublicOrderCreateRequest) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            terminals = TerminalRepository(connection)
            orders = OrderRepository(connection)
            terminal = self._terminal(terminals, identifier, for_update=True)
            payment_mode = self._payment_mode(terminal)
            if payload.paymentMode != payment_mode:
                raise ServiceError(409, 'payment mode changed; refresh menu')
            inventory = terminals.snapshot(terminal['id'], 'inventory')
            menu = public_menu(terminal, terminals.snapshot(terminal['id'], 'capabilities'), inventory,
                              self.settings.offline_threshold_seconds, self.settings.default_product_price_minor,
                              self.settings.payment_currency, payment_mode)
            if getattr(self.settings, 'merchant_enabled', False):
                menu = apply_merchant_catalog(connection, terminal, menu, payment_mode)
            product = self._selected_product(menu, payload, inventory)
            apply_commitments({'products': [product]}, inventory, orders.material_commitments(terminal['id']), orders.required_inventory_version(terminal['id']))
            token = issue_quote(self.settings.order_access_secret or self.settings.admin_token, terminal['device_id'], product, payment_mode)
            return {'quoteId': token, 'expiresAt': int(token.split('.')[0]), 'product': product,
                    'available': product['available'], 'paymentMode': payment_mode}

    @staticmethod
    def _selected_product(menu, payload, inventory):
        product = next((item for item in menu['products'] if item['recipeId'] == payload.recipeId), None)
        if not product or product['recipeVersion'] != payload.recipeVersion:
            raise ServiceError(409, 'recipe is missing or version changed; refresh the menu')
        options = payload.customization.model_dump(exclude_none=True) if payload.customization else None
        return select_variant(product, options, inventory, menu['online'])

    def create(
        self, identifier: str, payload: PublicOrderCreateRequest, idempotency_key: str | None
    ) -> dict[str, Any]:
        if not idempotency_key or len(idempotency_key) > 160:
            raise ServiceError(400, "Idempotency-Key is required and must be <= 160 characters")
        digest = canonical_digest(payload.model_dump(mode="json", exclude_none=True))
        with self.uow.transaction() as connection:
            terminals = TerminalRepository(connection)
            orders = OrderRepository(connection)
            payments = PaymentRepository(connection)
            terminal = self._terminal(terminals, identifier, for_update=True)
            payment_mode = self._payment_mode(terminal)
            if payload.paymentMode != payment_mode:
                raise ServiceError(409, "payment mode changed; refresh the menu")
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
                payment_mode,
            )
            if getattr(self.settings,'merchant_enabled',False):
                menu = apply_merchant_catalog(connection,terminal,menu,payment_mode)
            commitments = orders.material_commitments(terminal['id'])
            product = self._selected_product(menu, payload, inventory)
            apply_commitments({'products': [product]}, inventory, commitments, orders.required_inventory_version(terminal['id']))
            if product.get('optionSchema') or payload.quoteId:
                check_quote(payload.quoteId, self.settings.order_access_secret or self.settings.admin_token,
                            terminal['device_id'], product, payment_mode)
            if not product["available"]:
                raise ServiceError(409, {"code": "PRODUCT_UNAVAILABLE", "reasons": product["unavailableReasons"]})
            if orders.active_count(terminal["id"]) >= self.settings.public_order_queue_limit:
                raise ServiceError(429, "device order queue is full")
            order_id = uuid.uuid4()
            task_id = f"task-{uuid.uuid4()}"
            order_status = "QUEUED" if payload.paymentMode == "TEST_FREE" else "CREATED"
            payment_status = "NOT_REQUIRED" if payload.paymentMode == "TEST_FREE" else "NOT_STARTED"
            product_snapshot = {**product, "quantity": 1}
            product_snapshot.pop("customizationVariants", None)
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

    def with_live_progress(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        job = snapshot.get("production")
        if not self.telemetry_cache or not job or snapshot.get("status") != "MAKING" or job.get("status") != "EXECUTING":
            return snapshot
        return merge_progress(snapshot, self.telemetry_cache.latest_progress(snapshot["deviceId"], job["taskId"]))

    def _queue(self, orders: OrderRepository, order: dict[str, Any]) -> dict[str, Any] | None:
        if order['status'] != 'QUEUED':
            return None
        jobs = orders.queue_context(order)
        terminal = TerminalRepository(orders.connection).find(order['device_id'])
        blocked = PickupRepository(orders.connection).blocked(order['terminal_id'])
        online = bool(terminal and terminal_is_online(terminal, self.settings.offline_threshold_seconds))
        uncertain = not online or terminal.get('lifecycle_status') != 'ACTIVE' or blocked or any(j['status'] in ('PAUSED','RETRY_WAIT','HOLD','UNKNOWN') for j in jobs)
        seconds = 0
        for job in jobs:
            duration = job.get('remaining_seconds') if job['status'] == 'EXECUTING' else job.get('planned_duration_seconds')
            if duration is None:
                duration = job.get('planned_duration_seconds')
            if duration is None or duration <= 0:
                uncertain = True
            else:
                remaining = float(duration)
                if job['status'] == 'EXECUTING' and job.get('remaining_seconds') is not None:
                    remaining = max(0, remaining - max(0, (utc_now()-job['updated_at']).total_seconds()))
                seconds += remaining
        return {'aheadCount': len(jobs), 'estimatedWaitSeconds': None if uncertain else round(seconds),
                'estimateOnly': True, 'blocked': bool(uncertain),
                'watchAvailable': online and any(j['status']=='EXECUTING' and public_robot_view(j['step_durations']) for j in jobs)}

    def watch(self, order_id: uuid.UUID, access_token: str | None) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            orders = OrderRepository(connection)
            order = self._authenticate(orders, order_id, access_token)
            if order['status'] != 'QUEUED':
                return {'scene': None}
            terminal = TerminalRepository(connection).find(order['device_id'])
            if not terminal or not terminal_is_online(terminal, self.settings.offline_threshold_seconds):
                return {'scene': None}
            job = next((j for j in orders.queue_context(order) if j['status']=='EXECUTING'), None)
        if not job:
            return {'scene': None}
        # Redis progress is validated against the active task, then projected again.
        if self.telemetry_cache:
            raw = {'status':'MAKING', 'deviceId':order['device_id'], 'production':{
                'status':'EXECUTING', 'taskId':job['task_id'], 'deviceRevision':job['last_device_revision'],
                'overallProgress':job['progress'], 'stepProgress':job['step_progress']}}
            live = merge_progress(raw, self.telemetry_cache.latest_progress(order['device_id'], job['task_id']))['production']
            job = {**job, 'current_step_id':live.get('currentStepId',job['current_step_id']),
                   'step_progress':live['stepProgress'], 'progress':live['overallProgress'],
                   'last_device_revision':live['deviceRevision']}
        return {'scene': anonymous_robot_snapshot(job, hash_token(f"{access_token}:{job['task_id']}"))}

    def get(self, order_id: uuid.UUID, access_token: str | None, *, include_progress: bool = True) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            orders = OrderRepository(connection)
            if not access_token:
                raise ServiceError(401, "missing order access token")
            order = orders.public_view(order_id)
            if order is None or not tokens_equal(order["access_token_hash"].strip(), hash_token(access_token)):
                raise ServiceError(404, "order not found")
            snapshot = self._payload(orders, PaymentRepository(connection), order)
            snapshot["queue"] = self._queue(orders, order)
        # Release the SQL connection before any Redis I/O.
        return self.with_live_progress(snapshot) if include_progress else snapshot

    def cancel(self, order_id: uuid.UUID, access_token: str | None) -> dict[str, Any]:
        intents_to_close: list[dict[str, Any]] = []
        repeat_cancel = False
        with self.uow.transaction() as connection:
            orders = OrderRepository(connection)
            payments = PaymentRepository(connection)
            order = self._authenticate(orders, order_id, access_token, for_update=True)
            if order["status"] == "CANCELLED":
                # Repeat cancellation returns the current state and never refunds twice.
                repeat_cancel = True
            if not repeat_cancel:
                if order["status"] not in {"CREATED", "AWAITING_PAYMENT", "QUEUED"}:
                    raise ServiceError(409, "only unpaid or queued orders can be cancelled safely")
                intents_to_close = payments.open_intents_for_order(order_id, for_update=True)
                if order["status"] == "QUEUED" and order["payment_status"] in REFUNDABLE_PAYMENT_STATUSES:
                    # Paid queued order: ensure the remaining money is refunded
                    # inside the same transaction. An already fully refunded or
                    # in-flight-covered budget is a successful no-op and must not
                    # block the cancellation.
                    payment_id = order.get("paid_payment_id")
                    if not payment_id:
                        fallback = payments.paid_for_order(order_id)
                        payment_id = fallback["id"] if fallback else None
                    if payment_id:
                        ensure_automatic_refund_intent(
                            connection, payment_id=payment_id,
                            idempotency_key=f"order:{order_id}:cancelled-order-refund",
                            reason="order cancelled before dispatch", actor="customer-cancel",
                        )
                transition_order(connection, order, "CANCELLED", "customer", reason="cancelled before dispatch")
                orders.cancel_job(order_id)
        if repeat_cancel:
            return self.get(order_id, access_token)
        # Closing open intents talks to the channel outside any database transaction.
        closed: list[tuple[dict[str, Any], Any]] = []
        for intent in intents_to_close:
            try:
                result = provider_for_payment(self.payment_provider, intent).close_payment(
                    intent["merchant_payment_no"]
                )
                closed.append((intent, result))
            except Exception as exc:
                log.warning(
                    "payment close deferred after order cancellation payment=%s: %s", intent["id"], exc
                )
        if closed:
            with self.uow.transaction() as connection:
                orders = OrderRepository(connection)
                payments = PaymentRepository(connection)
                # Same financial lock order: the order row first, then payment rows.
                order = orders.find(order_id, for_update=True)
                if order is not None:
                    for intent, result in closed:
                        current = payments.find(intent["id"], for_update=True)
                        if current and current["status"] in {"CREATED", "PENDING"}:
                            if getattr(result, "status", None) == "CLOSED":
                                transition_payment(
                                    connection, current, "CLOSED", actor="customer-cancel",
                                    payload=getattr(result, "raw", None) or {},
                                )
                            elif getattr(result, "status", None) == "PAID":
                                # Verified channel fact: record the money via the
                                # regular callback compensation path.
                                apply_paid_callback(
                                    connection, provider=intent["provider"],
                                    event_id=f"close-paid:{intent['merchant_payment_no']}",
                                    values={
                                        "merchant_payment_no": intent["merchant_payment_no"],
                                        "amount_minor": str(current["amount_minor"]),
                                        "provider_trade_no": getattr(result, "provider_trade_no", "") or "",
                                    },
                                )
                            else:
                                # UNKNOWN/PENDING/FAILED close results stay undecided;
                                # the reconciliation worker owns them.
                                payments.schedule_reconciliation(
                                    current["id"], self.settings.payment_reconcile_seconds
                                )
                    # Re-read: a PAID close result may have moved the projection
                    # to REFUNDING inside the loop above.
                    order = orders.find(order_id, for_update=True)
                    if not payments.open_intents_for_order(order_id) and order["payment_status"] in {
                        "NOT_STARTED", "PENDING"
                    }:
                        orders.update_payment_status(order_id, "CLOSED")
        return self.get(order_id, access_token)
