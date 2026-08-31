SCHEMA = """
create table merchant_material (
 id uuid primary key default gen_random_uuid(), tenant_id uuid not null references merchant_tenant(id),
 external_id text not null, name text not null, unit text not null,
 unit_precision integer not null default 3 check(unit_precision between 0 and 6),
 status text not null default 'ACTIVE', created_at timestamptz not null default now(),
 unique(tenant_id,id), unique(tenant_id,external_id)
);
create table merchant_purchase (
 id uuid primary key default gen_random_uuid(), tenant_id uuid not null references merchant_tenant(id),
 store_id uuid not null, purchased_on date not null, supplier text not null default '',note text not null default '',
 lines jsonb not null, status text not null default 'DRAFT' check(status in ('DRAFT','POSTED')),
 version integer not null default 1, created_at timestamptz not null default now(),posted_at timestamptz,
 foreign key(tenant_id,store_id) references merchant_store(tenant_id,id)
);
create table merchant_stock (
 id uuid primary key default gen_random_uuid(), tenant_id uuid not null references merchant_tenant(id),
 material_id uuid not null, location_key text not null, store_id uuid not null, terminal_id bigint references terminal(id),
 quantity numeric(24,6) not null default 0 check(quantity>=0), value_minor bigint check(value_minor>=0),
 version integer not null default 1, last_event_at timestamptz not null default now(),
 foreign key(tenant_id,store_id) references merchant_store(tenant_id,id),
 foreign key(tenant_id,material_id) references merchant_material(tenant_id,id),
 unique(tenant_id,material_id,location_key)
);
create table merchant_inventory_movement (
 id uuid primary key default gen_random_uuid(), tenant_id uuid not null references merchant_tenant(id),
 material_id uuid not null, store_id uuid not null, terminal_id bigint references terminal(id),
 location_key text not null, type text not null, quantity numeric(24,6) not null,
 amount_minor bigint, unit_cost_minor numeric(30,12), source_key text not null,
 reason text not null, occurred_at timestamptz not null, created_at timestamptz not null default now(),
 foreign key(tenant_id,store_id) references merchant_store(tenant_id,id),
 foreign key(tenant_id,material_id) references merchant_material(tenant_id,id),
 unique(tenant_id,source_key,location_key,material_id)
);
create table merchant_expense (
 id uuid primary key default gen_random_uuid(), tenant_id uuid not null references merchant_tenant(id),
 store_id uuid, terminal_id bigint references terminal(id), category text not null,
 amount_minor bigint not null check(amount_minor>0), occurred_on date not null,
 allocation_start date, allocation_end date, allocation_method text not null check(allocation_method in ('ONCE','DAILY_EQUAL')),
 note text not null default '', status text not null default 'DRAFT' check(status in ('DRAFT','POSTED','REVERSED')),
 version integer not null default 1, created_at timestamptz not null default now(),posted_at timestamptz,
 foreign key(tenant_id,store_id) references merchant_store(tenant_id,id)
);
create table merchant_ledger (
 id uuid primary key default gen_random_uuid(), tenant_id uuid not null references merchant_tenant(id),
 store_id uuid, terminal_id bigint references terminal(id), order_id uuid,
 kind text not null check(kind in ('COLLECTION','REFUND','REVENUE','REVENUE_REVERSAL','MATERIAL','WASTE','FEE','EXPENSE','EXPENSE_REVERSAL','COST_ADJUSTMENT')),
 amount_minor bigint, environment text not null check(environment in ('LIVE','TEST')),
 source_key text not null, occurred_at timestamptz not null, basis text not null default 'ACTUAL',
 detail jsonb not null default '{}', created_at timestamptz not null default now(),
 foreign key(tenant_id,store_id) references merchant_store(tenant_id,id),
 foreign key(tenant_id,order_id) references sales_order(tenant_id,id), unique(tenant_id,source_key)
);
create index merchant_ledger_period on merchant_ledger(tenant_id,occurred_at,store_id,terminal_id,environment);
create table merchant_cost_inbox (
 terminal_id bigint not null references terminal(id), event_id text not null,
 payload jsonb not null, occurred_at timestamptz not null, status text not null default 'PENDING',
 error_code text, created_at timestamptz not null default now(),processed_at timestamptz,
 primary key(terminal_id,event_id)
);
create table merchant_daily_summary (
 tenant_id uuid not null references merchant_tenant(id), day date not null, environment text not null,
 dimension_key text not null, store_id uuid, terminal_id bigint,
 totals jsonb not null, rebuilt_at timestamptz not null default now(),
 primary key(tenant_id,day,environment,dimension_key)
);
create function merchant_immutable_financial_fact() returns trigger language plpgsql as $$
begin raise exception 'financial facts are append only; use a correcting event' using errcode='23514'; end $$;
create trigger merchant_ledger_immutable before update or delete on merchant_ledger
 for each row execute function merchant_immutable_financial_fact();
create trigger merchant_movement_immutable before update or delete on merchant_inventory_movement
 for each row execute function merchant_immutable_financial_fact();

create function merchant_record_money() returns trigger language plpgsql as $$
declare o sales_order%rowtype; p payment%rowtype;
begin
 if tg_table_name='payment' then
  if new.paid_at is null then return new; end if;
  select * into strict o from sales_order where id=new.order_id;
  insert into merchant_ledger(tenant_id,store_id,terminal_id,order_id,kind,amount_minor,environment,source_key,occurred_at)
   values(o.tenant_id,o.merchant_store_id,o.terminal_id,o.id,'COLLECTION',new.amount_minor,new.environment,'payment:'||new.id,new.paid_at)
   on conflict(tenant_id,source_key) do nothing;
  insert into merchant_ledger(tenant_id,store_id,terminal_id,order_id,kind,amount_minor,environment,source_key,occurred_at,basis)
   values(o.tenant_id,o.merchant_store_id,o.terminal_id,o.id,'FEE',case when new.environment='TEST' then 0 else null end,
          new.environment,'payment-fee:'||new.id,new.paid_at,case when new.environment='TEST' then 'SIMULATION' else 'UNKNOWN' end)
   on conflict(tenant_id,source_key) do nothing;
 elsif tg_table_name='refund' then
  if new.status<>'SUCCEEDED' then return new; end if;
  select * into strict p from payment where id=new.payment_id;
  select * into strict o from sales_order where id=p.order_id;
  insert into merchant_ledger(tenant_id,store_id,terminal_id,order_id,kind,amount_minor,environment,source_key,occurred_at)
   values(o.tenant_id,o.merchant_store_id,o.terminal_id,o.id,'REFUND',new.amount_minor,p.environment,'refund:'||new.id,coalesce(new.completed_at,new.updated_at))
   on conflict(tenant_id,source_key) do nothing;
  if p.id=o.paid_payment_id and exists(select 1 from merchant_ledger where order_id=o.id and kind='REVENUE') then
   insert into merchant_ledger(tenant_id,store_id,terminal_id,order_id,kind,amount_minor,environment,source_key,occurred_at)
    values(o.tenant_id,o.merchant_store_id,o.terminal_id,o.id,'REVENUE_REVERSAL',new.amount_minor,p.environment,'refund-revenue:'||new.id,coalesce(new.completed_at,new.updated_at))
    on conflict(tenant_id,source_key) do nothing;
  end if;
 elsif tg_table_name='sales_order' then
  if new.status<>'READY' or new.payment_mode<>'ONLINE' or new.paid_payment_id is null then return new; end if;
  select * into p from payment where id=new.paid_payment_id and paid_at is not null;
  if not found then return new; end if;
  insert into merchant_ledger(tenant_id,store_id,terminal_id,order_id,kind,amount_minor,environment,source_key,occurred_at)
   values(new.tenant_id,new.merchant_store_id,new.terminal_id,new.id,'REVENUE',new.total_amount_minor,new.environment,'revenue:'||new.id,coalesce(new.completed_at,new.updated_at))
   on conflict(tenant_id,source_key) do nothing;
  insert into merchant_ledger(tenant_id,store_id,terminal_id,order_id,kind,amount_minor,environment,source_key,occurred_at)
   select new.tenant_id,new.merchant_store_id,new.terminal_id,new.id,'REVENUE_REVERSAL',r.amount_minor,new.environment,
          'refund-revenue:'||r.id,coalesce(new.completed_at,new.updated_at) from refund r where r.payment_id=p.id and r.status='SUCCEEDED'
   on conflict(tenant_id,source_key) do nothing;
 end if;
 return new;
end $$;
create trigger merchant_payment_money after insert or update on payment for each row execute function merchant_record_money();
create trigger merchant_refund_money after insert or update on refund for each row execute function merchant_record_money();
create trigger merchant_order_revenue after insert or update on sales_order for each row execute function merchant_record_money();
create function merchant_capture_consumption() returns trigger language plpgsql as $$
begin
 if new.event_type='inventory.consumed' then
  insert into merchant_cost_inbox(terminal_id,event_id,payload,occurred_at)
   values(new.terminal_id,new.event_id,new.payload_json,coalesce(new.occurred_at,new.received_at)) on conflict do nothing;
 end if;
 return new;
end $$;
create trigger merchant_material_event after insert on terminal_event for each row execute function merchant_capture_consumption();

-- Backfill actual payment/refund history with its immutable TEST environment.
insert into merchant_ledger(tenant_id,store_id,terminal_id,order_id,kind,amount_minor,environment,source_key,occurred_at)
 select o.tenant_id,o.merchant_store_id,o.terminal_id,o.id,'COLLECTION',p.amount_minor,p.environment,'payment:'||p.id,p.paid_at
 from payment p join sales_order o on o.id=p.order_id where p.paid_at is not null on conflict do nothing;
insert into merchant_ledger(tenant_id,store_id,terminal_id,order_id,kind,amount_minor,environment,source_key,occurred_at)
 select o.tenant_id,o.merchant_store_id,o.terminal_id,o.id,'REFUND',r.amount_minor,p.environment,'refund:'||r.id,coalesce(r.completed_at,r.updated_at)
 from refund r join payment p on p.id=r.payment_id join sales_order o on o.id=p.order_id where r.status='SUCCEEDED' on conflict do nothing;
"""

for table in ('merchant_material','merchant_purchase','merchant_stock','merchant_inventory_movement','merchant_expense','merchant_ledger','merchant_daily_summary'):
    SCHEMA += f"""
    alter table {table} enable row level security;
    create policy {table}_tenant on {table}
     using(tenant_id=nullif(current_setting('coffee.tenant_id',true),'')::uuid)
     with check(tenant_id=nullif(current_setting('coffee.tenant_id',true),'')::uuid);
    """
