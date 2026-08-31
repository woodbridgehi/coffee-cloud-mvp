SCHEMA = """
create table merchant_payment_account (
 id uuid primary key default gen_random_uuid(), tenant_id uuid not null references merchant_tenant(id),
 label text not null, provider text not null check(provider in ('alipay','alipay_mock')),
 environment text not null check(environment in ('LIVE','SANDBOX','MOCK')),
 app_id text not null, merchant_id text not null, encrypted_credentials text not null,
 status text not null default 'DRAFT' check(status in ('DRAFT','VALIDATED','DISABLED')),
 is_default boolean not null default false, version integer not null default 1,
 checks jsonb not null default '[]', configured_at timestamptz not null default now(),
 unique(tenant_id,id), unique(provider,environment,app_id),
 check((provider='alipay_mock')=(environment='MOCK')),
 check(not is_default or status='VALIDATED')
);
create unique index merchant_payment_default on merchant_payment_account(tenant_id) where is_default;
alter table merchant_payment_account enable row level security;
create policy merchant_payment_account_scope on merchant_payment_account
 using(tenant_id=nullif(current_setting('coffee.tenant_id',true),'')::uuid)
 with check(tenant_id=nullif(current_setting('coffee.tenant_id',true),'')::uuid);
alter table sales_order add column payment_account_id uuid;
alter table sales_order add constraint sales_order_payment_account
 foreign key(tenant_id,payment_account_id) references merchant_payment_account(tenant_id,id);
alter table payment add column tenant_id uuid not null default '00000000-0000-4000-8000-000000000001' references merchant_tenant(id);
alter table payment add column payment_account_id uuid;
alter table payment add column environment text not null default 'TEST' check(environment in ('LIVE','TEST'));
alter table payment add constraint payment_tenant_order foreign key(tenant_id,order_id) references sales_order(tenant_id,id);
alter table payment add constraint payment_tenant_account foreign key(tenant_id,payment_account_id) references merchant_payment_account(tenant_id,id);
create function merchant_capture_payment_account() returns trigger language plpgsql as $$
declare o sales_order%rowtype; a merchant_payment_account%rowtype;
begin
 select * into strict o from sales_order where id=new.order_id;
 new.tenant_id:=o.tenant_id; new.payment_account_id:=o.payment_account_id; new.environment:=o.environment;
 if o.payment_account_id is not null then
  select * into strict a from merchant_payment_account where id=o.payment_account_id and tenant_id=o.tenant_id;
  if a.provider<>new.provider then raise exception 'payment provider differs from frozen account' using errcode='23514'; end if;
 end if;
 return new;
end $$;
create trigger merchant_payment_account before insert on payment for each row execute function merchant_capture_payment_account();
create function merchant_preserve_payment_account() returns trigger language plpgsql as $$
begin
 if (new.tenant_id,new.order_id,new.payment_account_id,new.environment) is distinct from
    (old.tenant_id,old.order_id,old.payment_account_id,old.environment)
 then raise exception 'payment account is immutable' using errcode='23514'; end if;
 return new;
end $$;
create trigger merchant_payment_account_immutable before update on payment for each row execute function merchant_preserve_payment_account();
create or replace function merchant_capture_order_owner() returns trigger language plpgsql as $$
declare d terminal%rowtype; a merchant_payment_account%rowtype;
begin
 select * into strict d from terminal where id=new.terminal_id for share;
 if d.ownership_frozen then raise exception 'device ownership is frozen' using errcode='23514'; end if;
 new.tenant_id:=d.tenant_id; new.merchant_store_id:=d.merchant_store_id; new.ownership_version:=d.ownership_version;
 new.device_name_snapshot:=coalesce(nullif(d.device_name,''),d.device_id);
 new.store_name_snapshot:=coalesce((select name from merchant_store where id=d.merchant_store_id),d.store_name,d.store_id,'');
 select * into a from merchant_payment_account where tenant_id=d.tenant_id and is_default and status='VALIDATED';
 new.payment_account_id:=a.id;
 new.environment:=case when a.environment='LIVE' and new.payment_mode='ONLINE' then 'LIVE' else 'TEST' end;
 return new;
end $$;
create or replace function merchant_preserve_order_owner() returns trigger language plpgsql as $$
begin
 if (new.tenant_id,new.merchant_store_id,new.ownership_version,new.device_name_snapshot,new.store_name_snapshot,new.payment_account_id,new.environment)
    is distinct from (old.tenant_id,old.merchant_store_id,old.ownership_version,old.device_name_snapshot,old.store_name_snapshot,old.payment_account_id,old.environment)
 then raise exception 'historical order ownership and account are immutable' using errcode='23514'; end if;
 return new;
end $$;
"""
