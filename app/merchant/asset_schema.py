SCHEMA = """
insert into merchant_tenant(id,name,environment)
 values('00000000-0000-4000-8000-000000000001','平台历史测试资产','INTERNAL_TEST');
alter table terminal add column tenant_id uuid not null default '00000000-0000-4000-8000-000000000001' references merchant_tenant(id);
alter table terminal add column merchant_store_id uuid;
alter table terminal add column ownership_version integer not null default 1;
alter table terminal add column merchant_version integer not null default 1;
alter table terminal add column ownership_frozen boolean not null default false;
alter table terminal add constraint terminal_merchant_store foreign key(tenant_id,merchant_store_id) references merchant_store(tenant_id,id);
alter table terminal add constraint terminal_tenant_id_unique unique(tenant_id,id);
create index terminal_merchant_store_index on terminal(tenant_id,merchant_store_id);

create table merchant_device_ownership (
 id uuid primary key default gen_random_uuid(), terminal_id bigint not null references terminal(id),
 tenant_id uuid not null references merchant_tenant(id), store_id uuid,
 version integer not null, valid_from timestamptz not null default now(), valid_until timestamptz,
 unique(terminal_id,version), unique(tenant_id,terminal_id,version), foreign key(tenant_id,store_id) references merchant_store(tenant_id,id)
);
insert into merchant_device_ownership(terminal_id,tenant_id,store_id,version,valid_from)
 select id,tenant_id,merchant_store_id,ownership_version,created_at from terminal;
create table merchant_device_claim (
 id uuid primary key default gen_random_uuid(), terminal_id bigint not null references terminal(id),
 code_hash text not null unique, expires_at timestamptz not null,
 consumed_at timestamptz, consumed_by uuid references merchant_tenant(id),
 created_at timestamptz not null default now()
);
create table merchant_device_transfer (
 id uuid primary key default gen_random_uuid(), terminal_id bigint not null references terminal(id),
 source_tenant_id uuid not null references merchant_tenant(id), target_tenant_id uuid references merchant_tenant(id),
 target_store_id uuid, reason text not null,
 status text not null check(status in ('PENDING_RECIPIENT','PENDING_PLATFORM','REVOKING','COMPLETED','CANCELLED','REJECTED')),
 ownership_version integer not null, previous_lifecycle text not null,
 version integer not null default 1, created_at timestamptz not null default now(), completed_at timestamptz,
 foreign key(target_tenant_id,target_store_id) references merchant_store(tenant_id,id)
);
create unique index merchant_transfer_active on merchant_device_transfer(terminal_id)
 where status in ('PENDING_RECIPIENT','PENDING_PLATFORM','REVOKING');
create table merchant_operation (
 tenant_id uuid not null references merchant_tenant(id), operation text not null, key text not null,
 digest text not null, response jsonb not null, created_at timestamptz not null default now(),
 primary key(tenant_id,operation,key)
);
create table merchant_price (
 id uuid primary key default gen_random_uuid(), tenant_id uuid not null references merchant_tenant(id),
 sku text not null, store_id uuid, terminal_id bigint, ownership_version integer,
 price_minor bigint not null check(price_minor>0), effective_at timestamptz not null,
 version integer not null default 1, created_at timestamptz not null default now(),
 foreign key(tenant_id,store_id) references merchant_store(tenant_id,id),
 foreign key(tenant_id,terminal_id,ownership_version) references merchant_device_ownership(tenant_id,terminal_id,version),
 check((terminal_id is null)=(ownership_version is null))
);
alter table sales_order add column tenant_id uuid not null default '00000000-0000-4000-8000-000000000001' references merchant_tenant(id);
alter table sales_order add column merchant_store_id uuid;
alter table sales_order add column ownership_version integer not null default 1;
alter table sales_order add column device_name_snapshot text not null default '';
alter table sales_order add column store_name_snapshot text not null default '';
alter table sales_order add column environment text not null default 'TEST' check(environment in ('LIVE','TEST'));
alter table sales_order add constraint sales_order_tenant_unique unique(tenant_id,id);
alter table sales_order add constraint sales_order_merchant_store foreign key(tenant_id,merchant_store_id) references merchant_store(tenant_id,id);
update sales_order o set device_name_snapshot=coalesce(nullif(t.device_name,''),t.device_id),store_name_snapshot=coalesce(t.store_name,t.store_id,'')
 from terminal t where t.id=o.terminal_id;
create index sales_order_tenant_period on sales_order(tenant_id,created_at,id);
create function merchant_capture_order_owner() returns trigger language plpgsql as $$
declare d terminal%rowtype;
begin
 select * into strict d from terminal where id=new.terminal_id for share;
 if d.ownership_frozen then raise exception 'device ownership is frozen' using errcode='23514'; end if;
 new.tenant_id:=d.tenant_id; new.merchant_store_id:=d.merchant_store_id;
 new.ownership_version:=d.ownership_version;
 new.device_name_snapshot:=coalesce(nullif(d.device_name,''),d.device_id);
 new.store_name_snapshot:=coalesce((select name from merchant_store where id=d.merchant_store_id),d.store_name,d.store_id,'');
 -- Explicitly TEST until an enabled, validated merchant account is selected.
 new.environment:='TEST';
 return new;
end $$;
create trigger merchant_order_owner before insert on sales_order for each row execute function merchant_capture_order_owner();
create function merchant_preserve_order_owner() returns trigger language plpgsql as $$
begin
 if (new.tenant_id,new.merchant_store_id,new.ownership_version,new.device_name_snapshot,new.store_name_snapshot)
    is distinct from (old.tenant_id,old.merchant_store_id,old.ownership_version,old.device_name_snapshot,old.store_name_snapshot)
 then raise exception 'historical order ownership is immutable' using errcode='23514'; end if;
 return new;
end $$;
create trigger merchant_order_owner_immutable before update on sales_order for each row execute function merchant_preserve_order_owner();

alter table terminal enable row level security;
create policy terminal_merchant_scope on terminal
 using(tenant_id=nullif(current_setting('coffee.tenant_id',true),'')::uuid)
 with check(tenant_id=nullif(current_setting('coffee.tenant_id',true),'')::uuid);
alter table sales_order enable row level security;
create policy order_merchant_scope on sales_order
 using(tenant_id=nullif(current_setting('coffee.tenant_id',true),'')::uuid)
 with check(tenant_id=nullif(current_setting('coffee.tenant_id',true),'')::uuid);
-- Existing internal platform/worker connections retain their table-owner access.
-- Tenant requests always switch to the explicitly checked non-owner role.
"""

for table in ('merchant_device_ownership', 'merchant_operation', 'merchant_price'):
    SCHEMA += f"""
    alter table {table} enable row level security;
    create policy {table}_scope on {table}
    using(tenant_id=nullif(current_setting('coffee.tenant_id',true),'')::uuid)
    with check(tenant_id=nullif(current_setting('coffee.tenant_id',true),'')::uuid);
    """
