from __future__ import annotations

import base64
import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .assets import MerchantAssets
from .security import MerchantError, PERMISSIONS
from .service import identifier, now, text_field
from ..services.refund_intents import create_refund_intent


def period(p, params):
    zone = ZoneInfo(p['timezone'])
    today = now().astimezone(zone).date()
    try:
        start = date.fromisoformat(params.get('from') or (today-timedelta(days=6)).isoformat())
        end = date.fromisoformat(params.get('to') or (today+timedelta(days=1)).isoformat())
        if not 0 < (end-start).days <= 3660: raise ValueError()
    except (ValueError, TypeError):
        raise MerchantError(422,'INVALID_PERIOD','日期范围无效，最多查询10年') from None
    return datetime.combine(start,time.min,zone), datetime.combine(end,time.min,zone)


def cursor_encode(row):
    return base64.urlsafe_b64encode(json.dumps([row['created_at'].isoformat(),str(row['id'])]).encode()).decode()


def cursor_decode(value):
    try:
        if not isinstance(value,str) or len(value)>300: raise ValueError()
        stamp, row_id = json.loads(base64.urlsafe_b64decode(value))
        when=datetime.fromisoformat(stamp)
        if not when.tzinfo: raise ValueError()
        return when, identifier(row_id)
    except (ValueError,TypeError,KeyError):
        raise MerchantError(422,'INVALID_CURSOR','分页参数无效') from None


class MerchantOrders:
    def __init__(self, service):
        self.service=service
        self.assets=MerchantAssets(service)

    def find(self,c,p,order_id,lock=False):
        row=c.execute('select * from sales_order where id=%s and tenant_id=%s'+(' for update' if lock else ''),
                      (identifier(order_id),p['tenant_id'])).fetchone()
        if not row or not self.service.store_allowed(p,row['merchant_store_id']):
            raise MerchantError(404,'NOT_FOUND','订单不存在或无访问权限')
        return row

    def payload(self,c,p,row,detail=False):
        amounts=c.execute("""select coalesce(sum(case when paid_at is not null then amount_minor else 0 end),0) as received,
            coalesce((select sum(r.amount_minor) from refund r join payment p on p.id=r.payment_id
                      where p.order_id=%s and r.status='SUCCEEDED'),0) as refunded
            from payment where order_id=%s""",(row['id'],row['id'])).fetchone()
        actions=['REFUND'] if 'refunds.manage' in PERMISSIONS[p['role']] and row['paid_payment_id'] and row['payment_status'] in ('PAID','PARTIALLY_REFUNDED') else []
        result={'id':str(row['id']),'orderNo':row['order_no'],'createdAt':row['created_at'],'deliveredAt':row['completed_at'] if row['status']=='READY' else None,
                'storeNameSnapshot':row['store_name_snapshot'],'deviceNameSnapshot':row['device_name_snapshot'],
                'items':[{'name':row['product_name'],'quantity':row['product_snapshot'].get('quantity',1),'unitPriceMinor':row['total_amount_minor']}],
                'totalMinor':row['total_amount_minor'],'receivedMinor':int(amounts['received']),'refundedMinor':int(amounts['refunded']),
                'paymentStatus':row['payment_status'],'productionStatus':row['status'],'environment':row['environment'],'allowedActions':actions}
        if detail:
            payments=c.execute('select id,provider,status,amount_minor,paid_at from payment where order_id=%s order by created_at',(row['id'],)).fetchall()
            refunds=c.execute('select r.id,r.status,r.amount_minor,r.created_at,r.completed_at from refund r join payment p on p.id=r.payment_id where p.order_id=%s order by r.created_at',(row['id'],)).fetchall()
            timeline=c.execute('select to_status,reason,created_at from order_transition where order_id=%s order by revision',(row['id'],)).fetchall()
            result.update(paidAt=next((v['paid_at'] for v in payments if v['paid_at']),None),
                payments=[{'id':str(v['id']),'provider':v['provider'],'accountLabel':'原交易收款账户','environment':row['environment'],'status':v['status'],'amountMinor':v['amount_minor']} for v in payments],
                refunds=[{'id':str(v['id']),'status':v['status'],'amountMinor':v['amount_minor'],'createdAt':v['created_at'],'completedAt':v['completed_at']} for v in refunds],
                timeline=[{'status':v['to_status'],'description':v['reason'],'createdAt':v['created_at']} for v in timeline],
                costSummary={'status':'MISSING','materialCostMinor':None})
        return result

    def orders(self,token,params,order_id=None):
        with self.service.scoped(token,'orders.read') as (c,p):
            if order_id:return self.payload(c,p,self.find(c,p,order_id),True)
            start,end=period(p,params)
            clauses=['tenant_id=%s','created_at>=%s','created_at<%s']; args=[p['tenant_id'],start,end]
            environment=params.get('environment','LIVE')
            if environment not in ('LIVE','TEST'):raise MerchantError(422,'INVALID_ENVIRONMENT','请选择正式或测试数据')
            clauses.append('environment=%s');args.append(environment)
            if p['store_scope']['mode']=='SELECTED':
                clauses.append('merchant_store_id=any(%s)');args.append([identifier(v) for v in p['store_scope']['storeIds']])
            if params.get('storeId'):
                clauses.append('merchant_store_id=%s');args.append(identifier(params['storeId']))
            if params.get('deviceId'):
                if not str(params['deviceId']).isdigit():raise MerchantError(422,'INVALID_DEVICE','无效设备编号')
                # Historical orders can outlive current device ownership.
                clauses.append('terminal_id=%s');args.append(int(params['deviceId']))
            if params.get('status'):
                clauses.append('(status=%s or payment_status=%s)');args.extend([params['status']]*2)
            if params.get('cursor'):
                clauses.append('(created_at,id)<(%s,%s)');args.extend(cursor_decode(params['cursor']))
            rows=c.execute('select * from sales_order where '+' and '.join(clauses)+' order by created_at desc,id desc limit 51',args).fetchall()
            return {'data':[self.payload(c,p,r) for r in rows[:50]],'meta':{'nextCursor':cursor_encode(rows[49]) if len(rows)>50 else None}}

    def refund(self,token,order_id,data,csrf,key,request_id):
        amount=data.get('amountMinor')
        if type(amount) is not int or amount<=0:raise MerchantError(422,'INVALID_AMOUNT','退款金额必须为正整数分',{'amountMinor':'请输入有效金额'})
        with self.service.scoped(token,'refunds.manage',csrf=csrf,sensitive=True) as (c,p):
            def execute():
                order=self.find(c,p,order_id,True)
                if not order['paid_payment_id']:raise MerchantError(409,'REFUND_NOT_ALLOWED','订单没有可退款支付')
                intent=create_refund_intent(c,payment_id=order['paid_payment_id'],idempotency_key='merchant:'+str(key),
                    amount_minor=amount,reason=text_field(data,'reason',500),actor='merchant:'+str(p['user_id']))
                self.service.audit(c,p,'refund.request','order',order['order_no'],request_id)
                return {'id':str(intent.refund['id']),'status':intent.refund['status'],'amountMinor':intent.refund['amount_minor']}
            return self.assets.idempotent(c,p,'refund:'+str(order_id),key,data,execute)
