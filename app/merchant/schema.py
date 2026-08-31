SCHEMA = """
create table merchant_tenant (
 id uuid primary key default gen_random_uuid(), name text not null,
 status text not null default 'ACTIVE' check(status in ('ACTIVE','SUSPENDED')),
 timezone text not null default 'Asia/Shanghai', environment text not null default 'LIVE'
 check(environment in ('LIVE','INTERNAL_TEST')), version integer not null default 1,
 created_at timestamptz not null default now()
);
create table merchant_user (
 id uuid primary key default gen_random_uuid(), email text not null unique,
 display_name text not null, password_hash text not null,
 status text not null default 'ACTIVE' check(status in ('ACTIVE','SUSPENDED')),
 verified_at timestamptz, created_at timestamptz not null default now()
);
create table merchant_member (
 id uuid primary key default gen_random_uuid(), tenant_id uuid not null references merchant_tenant(id),
 user_id uuid not null references merchant_user(id),
 role text not null check(role in ('OWNER','OPERATOR','FINANCE')),
 status text not null default 'ACTIVE' check(status in ('ACTIVE','SUSPENDED')),
 store_scope jsonb not null default '{"mode":"ALL","storeIds":[]}',
 version integer not null default 1, created_at timestamptz not null default now(),
 unique(tenant_id,user_id), unique(tenant_id,id)
);
create table merchant_session (
 id uuid primary key default gen_random_uuid(), token_hash text not null unique,
 csrf_token text not null, user_id uuid not null references merchant_user(id),
 member_id uuid not null references merchant_member(id),
 expires_at timestamptz not null, revoked_at timestamptz,
 reauthenticated_at timestamptz not null default now(), created_at timestamptz not null default now()
);
create index merchant_session_user on merchant_session(user_id);
create table merchant_email_action (
 id uuid primary key default gen_random_uuid(), token_hash text not null unique,
 user_id uuid references merchant_user(id), purpose text not null check(purpose in ('VERIFY','RESET','INVITE')),
 payload jsonb not null default '{}', expires_at timestamptz not null,
 consumed_at timestamptz, created_at timestamptz not null default now()
);
create table merchant_mail_outbox (
 id uuid primary key default gen_random_uuid(), recipient text not null,
 encrypted_message text not null, status text not null default 'PENDING',
 attempts integer not null default 0, next_attempt_at timestamptz not null default now(),
 last_error text, created_at timestamptz not null default now(), sent_at timestamptz
);
create table merchant_rate_limit (
 key text primary key, window_start timestamptz not null default now(), hits integer not null
);
create table merchant_store (
 id uuid primary key default gen_random_uuid(), tenant_id uuid not null references merchant_tenant(id),
 name text not null, address text not null default '', status text not null default 'ACTIVE'
 check(status in ('ACTIVE','ARCHIVED')), version integer not null default 1,
 created_at timestamptz not null default now(), unique(tenant_id,id)
);
create table merchant_invitation (
 id uuid primary key default gen_random_uuid(), tenant_id uuid not null references merchant_tenant(id),
 email text not null, role text not null check(role in ('OWNER','OPERATOR','FINANCE')),
 store_scope jsonb not null, status text not null default 'PENDING'
 check(status in ('PENDING','ACCEPTED','REVOKED')),
 action_id uuid not null references merchant_email_action(id),
 expires_at timestamptz not null, created_at timestamptz not null default now()
);
create unique index merchant_invitation_pending on merchant_invitation(tenant_id,email) where status='PENDING';
create table merchant_audit (
 id uuid primary key default gen_random_uuid(), tenant_id uuid not null references merchant_tenant(id),
 actor_id uuid references merchant_user(id), actor_name text not null,
 action text not null, resource_type text not null, resource_label text not null,
 outcome text not null default 'SUCCEEDED', request_id text not null,
 created_at timestamptz not null default now()
);
create index merchant_audit_tenant_time on merchant_audit(tenant_id,created_at desc,id);
-- RLS is an additional boundary. The dedicated runtime role must have no
-- ownership, superuser or BYPASSRLS privileges (provisioned outside migrations).
alter table merchant_store enable row level security;
alter table merchant_store force row level security;
create policy merchant_store_tenant on merchant_store
 using (tenant_id = nullif(current_setting('coffee.tenant_id',true),'')::uuid)
 with check (tenant_id = nullif(current_setting('coffee.tenant_id',true),'')::uuid);
alter table merchant_audit enable row level security;
alter table merchant_audit force row level security;
create policy merchant_audit_tenant on merchant_audit
 using (tenant_id = nullif(current_setting('coffee.tenant_id',true),'')::uuid)
 with check (tenant_id = nullif(current_setting('coffee.tenant_id',true),'')::uuid);
"""
