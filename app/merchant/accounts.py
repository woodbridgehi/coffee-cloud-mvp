from __future__ import annotations

import json
import secrets

import psycopg
from psycopg.types.json import Jsonb

from ..payment_providers import AlipayProvider
from .security import MerchantError, cipher
from .service import identifier, text_field


def provider_for_payment(factory, payment):
    account = payment.get('payment_account_id')
    return factory(payment['provider'], account) if account else factory(payment['provider'])


class MerchantAccounts:
    def __init__(self, service):
        self.service=service

    def gateway(self, environment):
        if environment=='MOCK':
            gateway=self.service.settings.alipay_mock_gateway
            if not gateway:raise MerchantError(503,'NOT_CONFIGURED','模拟网关尚未配置')
            return gateway
        return 'https://openapi.alipay.com/gateway.do' if environment=='LIVE' else 'https://openapi-sandbox.dl.alipaydev.com/gateway.do'

    @staticmethod
    def public(row):
        def mask(value):return value[:3]+'…'+value[-3:] if len(value)>6 else '***'
        return {'id':str(row['id']),'label':row['label'],'provider':row['provider'],'environment':row['environment'],
                'appIdMasked':mask(row['app_id']),'merchantIdMasked':mask(row['merchant_id']),
                'status':row['status'],'isDefault':row['is_default'],'version':row['version'],'checks':row['checks'],
                'configuredAt':row['configured_at']}

    def build(self,row):
        keys=json.loads(cipher(self.service.settings.merchant_encryption_key).decrypt(row['encrypted_credentials'].encode()))
        provider=AlipayProvider(app_id=row['app_id'],app_private_key=keys['privateKey'],alipay_public_key=keys['publicKey'],
                                gateway=self.gateway(row['environment']),timeout_seconds=self.service.settings.alipay_timeout_seconds)
        provider.name=row['provider']
        return provider

    def resolve(self,name,account_id):
        with self.service.database.connect() as c:
            row=c.execute('select * from merchant_payment_account where id=%s',(identifier(account_id),)).fetchone()
        if not row or row['provider']!=name:
            raise MerchantError(503,'ACCOUNT_UNAVAILABLE','原交易账户不可用')
        # Disabled accounts remain available for historical query/close/refund.
        return self.build(row)

    def list(self,token):
        with self.service.scoped(token,'payments.read') as (c,p):
            return [self.public(r) for r in c.execute('select * from merchant_payment_account where tenant_id=%s order by configured_at,id',(p['tenant_id'],)).fetchall()]

    def create(self,token,data,csrf,request_id):
        environment=data.get('environment');provider=data.get('provider')
        if (environment,provider) not in {('LIVE','alipay'),('SANDBOX','alipay'),('MOCK','alipay_mock')}:
            raise MerchantError(422,'INVALID_CHANNEL','收款渠道与环境不匹配')
        private=text_field(data,'appPrivateKey',16384);public=text_field(data,'providerPublicKey',8192)
        app_id=text_field(data,'appId',128);merchant_id=text_field(data,'merchantId',128)
        encrypted=cipher(self.service.settings.merchant_encryption_key).encrypt(json.dumps({'privateKey':private,'publicKey':public}).encode()).decode()
        candidate={'provider':provider,'environment':environment,'app_id':app_id,'encrypted_credentials':encrypted}
        try:
            parsed=self.build(candidate)
            from cryptography.hazmat.primitives.asymmetric import rsa
            if not isinstance(parsed.private_key,rsa.RSAPrivateKey) or parsed.private_key.key_size<2048 or not isinstance(parsed.public_key,rsa.RSAPublicKey) or parsed.public_key.key_size<2048:
                raise ValueError('RSA2 keys required')
        except (ValueError,TypeError):
            raise MerchantError(422,'INVALID_KEY','请提供2048位或以上的 RSA PEM 密钥') from None
        try:
            with self.service.scoped(token,'payments.manage',csrf=csrf,sensitive=True) as (c,p):
                row=c.execute("""insert into merchant_payment_account(tenant_id,label,provider,environment,app_id,merchant_id,encrypted_credentials)
                    values(%s,%s,%s,%s,%s,%s,%s) returning *""",(p['tenant_id'],text_field(data,'label'),provider,environment,app_id,merchant_id,encrypted)).fetchone()
                self.service.audit(c,p,'payment-account.create','payment-account',row['label'],request_id)
                return self.public(row)
        except psycopg.errors.UniqueViolation:
            raise MerchantError(409,'ACCOUNT_UNAVAILABLE','该渠道应用已配置，请联系平台核对') from None

    def action(self,token,account_id,data,csrf,request_id,action):
        if action=='validate':
            with self.service.scoped(token,'payments.manage',csrf=csrf,sensitive=True) as (c,p):
                row=c.execute('select * from merchant_payment_account where id=%s and tenant_id=%s',(identifier(account_id),p['tenant_id'])).fetchone()
                if not row:raise MerchantError(404,'NOT_FOUND','账户不存在或无访问权限')
                self.service.check_version(row,data)
                if row['status']=='DISABLED':raise MerchantError(409,'BAD_STATE','已停用的账户不能重新校验，请新建配置')
            # Query an unpredictable nonexistent order; never create or charge.
            try:
                result=self.build(row).query_payment('CHECK'+secrets.token_hex(16))
                valid=result.status=='NOT_FOUND'
            except Exception:
                valid=False
            checks=[{'name':'渠道签名与查询权限','status':'PASSED' if valid else 'FAILED',
                     'message':'渠道已验证签名并确认订单不存在' if valid else '校验失败，请核对渠道应用、公钥及商户配置'}]
            with self.service.scoped(token,'payments.manage',csrf=csrf,sensitive=True) as (c,p):
                current=c.execute('select * from merchant_payment_account where id=%s and tenant_id=%s for update',(identifier(account_id),p['tenant_id'])).fetchone()
                if not current:raise MerchantError(404,'NOT_FOUND','账户不存在或无访问权限')
                self.service.check_version(current,data)
                if current['is_default'] and not valid:
                    # Do not erase an existing operational account on a transient
                    # network failure; surface failed checks without changing it.
                    c.execute('update merchant_payment_account set checks=%s where id=%s',(Jsonb(checks),current['id']))
                else:
                    c.execute('update merchant_payment_account set status=%s,checks=%s,version=version+1 where id=%s',('VALIDATED' if valid else 'DRAFT',Jsonb(checks),current['id']))
                self.service.audit(c,p,'payment-account.validate','payment-account',row['label'],request_id)
            return {'status':'VALIDATED' if valid else 'FAILED','checks':checks}
        with self.service.scoped(token,'payments.manage',csrf=csrf,sensitive=True) as (c,p):
            c.execute('select pg_advisory_xact_lock(hashtextextended(%s,0))',('account:'+str(p['tenant_id']),))
            row=c.execute('select * from merchant_payment_account where id=%s and tenant_id=%s for update',(identifier(account_id),p['tenant_id'])).fetchone()
            if not row:raise MerchantError(404,'NOT_FOUND','账户不存在或无访问权限')
            self.service.check_version(row,data)
            if action=='set-default':
                if row['status']!='VALIDATED':raise MerchantError(409,'VALIDATION_REQUIRED','账户须先通过渠道校验')
                c.execute('update merchant_payment_account set is_default=false,version=version+1 where tenant_id=%s and is_default',(p['tenant_id'],))
                row=c.execute('update merchant_payment_account set is_default=true,version=version+1 where id=%s returning *',(row['id'],)).fetchone()
            elif action=='disable':
                if row['is_default']:raise MerchantError(409,'IS_DEFAULT','请先设置其他默认账户')
                row=c.execute("update merchant_payment_account set status='DISABLED',version=version+1 where id=%s returning *",(row['id'],)).fetchone()
            else:raise MerchantError(404,'NOT_FOUND','操作不存在')
            self.service.audit(c,p,'payment-account.'+action,'payment-account',row['label'],request_id)
            return self.public(row)
