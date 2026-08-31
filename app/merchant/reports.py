from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import timedelta

from psycopg.types.json import Jsonb

from .assets import MerchantAssets
from .orders import MerchantOrders, period, cursor_decode, cursor_encode
from .security import MerchantError, PERMISSIONS, token_hash
from .service import identifier


FIELDS=('receivedMinor','refundedMinor','recognizedRevenueMinor','materialCostMinor','wasteCostMinor','paymentFeeMinor','operatingExpenseMinor','paidOrderCount','deliveredCupCount')
KIND={'COLLECTION':('receivedMinor',1),'REFUND':('refundedMinor',1),'REVENUE':('recognizedRevenueMinor',1),
      'REVENUE_REVERSAL':('recognizedRevenueMinor',-1),'MATERIAL':('materialCostMinor',1),'WASTE':('wasteCostMinor',1),
      'FEE':('paymentFeeMinor',1),'EXPENSE':('operatingExpenseMinor',1),'EXPENSE_REVERSAL':('operatingExpenseMinor',-1)}


def finish(values):
    result=dict(values)
    result['netCashMinor']=result['receivedMinor']-result['refundedMinor']
    result['grossProfitMinor']=None if result['materialCostMinor'] is None else result['recognizedRevenueMinor']-result['materialCostMinor']
    missing=[k for k in ('materialCostMinor','wasteCostMinor','paymentFeeMinor','operatingExpenseMinor') if result[k] is None]
    result['estimatedProfitMinor']=None if missing else result['grossProfitMinor']-result['wasteCostMinor']-result['paymentFeeMinor']-result['operatingExpenseMinor']
    result['completeness']={'status':'INCOMPLETE' if missing else 'COMPLETE','missing':missing}
    return result


def add(target, source):
    for key in FIELDS:
        target[key]=None if target[key] is None or source[key] is None else target[key]+source[key]


