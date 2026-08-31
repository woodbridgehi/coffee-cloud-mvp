from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from .assets import MerchantAssets
from .orders import period
from .security import MerchantError, PERMISSIONS
from .service import identifier, now, text_field


def quantity(value, *, signed=False, precision=6):
    pattern=r'-?\d{1,15}(?:\.\d{1,6})?' if signed else r'\d{1,15}(?:\.\d{1,6})?'
    if not isinstance(value,str) or not re.fullmatch(pattern,value):
        raise MerchantError(422,'INVALID_QUANTITY','数量须为有效十进制字符串，最多6位小数')
    parsed=Decimal(value)
    if parsed==0 or (not signed and parsed<0) or -parsed.as_tuple().exponent>precision:
        raise MerchantError(422,'INVALID_QUANTITY','数量不能为零，且须符合物料单位精度')
    return parsed


def money(value, *, positive=True):
    if type(value) is not int or value< (1 if positive else 0) or value>10**12:
        raise MerchantError(422,'INVALID_AMOUNT','金额须为有效整数分')
    return value


def day(value):
    try:return date.fromisoformat(value)
    except (ValueError,TypeError):raise MerchantError(422,'INVALID_DATE','日期格式须为 YYYY-MM-DD') from None


class MerchantCosts:
    def __init__(self,service):
        self.service=service
        self.assets=MerchantAssets(service)

    def material(self,c,p,material_id):
        row=c.execute('select * from merchant_material where id=%s and tenant_id=%s',(identifier(material_id),p['tenant_id'])).fetchone()
        if not row:raise MerchantError(404,'NOT_FOUND','物料不存在或无访问权限')
        return row

    def materials(self,token,data=None,csrf=None,request_id=''):
        with self.service.scoped(token,'costs.manage' if data is not None else 'inventory.read',csrf=csrf) as (c,p):
            if data is not None:
                precision=data.get('unitPrecision',3)
                if type(precision) is not int or not 0<=precision<=6:raise MerchantError(422,'INVALID_PRECISION','单位精度范围为0至6')
                name=text_field(data,'name');unit=text_field(data,'unit',24)
                external=text_field(data,'externalId',128,default=name)
                row=c.execute("""insert into merchant_material(tenant_id,external_id,name,unit,unit_precision)
                    values(%s,%s,%s,%s,%s) on conflict(tenant_id,external_id) do nothing returning *""",(p['tenant_id'],external,name,unit,precision)).fetchone()
                if not row:raise MerchantError(409,'MATERIAL_EXISTS','同一设备物料编码已存在')
                self.service.audit(c,p,'material.create','material',name,request_id)
                rows=[row]
            else:
                rows=c.execute('select * from merchant_material where tenant_id=%s order by name,id',(p['tenant_id'],)).fetchall()
            result=[]
            for row in rows:
                average=None
                if 'costs.read' in PERMISSIONS[p['role']]:
                    value=c.execute("""select sum(value_minor) as amount,sum(quantity) as quantity,count(*) filter(where value_minor is null and quantity>0) as missing
                        from merchant_stock where tenant_id=%s and material_id=%s""",(p['tenant_id'],row['id'])).fetchone()
                    if value['quantity'] and not value['missing']:average=str(Decimal(value['amount'])/value['quantity'])
                result.append({'id':str(row['id']),'externalId':row['external_id'],'name':row['name'],'unit':row['unit'],
                    'unitPrecision':row['unit_precision'],'status':row['status'],'averageUnitCostMinor':average})
            return result[0] if data is not None else result

    def location(self,c,p,store_id,device_id=None):
        if device_id:
            device=self.assets.device(c,p,device_id)
            if store_id and str(device['merchant_store_id'])!=str(store_id):raise MerchantError(409,'LOCATION_MISMATCH','设备不属于所选门店')
            store_id=device['merchant_store_id']
            if not store_id:raise MerchantError(409,'STORE_REQUIRED','请先给设备分配门店')
            return {'key':'DEVICE:'+str(device['id']),'store_id':store_id,'terminal_id':device['id']}
        store=self.assets.store(c,p,store_id)
        return {'key':'STORE:'+str(store['id']),'store_id':store['id'],'terminal_id':None}

    @staticmethod
    def stock(c,p,material,loc):
        c.execute("""insert into merchant_stock(tenant_id,material_id,location_key,store_id,terminal_id,quantity,value_minor)
            values(%s,%s,%s,%s,%s,0,0) on conflict do nothing""",(p['tenant_id'],material['id'],loc['key'],loc['store_id'],loc['terminal_id']))
        return c.execute('select * from merchant_stock where tenant_id=%s and material_id=%s and location_key=%s for update',
                         (p['tenant_id'],material['id'],loc['key'])).fetchone()

    def move(self,c,p,material,loc,qty,kind,key,reason,occurred,*,incoming_cost=None):
        stock=self.stock(c,p,material,loc)
        before=stock['quantity'];after=before+qty
        if after<0:raise MerchantError(409,'INSUFFICIENT_STOCK','库存不足，请核对补货和采购记录')
        unit_cost=Decimal(stock['value_minor'])/before if before and stock['value_minor'] is not None else None
        if qty<0:
            cost=stock['value_minor'] if after==0 else int((-qty*unit_cost).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) if unit_cost is not None else None
            remaining=stock['value_minor']-cost if stock['value_minor'] is not None and cost is not None else None
            if after==0:remaining=0
        else:
            cost=incoming_cost
            remaining=(stock['value_minor']+cost) if stock['value_minor'] is not None and cost is not None else None
            unit_cost=Decimal(cost)/qty if cost is not None else None
        c.execute('update merchant_stock set quantity=%s,value_minor=%s,version=version+1,last_event_at=greatest(last_event_at,%s) where id=%s',
                  (after,remaining,occurred,stock['id']))
        row=c.execute("""insert into merchant_inventory_movement(tenant_id,material_id,store_id,terminal_id,location_key,type,quantity,
            amount_minor,unit_cost_minor,source_key,reason,occurred_at) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *""",
            (p['tenant_id'],material['id'],loc['store_id'],loc['terminal_id'],loc['key'],kind,qty,cost,unit_cost,key,reason,occurred)).fetchone()
        return row,cost

    @staticmethod
    def ledger(c,p,kind,amount,key,occurred,*,store_id=None,terminal_id=None,order_id=None,environment=None,basis='ACTUAL',detail=None):
        environment=environment or ('TEST' if p.get('environment')=='INTERNAL_TEST' else 'LIVE')
        c.execute("""insert into merchant_ledger(tenant_id,store_id,terminal_id,order_id,kind,amount_minor,environment,source_key,occurred_at,basis,detail)
            values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict(tenant_id,source_key) do nothing""",
            (p['tenant_id'],store_id,terminal_id,order_id,kind,amount,environment,key,occurred,basis,Jsonb(detail or {})))

    def _purchase_lines(self,c,p,data):
        lines=data.get('lines')
        if not isinstance(lines,list) or not 1<=len(lines)<=100:raise MerchantError(422,'INVALID_LINES','采购单须包含1至100行物料')
        result=[]
        for line in lines:
            if not isinstance(line,dict):raise MerchantError(422,'INVALID_LINES','采购行格式错误')
            material=self.material(c,p,line.get('materialId'))
            qty=quantity(line.get('quantity'),precision=material['unit_precision'])
            result.append({'materialId':str(material['id']),'name':material['name'],'unit':material['unit'],
                           'quantity':str(qty),'totalCostMinor':money(line.get('totalCostMinor'))})
        return result

    @staticmethod
    def purchase_payload(row):
        return {'id':str(row['id']),'storeId':str(row['store_id']),'purchasedOn':row['purchased_on'],'supplier':row['supplier'],
                'note':row['note'],'lines':row['lines'],'status':row['status'],'version':row['version'],
                'totalCostMinor':sum(x['totalCostMinor'] for x in row['lines']),'createdAt':row['created_at']}

    def purchases(self,token,params):
        with self.service.scoped(token,'costs.read') as (c,p):
            start,end=period(p,params)
            rows=c.execute('select * from merchant_purchase where tenant_id=%s and purchased_on>=%s and purchased_on<%s order by purchased_on desc,id',
                           (p['tenant_id'],start.date(),end.date())).fetchall()
            return [self.purchase_payload(r) for r in rows if self.service.store_allowed(p,r['store_id']) and (not params.get('storeId') or str(r['store_id'])==params['storeId'])]

    def save_purchase(self,token,data,csrf,key,request_id,purchase_id=None):
        with self.service.scoped(token,'costs.manage',csrf=csrf) as (c,p):
            def execute():
                store=self.assets.store(c,p,data.get('storeId'));lines=self._purchase_lines(c,p,data)
                purchased=day(data.get('purchasedOn'))
                supplier=str(data.get('supplier',''))[:160];note=str(data.get('note',''))[:1000]
                if purchase_id:
                    old=c.execute('select * from merchant_purchase where id=%s and tenant_id=%s for update',(identifier(purchase_id),p['tenant_id'])).fetchone()
                    if not old:raise MerchantError(404,'NOT_FOUND','采购单不存在或无访问权限')
                    self.service.check_version(old,data)
                    if old['status']!='DRAFT':raise MerchantError(409,'NOT_DRAFT','已入账采购不能直接修改')
                    row=c.execute('update merchant_purchase set store_id=%s,purchased_on=%s,supplier=%s,note=%s,lines=%s,version=version+1 where id=%s returning *',
                                  (store['id'],purchased,supplier,note,Jsonb(lines),old['id'])).fetchone()
                else:
                    row=c.execute('insert into merchant_purchase(tenant_id,store_id,purchased_on,supplier,note,lines) values(%s,%s,%s,%s,%s,%s) returning *',
                                  (p['tenant_id'],store['id'],purchased,supplier,note,Jsonb(lines))).fetchone()
                self.service.audit(c,p,'purchase.save','purchase',str(row['id']),request_id)
                return self.purchase_payload(row)
            return execute() if purchase_id else self.assets.idempotent(c,p,'purchase.create',key,data,execute)

    def post_purchase(self,token,purchase_id,data,csrf,request_id):
        with self.service.scoped(token,'costs.manage',csrf=csrf) as (c,p):
            c.execute('select pg_advisory_xact_lock(hashtextextended(%s,0))',('inventory:'+str(p['tenant_id']),))
            row=c.execute('select * from merchant_purchase where id=%s and tenant_id=%s for update',(identifier(purchase_id),p['tenant_id'])).fetchone()
            if not row:raise MerchantError(404,'NOT_FOUND','采购单不存在或无访问权限')
            if row['status']=='POSTED':return self.purchase_payload(row)
            self.service.check_version(row,data)
            loc=self.location(c,p,row['store_id'])
            for index,line in enumerate(row['lines']):
                material=self.material(c,p,line['materialId'])
                # Enter inventory now; purchase document date does not rewrite
                # the cost basis used for already-consumed historical stock.
                self.move(c,p,material,loc,Decimal(line['quantity']),'PURCHASE',f'purchase:{row["id"]}:{index}',row['note'],now(),incoming_cost=line['totalCostMinor'])
            row=c.execute("update merchant_purchase set status='POSTED',posted_at=now(),version=version+1 where id=%s returning *",(row['id'],)).fetchone()
            self.service.audit(c,p,'purchase.post','purchase',str(row['id']),request_id)
            return self.purchase_payload(row)

    def inventory(self,token,params,*,movements=False):
        with self.service.scoped(token,'inventory.read') as (c,p):
            if movements:
                start,end=period(p,params)
                rows=c.execute("""select x.*,m.name,m.unit from merchant_inventory_movement x join merchant_material m on m.id=x.material_id
                    where x.tenant_id=%s and x.occurred_at>=%s and x.occurred_at<%s order by x.occurred_at desc,x.id""",(p['tenant_id'],start,end)).fetchall()
            else:
                rows=c.execute("""select x.*,m.name,m.unit from merchant_stock x join merchant_material m on m.id=x.material_id
                    where x.tenant_id=%s order by m.name,x.location_key""",(p['tenant_id'],)).fetchall()
            result=[]
            for row in rows:
                if not self.service.store_allowed(p,row['store_id']):continue
                if params.get('storeId') and str(row['store_id'])!=params['storeId']:continue
                if params.get('deviceId') and str(row['terminal_id'])!=params['deviceId']:continue
                if movements and params.get('type') and row['type']!=params['type']:continue
                item={'id':str(row['id']),'materialId':str(row['material_id']),'name':row['name'],'unit':row['unit'],
                      'storeId':str(row['store_id']),'deviceId':str(row['terminal_id']) if row['terminal_id'] else None,
                      'version':row.get('version')}
                if movements:
                    item.update(type=row['type'],quantity=str(row['quantity']),sourceKey=row['source_key'],reason=row['reason'],occurredAt=row['occurred_at'])
                    if 'costs.read' in PERMISSIONS[p['role']]:item['amountMinor']=row['amount_minor']
                else:
                    # Device reservations live in telemetry. The accounting
                    # stock book alone cannot establish the available quantity.
                    item.update(onHandQuantity=str(row['quantity']),
                                reservedQuantity=None if row['terminal_id'] else '0',
                                availableQuantity=None if row['terminal_id'] else str(row['quantity']),
                                quantitySource='BOOK',
                                costStatus='KNOWN' if row['value_minor'] is not None else 'UNKNOWN')
                result.append(item)
            return result

    def movement(self,token,data,csrf,key,request_id):
        kind=data.get('type')
        if kind not in ('RESTOCK','WASTE','ADJUSTMENT','TRANSFER'):raise MerchantError(422,'INVALID_MOVEMENT','无效出入库类型')
        with self.service.scoped(token,'inventory.manage',csrf=csrf) as (c,p):
            c.execute('select pg_advisory_xact_lock(hashtextextended(%s,0))',('inventory:'+str(p['tenant_id']),))
            def execute():
                material=self.material(c,p,data.get('materialId'))
                qty=quantity(data.get('quantity'),signed=kind=='ADJUSTMENT',precision=material['unit_precision'])
                reason=text_field(data,'reason',500);stamp=now();source_key='movement:'+str(uuid.uuid4())
                source=self.location(c,p,data.get('sourceStoreId'),data.get('sourceDeviceId'))
                if kind in ('TRANSFER','RESTOCK'):
                    target=self.location(c,p,data.get('targetStoreId'),data.get('targetDeviceId'))
                    if target['key']==source['key']:raise MerchantError(422,'SAME_LOCATION','来源与目标不能相同')
                    out,cost=self.move(c,p,material,source,-qty,kind,source_key,reason,stamp)
                    row,_=self.move(c,p,material,target,qty,kind,source_key,reason,stamp,incoming_cost=cost)
                else:
                    qty=-qty if kind=='WASTE' else qty
                    row,cost=self.move(c,p,material,source,qty,kind,source_key,reason,stamp)
                    if qty<0:
                        self.ledger(c,p,'WASTE',cost,source_key,stamp,store_id=source['store_id'],terminal_id=source['terminal_id'],basis='ACTUAL' if cost is not None else 'UNKNOWN')
                self.service.audit(c,p,'inventory.'+kind.lower(),'material',material['name'],request_id)
                return {'id':str(row['id']),'type':kind,'quantity':str(row['quantity']),'occurredAt':stamp}
            return self.assets.idempotent(c,p,'inventory.movement',key,data,execute)

    @staticmethod
    def expense_payload(r):
        return {'id':str(r['id']),'storeId':str(r['store_id']) if r['store_id'] else None,'deviceId':str(r['terminal_id']) if r['terminal_id'] else None,
                'category':r['category'],'amountMinor':r['amount_minor'],'occurredOn':r['occurred_on'],'allocationStart':r['allocation_start'],
                'allocationEnd':r['allocation_end'],'allocationMethod':r['allocation_method'],'note':r['note'],'status':r['status'],'version':r['version']}

    def expenses(self,token,params):
        with self.service.scoped(token,'costs.read') as (c,p):
            start,end=period(p,params)
            rows=c.execute('''select * from merchant_expense where tenant_id=%s and coalesce(allocation_end,occurred_on)>=%s
                and coalesce(allocation_start,occurred_on)<%s order by occurred_on desc,id''',(p['tenant_id'],start.date(),end.date())).fetchall()
            return [self.expense_payload(r) for r in rows if self.service.store_allowed(p,r['store_id']) and (not params.get('storeId') or str(r['store_id'])==params['storeId'])]

    def create_expense(self,token,data,csrf,key,request_id):
        with self.service.scoped(token,'costs.manage',csrf=csrf) as (c,p):
            def execute():
                category=data.get('category');method=data.get('allocationMethod')
                if category not in ('RENT','LABOR','UTILITIES','MAINTENANCE','OTHER') or method not in ('ONCE','DAILY_EQUAL'):
                    raise MerchantError(422,'INVALID_EXPENSE','费用类别或分摊方式无效')
                amount=money(data.get('amountMinor'));occurred=day(data.get('occurredOn'))
                start=day(data.get('allocationStart')) if method=='DAILY_EQUAL' else None
                end=day(data.get('allocationEnd')) if method=='DAILY_EQUAL' else None
                if start and not 0<=(end-start).days<3660:raise MerchantError(422,'INVALID_PERIOD','分摊区间无效，最长10年')
                loc=self.location(c,p,data.get('storeId'),data.get('deviceId')) if data.get('storeId') or data.get('deviceId') else None
                row=c.execute('''insert into merchant_expense(tenant_id,store_id,terminal_id,category,amount_minor,occurred_on,allocation_start,allocation_end,allocation_method,note)
                    values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *''',(p['tenant_id'],loc['store_id'] if loc else None,loc['terminal_id'] if loc else None,
                    category,amount,occurred,start,end,method,str(data.get('note',''))[:1000])).fetchone()
                self.service.audit(c,p,'expense.create','expense',str(row['id']),request_id)
                return self.expense_payload(row)
            return self.assets.idempotent(c,p,'expense.create',key,data,execute)

    def expense_action(self,token,expense_id,data,csrf,request_id,*,reverse=False):
        with self.service.scoped(token,'costs.manage',csrf=csrf) as (c,p):
            row=c.execute('select * from merchant_expense where id=%s and tenant_id=%s for update',(identifier(expense_id),p['tenant_id'])).fetchone()
            if not row or not self.service.store_allowed(p,row['store_id']):raise MerchantError(404,'NOT_FOUND','费用不存在或无访问权限')
            if reverse:
                text_field(data,'reason',500)
                if row['status']=='REVERSED':return self.expense_payload(row)
                if row['status']!='POSTED':raise MerchantError(409,'BAD_STATE','仅已入账费用可以冲正')
            else:
                if row['status']=='POSTED':return self.expense_payload(row)
                self.service.check_version(row,data)
                if row['status']!='DRAFT':raise MerchantError(409,'NOT_DRAFT','费用不是草稿')
            first=row['allocation_start'] or row['occurred_on'];last=row['allocation_end'] or first
            count=(last-first).days+1;each,remainder=divmod(row['amount_minor'],count)
            for index in range(count):
                value=each+(1 if index<remainder else 0)
                stamp=datetime.combine(first+timedelta(days=index),time.min,ZoneInfo(p['timezone']))
                self.ledger(c,p,'EXPENSE_REVERSAL' if reverse else 'EXPENSE',value,
                    ('expense-reversal:' if reverse else 'expense:')+str(row['id'])+':'+str(index),stamp,
                    store_id=row['store_id'],terminal_id=row['terminal_id'],detail={'category':row['category'],'reason':data.get('reason','')})
            row=c.execute('update merchant_expense set status=%s,posted_at=coalesce(posted_at,now()),version=version+1 where id=%s returning *',
                          ('REVERSED' if reverse else 'POSTED',row['id'])).fetchone()
            self.service.audit(c,p,'expense.reverse' if reverse else 'expense.post','expense',str(row['id']),request_id)
            return self.expense_payload(row)
