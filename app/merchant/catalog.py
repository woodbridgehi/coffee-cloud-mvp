from __future__ import annotations

from datetime import datetime

from .assets import MerchantAssets, LEGACY_TENANT
from .costs import money
from .security import MerchantError
from .service import now, text_field


def apply_merchant_catalog(connection, terminal, menu, payment_mode):
    """Apply tenant rules inside the order transaction before freezing price."""
    tenant_id=terminal.get('tenant_id')
    if not tenant_id or tenant_id==LEGACY_TENANT:return menu
    tenant=connection.execute('select status from merchant_tenant where id=%s',(tenant_id,)).fetchone()
    account=connection.execute("select id from merchant_payment_account where tenant_id=%s and is_default and status='VALIDATED'",(tenant_id,)).fetchone()
    for product in menu['products']:
        row=connection.execute("""select * from merchant_price where tenant_id=%s and sku=%s and effective_at<=now()
            and (terminal_id=%s and ownership_version=%s or terminal_id is null)
            and (store_id=%s or store_id is null)
            order by (terminal_id is not null) desc,(store_id is not null) desc,effective_at desc,created_at desc,id desc limit 1""",
            (tenant_id,product.get('skuCode') or product.get('recipeId'),terminal['id'],terminal['ownership_version'],terminal['merchant_store_id'])).fetchone()
        if row:product.update(priceMinor=row['price_minor'],priceVersion=str(row['id']))
        if not tenant or tenant['status']!='ACTIVE' or (payment_mode=='ONLINE' and not account):
            product['available']=False
            product['unavailableReasons']=sorted(set(product['unavailableReasons']+['MERCHANT_NOT_READY']))
    return menu


class MerchantCatalog:
    def __init__(self,service):
        self.service=service;self.assets=MerchantAssets(service)

    def prices(self,token,params,data=None,csrf=None,request_id=''):
        with self.service.scoped(token,'prices.manage' if data is not None else 'prices.read',csrf=csrf) as (c,p):
            if data is not None:
                store=self.assets.store(c,p,data['storeId']) if data.get('storeId') else None
                device=self.assets.device(c,p,data['deviceId']) if data.get('deviceId') else None
                if device and store and device['merchant_store_id']!=store['id']:raise MerchantError(409,'LOCATION_MISMATCH','设备与门店不匹配')
                try:
                    effective=datetime.fromisoformat(data['effectiveAt'].replace('Z','+00:00')) if data.get('effectiveAt') else now()
                    if effective.tzinfo is None:raise ValueError()
                except (ValueError,TypeError,AttributeError):raise MerchantError(422,'INVALID_DATE','生效时间必须包含时区') from None
                row=c.execute("""insert into merchant_price(tenant_id,sku,store_id,terminal_id,ownership_version,price_minor,effective_at)
                    values(%s,%s,%s,%s,%s,%s,%s) returning *""",(p['tenant_id'],text_field(data,'sku',128),store['id'] if store else None,
                    device['id'] if device else None,device['ownership_version'] if device else None,money(data.get('priceMinor')),effective)).fetchone()
                self.service.audit(c,p,'price.create','price',row['sku'],request_id);rows=[row]
            else:
                rows=c.execute('select * from merchant_price where tenant_id=%s order by effective_at desc,created_at desc,id',(p['tenant_id'],)).fetchall()
            result=[{'id':str(r['id']),'sku':r['sku'],'name':r['sku'],'storeId':str(r['store_id']) if r['store_id'] else None,
                     'deviceId':str(r['terminal_id']) if r['terminal_id'] else None,'priceMinor':r['price_minor'],'effectiveAt':r['effective_at'],'version':r['version']}
                    for r in rows if (not r['store_id'] or self.service.store_allowed(p,r['store_id']))
                    and (not params.get('storeId') or str(r['store_id'])==params['storeId'])
                    and (not params.get('deviceId') or str(r['terminal_id'])==params['deviceId'])]
            return result[0] if data is not None else result
