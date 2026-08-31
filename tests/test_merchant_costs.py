from datetime import datetime, timezone

import psycopg
import pytest

from app.merchant.costs import MerchantCosts
from app.merchant.reports import MerchantReports
from app.merchant.security import MerchantError
from test_merchant_identity import merchant, account, email_token, PASSWORD
from test_merchant_assets import terminal, claim


def setup_stock(service):
    session, token = account(service)
    device = terminal(service)
    owned, _ = claim(service, session, token, device)
    store_id = service.stores(token)[0]['id']
    costs = MerchantCosts(service)
    material = costs.materials(token, {'name': 'Coffee beans', 'externalId': 'beans', 'unit': 'g'}, session['csrfToken'])
    purchase = costs.save_purchase(token, {'storeId': store_id, 'purchasedOn': '2026-08-31',
        'lines': [{'materialId': material['id'], 'quantity': '3', 'totalCostMinor': 100}]},
        session['csrfToken'], 'purchase-1', 'test')
    costs.post_purchase(token, purchase['id'], {'version': 1}, session['csrfToken'], 'test')
    return costs, session, token, store_id, material, owned, purchase


def test_inventory_value_is_conserved_and_post_is_idempotent(merchant):
    costs, session, token, store, material, device, purchase = setup_stock(merchant)
    costs.post_purchase(token, purchase['id'], {'version': 1}, session['csrfToken'], 'retry')
    data = {'type': 'RESTOCK', 'materialId': material['id'], 'quantity': '1',
            'sourceStoreId': store, 'targetDeviceId': device['id'], 'reason': 'Load machine'}
    costs.movement(token, data, session['csrfToken'], 'load-1', 'test')
    costs.movement(token, data, session['csrfToken'], 'load-1', 'test')
    with merchant.database.connect() as c:
        rows = c.execute('select quantity,value_minor from merchant_stock order by value_minor').fetchall()
        assert [(str(r['quantity']), r['value_minor']) for r in rows] == [('1.000000', 33), ('2.000000', 67)]
    costs.movement(token, {**data, 'quantity': '2'}, session['csrfToken'], 'load-2', 'test')
    with merchant.database.connect() as c:
        rows = c.execute('select quantity,value_minor from merchant_stock order by value_minor').fetchall()
        assert [(str(r['quantity']), r['value_minor']) for r in rows] == [('0.000000', 0), ('3.000000', 100)]
    machine_stock = next(r for r in costs.inventory(token, {}) if r['deviceId'])
    assert machine_stock['reservedQuantity'] is None and machine_stock['availableQuantity'] is None
    with pytest.raises(MerchantError) as error:
        costs.movement(token, data, session['csrfToken'], 'load-3', 'test')
    assert error.value.code == 'INSUFFICIENT_STOCK'


def test_expense_allocation_cents_and_append_only_reversal(merchant):
    session, token = account(merchant)
    costs, reports = MerchantCosts(merchant), MerchantReports(merchant)
    expense = costs.create_expense(token, {'category': 'RENT', 'allocationMethod': 'DAILY_EQUAL',
        'amountMinor': 100, 'occurredOn': '2026-08-31', 'allocationStart': '2026-08-31', 'allocationEnd': '2026-09-02'},
        session['csrfToken'], 'rent', 'test')
    costs.expense_action(token, expense['id'], {'version': 1}, session['csrfToken'], 'test')
    params = {'from': '2026-08-31', 'to': '2026-09-03', 'environment': 'LIVE'}
    report = reports.operating(token, params)
    assert [row['operatingExpenseMinor'] for row in report['rows']] == [34, 33, 33]
    monthly = reports.operating(token, {**params, 'grain': 'MONTH'})
    assert [row['operatingExpenseMinor'] for row in monthly['rows']] == [34, 66]
    assert monthly['totals']['estimatedProfitMinor'] == -100
    costs.expense_action(token, expense['id'], {'reason': 'Correction'}, session['csrfToken'], 'test', reverse=True)
    costs.expense_action(token, expense['id'], {'reason': 'Correction'}, session['csrfToken'], 'retry', reverse=True)
    assert reports.operating(token, params)['totals']['operatingExpenseMinor'] == 0
    with merchant.database.connect() as c:
        assert c.execute('select count(*) as n from merchant_ledger').fetchone()['n'] == 6
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute('delete from merchant_ledger')


def test_reports_timezone_environment_and_unknown_cost(merchant):
    session, token = account(merchant)
    costs, reports = MerchantCosts(merchant), MerchantReports(merchant)
    with merchant.identity(token) as (c, p):
        for key, kind, amount, environment, hour in [
            ('prior', 'COLLECTION', 900, 'LIVE', 15),
            ('live', 'COLLECTION', 100, 'LIVE', 16),
            ('mock', 'COLLECTION', 300, 'TEST', 16),
            ('missing', 'MATERIAL', None, 'LIVE', 16),
        ]:
            costs.ledger(c, p, kind, amount, key, datetime(2026, 8, 30, hour, tzinfo=timezone.utc), environment=environment)
    params = {'from': '2026-08-31', 'to': '2026-09-01', 'environment': 'LIVE'}
    report = reports.operating(token, params)
    assert report['totals']['receivedMinor'] == 100
    assert report['totals']['estimatedProfitMinor'] is None
    assert report['completeness']['status'] == 'INCOMPLETE'
    assert reports.operating(token, {**params, 'environment': 'TEST'})['totals']['receivedMinor'] == 300
    assert reports.csv(token, params).startswith('\ufeff期间,')


def test_selected_store_finance_report_does_not_leak_or_write_global_cache(merchant):
    session, token = account(merchant)
    stores = [merchant.save_store(token, {'name': name}, session['csrfToken'], 'test') for name in ['A', 'B']]
    merchant.invite(token, {'email': 'finance@test.invalid', 'role': 'FINANCE',
        'storeScope': {'mode': 'SELECTED', 'storeIds': [stores[0]['id']]}}, session['csrfToken'], 'test')
    merchant.accept_invitation(None, {'token': email_token(merchant, 'finance@test.invalid'),
        'password': PASSWORD, 'displayName': 'Finance'}, 'ip')
    _, finance_token = merchant.login({'email': 'finance@test.invalid', 'password': PASSWORD}, 'ip')
    with merchant.identity(token) as (c, p):
        for store, amount in zip(stores, [100, 900]):
            MerchantCosts.ledger(c, p, 'COLLECTION', amount, store['id'], datetime(2026, 8, 31, tzinfo=timezone.utc),
                                 store_id=store['id'], environment='LIVE')
    report = MerchantReports(merchant).operating(finance_token, {'from': '2026-08-31', 'to': '2026-09-01'})
    assert report['totals']['receivedMinor'] == 100
    with merchant.database.connect() as c:
        assert c.execute('select count(*) as n from merchant_daily_summary').fetchone()['n'] == 0