class MerchantReports:
    def __init__(self,service):
        self.service=service

    def operating(self,token,params,*,permission='reports.read'):
        with self.service.scoped(token,permission) as (c,p):
            start,end=period(p,params);grain=params.get('grain','DAY');environment=params.get('environment','LIVE')
            if grain not in ('DAY','MONTH','YEAR') or environment not in ('LIVE','TEST'):raise MerchantError(422,'INVALID_REPORT','无效报表粒度或数据环境')
            store_id=identifier(params['storeId']) if params.get('storeId') else None
            if store_id and not c.execute('select id from merchant_store where id=%s and tenant_id=%s', (store_id,p['tenant_id'])).fetchone():
                raise MerchantError(404,'NOT_FOUND','门店不存在或无访问权限')
            device_id=params.get('deviceId')
            if device_id and (not device_id.isdigit() or len(device_id)>18):raise MerchantError(422,'INVALID_DEVICE','无效设备编号')
            device_id=int(device_id) if device_id else None
            where='tenant_id=%s and occurred_at>=%s and occurred_at<%s and environment=%s'
            args=[p['tenant_id'],start,end,environment]
            if store_id:where+=' and store_id=%s';args.append(store_id)
            if device_id:where+=' and terminal_id=%s';args.append(device_id)
            events=c.execute("""select (occurred_at at time zone %s)::date as day,kind,sum(amount_minor) as amount,
                count(*) filter(where amount_minor is null) as missing,count(distinct order_id) as orders
                from merchant_ledger where """+where+' group by day,kind', [p['timezone'],*args]).fetchall()
            daily={};current=start.date()
            while current<end.date():daily[current]={key:0 for key in FIELDS};current+=timedelta(days=1)
            for row in events:
                if row['kind'] not in KIND:continue
                field,sign=KIND[row['kind']];bucket=daily[row['day']]
                if row['missing']:bucket[field]=None
                elif bucket[field] is not None:bucket[field]+=sign*int(row['amount'] or 0)
                if row['kind']=='COLLECTION':bucket['paidOrderCount']=row['orders']
            order_where="tenant_id=%s and status='READY' and completed_at>=%s and completed_at<%s and environment=%s"
            order_args=[p['tenant_id'],start,end,environment]
            if store_id:order_where+=' and merchant_store_id=%s';order_args.append(store_id)
            if device_id:order_where+=' and terminal_id=%s';order_args.append(device_id)
            deliveries=c.execute("""select (completed_at at time zone %s)::date as day,count(*) as cups,
                count(*) filter(where payment_mode='ONLINE' and not exists(select 1 from merchant_ledger l
                  where l.tenant_id=sales_order.tenant_id and l.order_id=sales_order.id and l.kind='MATERIAL')) as missing
                from sales_order where """+order_where+' group by day',[p['timezone'],*order_args]).fetchall()
            for row in deliveries:
                daily[row['day']]['deliveredCupCount']=row['cups']
                if row['missing']:daily[row['day']]['materialCostMinor']=None
            # Derived summaries are replaceable; the append-only ledger is the
            # source of truth. Every read rebuilds its requested range, including
            # late refunds/events, rather than serving a stale cached balance.
            dimension=f'{store_id or "all"}:{device_id or "all"}:'+token_hash(str(p['store_scope']))[:12]
            groups={};totals={key:0 for key in FIELDS}
            for day,values in daily.items():
                row=finish(values)
                # A restricted membership cannot write an organization-wide
                # cache row. Return its RLS-filtered aggregation without caching.
                if store_id or p['store_scope']['mode']=='ALL':
                    c.execute("""insert into merchant_daily_summary(tenant_id,day,environment,dimension_key,store_id,terminal_id,totals)
                        values(%s,%s,%s,%s,%s,%s,%s) on conflict(tenant_id,day,environment,dimension_key)
                        do update set totals=excluded.totals,rebuilt_at=now()""",(p['tenant_id'],day,environment,dimension,store_id,device_id,Jsonb(row)))
                key=day.isoformat() if grain=='DAY' else day.strftime('%Y-%m') if grain=='MONTH' else str(day.year)
                groups.setdefault(key,{field:0 for field in FIELDS});add(groups[key],values);add(totals,values)
            finished=finish(totals)
            return {'period':{'from':start.date().isoformat(),'to':end.date().isoformat(),'timezone':p['timezone']},
                    'grain':grain,'environment':environment,'rows':[{'period':key,**finish(value)} for key,value in groups.items()],
                    'totals':finished,'completeness':finished['completeness'],
                    'notes':['门店与设备报表只包含已明确分配的费用；库存账不代表实时传感器读数。']}

    def csv(self,token,params):
        report=self.operating(token,params,permission='reports.export')
        out=io.StringIO();writer=csv.writer(out)
        columns=['period',*FIELDS,'netCashMinor','grossProfitMinor','estimatedProfitMinor']
        writer.writerow(['期间','实收(分)','退款(分)','营业净收入(分)','材料成本(分)','损耗(分)','支付手续费(分)','运营费用(分)','支付订单数','交付杯数','净收款(分)','毛利(分)','经营利润估算(分)'])
        def safe(value):
            text='待补全' if value is None else str(value)
            return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text
        for row in report['rows']:writer.writerow([safe(row.get(k)) for k in columns])
        writer.writerow(['数据环境',report['environment'],'时区',report['period']['timezone']])
        return '\ufeff'+out.getvalue()

    def dashboard(self,token,params):
        with self.service.identity(token,'dashboard.read') as (c,p):
            finance='costs.read' in PERMISSIONS[p['role']]
        devices=MerchantAssets(self.service).devices(token,{'storeId':params.get('storeId','')})
        recent=MerchantOrders(self.service).orders(token,params)['data'][:8]
        metrics={'deviceCount':len(devices),'onlineCount':sum(d['online'] for d in devices)}
        if finance:
            report=self.operating(token,{**params,'grain':'DAY'},permission='dashboard.read')
            metrics.update(report['totals'])
            trend=[{'date':r['period'],'receivedMinor':r['receivedMinor'],'estimatedProfitMinor':r['estimatedProfitMinor']} for r in report['rows']]
            completeness=report['completeness']
        else:
            metrics.update(paidOrderCount=None,deliveredCupCount=None)
            trend=[];completeness={'status':'COMPLETE','missing':[]}
        alerts=[{'id':'offline:'+d['id'],'severity':'WARNING','title':d['name']+' 离线','description':'请检查设备网络和电源','deviceId':d['id']} for d in devices if not d['online']]
        return {'period':{'from':params.get('from'),'to':params.get('to'),'timezone':p['timezone']},'environment':params.get('environment','LIVE'),
                'metrics':metrics,'trend':trend,'completeness':completeness,'alerts':alerts,'recentOrders':recent}

    def audit(self,token,params):
        with self.service.scoped(token,'audit.read') as (c,p):
            start,end=period(p,params);where='tenant_id=%s and created_at>=%s and created_at<%s';args=[p['tenant_id'],start,end]
            if params.get('action'):where+=' and action=%s';args.append(params['action'])
            if params.get('cursor'):where+=' and (created_at,id)<(%s,%s)';args.extend(cursor_decode(params['cursor']))
            rows=c.execute('select * from merchant_audit where '+where+' order by created_at desc,id desc limit 51',args).fetchall()
            return {'data':[{'id':str(r['id']),'createdAt':r['created_at'],'actorName':r['actor_name'],'action':r['action'],
                'resourceType':r['resource_type'],'resourceLabel':r['resource_label'],'outcome':r['outcome'],'requestId':r['request_id']} for r in rows[:50]],
                'meta':{'nextCursor':cursor_encode(rows[49]) if len(rows)>50 else None}}
