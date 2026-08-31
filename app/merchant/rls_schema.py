SCHEMA = """
create function merchant_store_visible(value uuid) returns boolean language sql stable as $$
 select coalesce((nullif(current_setting('coffee.store_scope',true),'')::jsonb->>'mode')='ALL'
   or (nullif(current_setting('coffee.store_scope',true),'')::jsonb->'storeIds') ? value::text,false)
$$;
create policy merchant_store_membership on merchant_store as restrictive
 using(merchant_store_visible(id)) with check(merchant_store_visible(id));
create policy terminal_store_membership on terminal as restrictive
 using(merchant_store_visible(merchant_store_id)) with check(merchant_store_visible(merchant_store_id));
create policy order_store_membership on sales_order as restrictive
 using(merchant_store_visible(merchant_store_id)) with check(merchant_store_visible(merchant_store_id));
alter table payment enable row level security;
create policy payment_merchant_scope on payment using(exists(select 1 from sales_order o where o.id=payment.order_id))
 with check(exists(select 1 from sales_order o where o.id=payment.order_id));
alter table terminal_command add column tenant_id uuid not null default '00000000-0000-4000-8000-000000000001' references merchant_tenant(id);
create function merchant_command_owner() returns trigger language plpgsql as $$
begin new.tenant_id:=(select tenant_id from terminal where id=new.terminal_id);return new;end $$;
create trigger merchant_command_owner before insert on terminal_command for each row execute function merchant_command_owner();
alter table terminal_command enable row level security;
create policy command_merchant_scope on terminal_command
 using(tenant_id=nullif(current_setting('coffee.tenant_id',true),'')::uuid and exists(select 1 from terminal t where t.id=terminal_command.terminal_id))
 with check(tenant_id=nullif(current_setting('coffee.tenant_id',true),'')::uuid and exists(select 1 from terminal t where t.id=terminal_command.terminal_id));
"""

PARENTS = {
    'refund': ('payment','payment_id'),
    'payment_event': ('payment','payment_id'),
    'order_transition': ('sales_order','order_id'),
    'production_job': ('sales_order','order_id'),
    'terminal_snapshot': ('terminal','terminal_id'),
    'terminal_command_transition': ('terminal_command','command_id'),
    'command_outbox': ('terminal_command','command_id'),
}
for table, (parent,column) in PARENTS.items():
    SCHEMA += f"""
    alter table {table} enable row level security;
    create policy {table}_merchant_scope on {table}
     using(exists(select 1 from {parent} p where p.id={table}.{column}))
     with check(exists(select 1 from {parent} p where p.id={table}.{column}));
    """
for table in ('merchant_purchase','merchant_stock','merchant_inventory_movement','merchant_expense','merchant_ledger','merchant_daily_summary'):
    SCHEMA += f"""
    create policy {table}_store_scope on {table} as restrictive
     using(merchant_store_visible(store_id)) with check(merchant_store_visible(store_id));
    """
