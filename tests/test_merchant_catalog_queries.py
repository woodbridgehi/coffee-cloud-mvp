import pytest
from app.merchant.catalog import MerchantCatalog, apply_merchant_catalog
from app.merchant.security import MerchantError
from test_merchant_identity import merchant, account
from test_merchant_assets import terminal, claim


def test_prices_paginate_filter_and_keep_tenant_isolation(merchant):
    session, token = account(merchant)
    device = terminal(merchant)
    owned, _ = claim(merchant, session, token, device)
    catalog = MerchantCatalog(merchant)
    for price in [100, 200, 300]:
        catalog.prices(token, {}, {'sku': 'LATTE', 'priceMinor': price}, session['csrfToken'])
    catalog.prices(token, {}, {'sku': 'LATTE', 'priceMinor': 400, 'deviceId': owned['id']}, session['csrfToken'])
    first = catalog.prices(token, {'limit': '2'})
    second = catalog.prices(token, {'limit': '2', 'offset': '2'})
    assert len(first) == len(second) == 2
    assert not ({r['id'] for r in first} & {r['id'] for r in second})
    assert len(catalog.prices(token, {'deviceId': owned['id']})) == 1
    with pytest.raises(MerchantError): catalog.prices(token, {'limit': '201'})
    _, other_token = account(merchant, 'another@test.invalid')
    assert catalog.prices(other_token, {}) == []
    with pytest.raises(MerchantError): catalog.prices(other_token, {'deviceId': owned['id']})
    with merchant.database.connect() as c:
        current = c.execute('select * from terminal where id=%s', (device['id'],)).fetchone()
        class CountQueries:
            calls = 0
            def execute(self, *args, **kwargs):
                self.calls += 1
                return c.execute(*args, **kwargs)
        counted = CountQueries()
        menu = {'products': [{'skuCode': 'LATTE', 'available': True, 'unavailableReasons': []},
                             {'skuCode': 'NO_OVERRIDE', 'available': True, 'unavailableReasons': []}]}
        result = apply_merchant_catalog(counted, current, menu, 'TEST_FREE')
        assert counted.calls == 3
        assert result['products'][0]['priceMinor'] == 400
        assert 'priceMinor' not in result['products'][1]
        c.execute("""insert into merchant_price(tenant_id,sku,price_minor,effective_at)
            select %s,'SKU-'||n,100,now()-n*interval '1 second' from generate_series(1,20000) n""",
            (current['tenant_id'],))
        c.execute('analyze merchant_price')
        plan = c.execute("""explain (analyze,format json) select * from merchant_price
            where tenant_id=%s order by effective_at desc,created_at desc,id limit 100""",
            (current['tenant_id'],)).fetchone()['QUERY PLAN'][0]
        assert 'ix_merchant_price_page' in str(plan)
