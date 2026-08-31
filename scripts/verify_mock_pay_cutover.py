"""Explicit deployment smoke: isolated suspended terminal, real HTTP payment and refund.

Run inside the coffee API container with --run. Leaves audited test records; never
targets an existing terminal, creates device credentials, or permits dispensing.
"""
import argparse
import json
import os
import secrets
import time
import uuid
from urllib.parse import urlsplit

import httpx
import psycopg
from psycopg.rows import dict_row

from app.repositories import OrderRepository
from app.security import hash_token


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("Pass --run to create an isolated simulated payment test order")
    assert os.environ.get("PAYMENT_DEFAULT_PROVIDER") == "alipay_mock"
    base = "https://coffee-api.woodbridge.top"
    gateway = "https://mock-pay.woodbridge.top"
    run = "QA-MOCK-" + uuid.uuid4().hex[:12].upper()
    order_id = uuid.uuid4()
    token = secrets.token_urlsafe(32)
    with httpx.Client(timeout=20, trust_env=False) as http:
        health = http.get(gateway + "/health")
        health.raise_for_status()
        assert health.json()["mode"] == "simulation"
        with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as db:
            terminal_id = db.execute(
                """INSERT INTO terminal(device_id,serial_number,lifecycle_status,connection_status)
                   VALUES(%s,%s,'SUSPENDED','offline') RETURNING id""", (run, run)
            ).fetchone()["id"]
            orders = OrderRepository(db)
            orders.insert(
                order_id=order_id, order_no=run, terminal_id=terminal_id,
                access_token_hash=hash_token(token), idempotency_key=run, request_digest=hash_token(run),
                order_status="CREATED", payment_mode="ONLINE", payment_status="NOT_STARTED",
                product={"currency": "CNY", "priceMinor": 100, "recipeId": "deployment-verification",
                         "recipeVersion": "1", "skuCode": "QA", "name": "Mock支付切换验收（无设备制作）"},
            )
            orders.insert_initial_transition(order_id, "CREATED", "isolated mock-pay cutover verification", {"run": run})
        print(json.dumps({"test_order": str(order_id), "test_terminal": run}), flush=True)
        auth = {"X-Order-Access-Token": token}
        response = http.post(base + f"/api/v1/orders/{order_id}/payments",
                             headers={**auth, "Idempotency-Key": run}, json={})
        response.raise_for_status()
        payment = response.json()
        assert payment["provider"] == "alipay_mock"
        assert urlsplit(payment["qrCode"]).hostname == "mock-pay.woodbridge.top"
        payment_id = payment["paymentId"]
        qr = http.get(base + f"/api/v1/payments/{payment_id}/qr", headers=auth)
        qr.raise_for_status()
        assert qr.headers["content-type"] == "image/png"
        pay_token = payment["qrCode"].rsplit("/", 1)[-1]
        details = http.get(gateway + "/api/pay/" + pay_token)
        details.raise_for_status()
        for _ in range(2):
            paid = http.post(gateway + "/api/pay/" + pay_token + "/confirm",
                             headers={"Origin": gateway}, json={"csrf_token": details.json()["csrf_token"]})
            paid.raise_for_status()

        def wait_for(check, description, seconds=60):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                value = check()
                if value:
                    return value
                time.sleep(0.5)
            raise RuntimeError("Timed out: " + description)

        def query(sql, params):
            with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as db:
                return db.execute(sql, params).fetchone()

        wait_for(lambda: query("SELECT 1 FROM payment_callback_inbox WHERE payment_id=%s AND provider='alipay_mock' AND status='PROCESSED'", (payment_id,)), "signed public callback")
        wait_for(lambda: query("SELECT 1 FROM sales_order WHERE id=%s AND status='QUEUED' AND payment_status='PAID'", (order_id,)), "paid order queue projection")
        cancel = http.post(base + f"/api/v1/public/orders/{order_id}/cancel", headers=auth)
        cancel.raise_for_status()
        wait_for(lambda: query("SELECT 1 FROM payment WHERE id=%s AND status='REFUNDED'", (payment_id,)), "automatic cancellation refund", 90)
        refunds = query("SELECT count(*) n, sum(amount_minor) amount FROM refund WHERE payment_id=%s AND provider='alipay_mock' AND status='SUCCEEDED'", (payment_id,))
        callbacks = query("SELECT count(*) n FROM payment_callback_inbox WHERE payment_id=%s", (payment_id,))
        commands = query("SELECT count(*) n FROM terminal_command WHERE terminal_id=%s", (terminal_id,))
        assert refunds == {"n": 1, "amount": 100}
        assert callbacks["n"] == 1 and commands["n"] == 0
        print(json.dumps({"result": "PASS", "order_id": str(order_id), "provider": payment["provider"],
                          "payment_url_host": urlsplit(payment["qrCode"]).hostname,
                          "callback_count": callbacks["n"], "refund_minor": refunds["amount"],
                          "device_commands": commands["n"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
