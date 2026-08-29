from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row


SCHEMA_SQL = """
create table if not exists terminal (
    id bigserial primary key,
    device_id text not null unique,
    serial_number text not null unique,
    instance_id text,
    store_id text,
    lifecycle_status text not null default 'ACTIVE',
    connection_status text not null default 'offline',
    last_seen_at timestamptz,
    last_heartbeat_at timestamptz,
    last_connected_at timestamptz,
    active_boot_id text,
    last_sequence bigint,
    software_version text,
    capability_version text,
    inventory_version bigint,
    heartbeat_count bigint not null default 0,
    reported_status jsonb not null default '{}'::jsonb,
    last_error_summary jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists terminal_credential (
    id bigserial primary key,
    terminal_id bigint not null references terminal(id),
    token_hash char(64) not null unique,
    status text not null default 'ACTIVE',
    created_at timestamptz not null default now(),
    expires_at timestamptz,
    revoked_at timestamptz
);

create table if not exists heartbeat_inbox (
    id bigserial primary key,
    terminal_id bigint not null references terminal(id),
    message_id text not null,
    payload_digest char(64) not null,
    boot_id text,
    sequence bigint,
    occurred_at timestamptz,
    received_at timestamptz not null default now(),
    disposition text not null,
    payload_json jsonb not null,
    unique (terminal_id, message_id)
);

create unique index if not exists uq_heartbeat_boot_sequence
    on heartbeat_inbox(terminal_id, boot_id, sequence)
    where boot_id is not null and sequence is not null;

create index if not exists ix_heartbeat_terminal_received
    on heartbeat_inbox(terminal_id, received_at desc);

create table if not exists terminal_snapshot (
    terminal_id bigint not null references terminal(id),
    snapshot_type text not null,
    version text,
    payload_json jsonb not null,
    received_at timestamptz not null default now(),
    primary key (terminal_id, snapshot_type)
);

create table if not exists terminal_event (
    id bigserial primary key,
    terminal_id bigint not null references terminal(id),
    event_id text not null,
    boot_id text,
    sequence bigint,
    event_type text not null,
    occurred_at timestamptz,
    received_at timestamptz not null default now(),
    payload_digest char(64) not null,
    payload_json jsonb not null,
    unique (terminal_id, event_id)
);

create table if not exists terminal_command (
    id bigserial primary key,
    terminal_id bigint not null references terminal(id),
    message_id text not null,
    command_type text not null,
    payload_json jsonb not null,
    status text not null default 'CREATED',
    created_at timestamptz not null default now(),
    delivered_at timestamptz,
    completed_at timestamptz,
    result_json jsonb,
    unique (terminal_id, message_id)
);

create index if not exists ix_terminal_command_delivery
    on terminal_command(terminal_id, id);

create table if not exists schema_migration (
    version integer primary key,
    name text not null,
    applied_at timestamptz not null default now()
);
"""


MIGRATIONS: tuple[tuple[int, str, str], ...] = (
    (1, "identity-and-command-v2", """
        alter table terminal_credential add column if not exists credential_id uuid;
        alter table terminal_credential add column if not exists version integer;
        alter table terminal_credential add column if not exists not_before timestamptz;
        alter table terminal_credential add column if not exists grace_expires_at timestamptz;
        alter table terminal_credential add column if not exists rotated_from_id bigint references terminal_credential(id);
        alter table terminal_credential add column if not exists last_used_at timestamptz;
        update terminal_credential set credential_id=gen_random_uuid() where credential_id is null;
        update terminal_credential set version=1 where version is null;
        update terminal_credential set not_before=created_at where not_before is null;
        create unique index if not exists uq_terminal_credential_id on terminal_credential(credential_id);
        create unique index if not exists uq_terminal_credential_version on terminal_credential(terminal_id, version);
        create index if not exists ix_terminal_credential_lookup on terminal_credential(terminal_id, token_hash, status);

        create table if not exists terminal_activation (
            id bigserial primary key,
            activation_id uuid not null unique,
            terminal_id bigint not null references terminal(id),
            code_hash char(64) not null unique,
            status text not null default 'PENDING',
            attempt_count integer not null default 0,
            max_attempts integer not null,
            created_at timestamptz not null default now(),
            expires_at timestamptz not null,
            consumed_at timestamptz,
            consumed_credential_id bigint references terminal_credential(id)
        );
        create index if not exists ix_activation_terminal_status on terminal_activation(terminal_id, status, expires_at desc);

        create table if not exists credential_rotation_request (
            id bigserial primary key,
            terminal_id bigint not null references terminal(id),
            idempotency_key text not null,
            request_digest char(64) not null,
            old_credential_id bigint not null references terminal_credential(id),
            new_credential_id bigint not null references terminal_credential(id),
            response_json jsonb not null,
            created_at timestamptz not null default now(),
            unique(terminal_id, idempotency_key)
        );

        alter table terminal_command add column if not exists idempotency_key text;
        alter table terminal_command add column if not exists payload_digest char(64);
        alter table terminal_command add column if not exists revision bigint not null default 0;
        alter table terminal_command add column if not exists expires_at timestamptz;
        alter table terminal_command add column if not exists acked_at timestamptz;
        alter table terminal_command add column if not exists executing_at timestamptz;
        alter table terminal_command add column if not exists last_transition_at timestamptz not null default now();
        update terminal_command set status='DELIVERING' where status='DELIVERED';
        create unique index if not exists uq_terminal_command_idempotency on terminal_command(terminal_id, idempotency_key) where idempotency_key is not null;
        create index if not exists ix_terminal_command_task_id on terminal_command(terminal_id, (payload_json->>'taskId'));
        create index if not exists ix_terminal_command_pending on terminal_command(terminal_id, id) where status in ('CREATED','DELIVERING');

        create table if not exists terminal_command_transition (
            id bigserial primary key,
            command_id bigint not null references terminal_command(id),
            revision bigint not null,
            from_status text,
            to_status text not null,
            actor text not null,
            reason text,
            payload_json jsonb,
            created_at timestamptz not null default now(),
            unique(command_id, revision)
        );
        insert into terminal_command_transition(command_id, revision, from_status, to_status, actor, reason, created_at)
        select id, 0, null, status, 'migration', 'baseline existing command', created_at
          from terminal_command
        on conflict(command_id, revision) do nothing;
    """),
    (2, "public-orders-and-production", """
        create table if not exists sales_order (
            id uuid primary key,
            order_no text not null unique,
            terminal_id bigint not null references terminal(id),
            access_token_hash char(64) not null unique,
            idempotency_key text not null,
            request_digest char(64) not null,
            status text not null,
            payment_mode text not null default 'TEST_FREE',
            payment_status text not null default 'NOT_REQUIRED',
            currency char(3) not null default 'TWD',
            total_amount_minor integer not null default 0,
            recipe_id text not null,
            recipe_version text not null,
            sku_code text,
            product_name text not null,
            product_snapshot jsonb not null,
            failure_code text,
            failure_message text,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            started_at timestamptz,
            completed_at timestamptz,
            cancelled_at timestamptz,
            unique(terminal_id, idempotency_key)
        );
        create index if not exists ix_sales_order_terminal_status
            on sales_order(terminal_id, status, created_at);
        create index if not exists ix_sales_order_created
            on sales_order(created_at desc);

        create table if not exists production_job (
            id uuid primary key,
            task_id text not null unique,
            order_id uuid not null unique references sales_order(id),
            terminal_id bigint not null references terminal(id),
            command_id bigint unique references terminal_command(id),
            status text not null,
            revision bigint not null default 0,
            progress double precision not null default 0,
            current_step_id text,
            current_step_name text,
            planned_duration_seconds double precision,
            step_durations jsonb not null default '[]'::jsonb,
            failure_json jsonb,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            accepted_at timestamptz,
            started_at timestamptz,
            completed_at timestamptz
        );
        create index if not exists ix_production_job_dispatch
            on production_job(terminal_id, status, created_at);

        create table if not exists order_transition (
            id bigserial primary key,
            order_id uuid not null references sales_order(id),
            revision bigint not null,
            from_status text,
            to_status text not null,
            actor text not null,
            reason text,
            payload_json jsonb,
            created_at timestamptz not null default now(),
            unique(order_id, revision)
        );
        create index if not exists ix_order_transition_order
            on order_transition(order_id, revision);
    """),
    (3, "device-authoritative-production-progress", """
        alter table production_job add column if not exists step_progress double precision not null default 0;
        alter table production_job add column if not exists elapsed_seconds double precision not null default 0;
        alter table production_job add column if not exists remaining_seconds double precision;
        alter table production_job add column if not exists last_device_revision bigint not null default 0;
    """),
    (4, "payment-and-device-platform", """
        alter table sales_order alter column payment_mode set default 'ONLINE';
        alter table sales_order alter column payment_status set default 'NOT_STARTED';

        create table if not exists payment (
            id uuid primary key,
            order_id uuid not null references sales_order(id),
            provider text not null,
            merchant_payment_no text not null,
            provider_trade_no text,
            idempotency_key text not null,
            request_digest char(64) not null,
            status text not null,
            revision bigint not null default 0,
            amount_minor integer not null check(amount_minor > 0),
            currency char(3) not null,
            subject text not null,
            qr_code text,
            provider_response jsonb,
            next_reconcile_at timestamptz,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            paid_at timestamptz,
            closed_at timestamptz,
            unique(order_id,idempotency_key),
            unique(provider,merchant_payment_no)
        );
        create unique index if not exists uq_payment_provider_trade
            on payment(provider,provider_trade_no) where provider_trade_no is not null;
        create index if not exists ix_payment_status_updated on payment(status,updated_at);
        create index if not exists ix_payment_reconcile on payment(status,next_reconcile_at);

        create table if not exists payment_event (
            id bigserial primary key,
            payment_id uuid not null references payment(id),
            event_id text not null,
            event_type text not null,
            actor text not null,
            payload_json jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            unique(payment_id,event_id)
        );

        create table if not exists payment_callback_inbox (
            id bigserial primary key,
            provider text not null,
            provider_event_id text not null,
            payment_id uuid references payment(id),
            payload_digest char(64) not null,
            status text not null,
            payload_json jsonb not null,
            received_at timestamptz not null default now(),
            processed_at timestamptz,
            error_message text,
            unique(provider,provider_event_id)
        );

        create table if not exists refund (
            id uuid primary key,
            payment_id uuid not null references payment(id),
            provider text not null,
            merchant_refund_no text not null,
            provider_refund_no text,
            idempotency_key text not null,
            request_digest char(64) not null,
            status text not null,
            revision bigint not null default 0,
            amount_minor integer not null check(amount_minor > 0),
            reason text not null,
            provider_response jsonb,
            attempt_count integer not null default 0,
            next_attempt_at timestamptz,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            completed_at timestamptz,
            unique(payment_id,idempotency_key),
            unique(provider,merchant_refund_no)
        );
        create index if not exists ix_refund_reconcile on refund(status,next_attempt_at);

        create table if not exists business_outbox (
            id uuid primary key,
            event_type text not null,
            aggregate_type text not null,
            aggregate_id text not null,
            payload_json jsonb not null,
            idempotency_key text not null unique,
            status text not null default 'PENDING',
            attempt_count integer not null default 0,
            next_attempt_at timestamptz not null default now(),
            locked_by text,
            locked_until timestamptz,
            last_error text,
            created_at timestamptz not null default now(),
            processed_at timestamptz
        );
        create index if not exists ix_business_outbox_pending
            on business_outbox(status,next_attempt_at) where status in ('PENDING','RETRY');

        create table if not exists mqtt_inbox (
            id bigserial primary key,
            device_id text not null,
            topic text not null,
            message_id text not null,
            message_type text not null,
            boot_id text,
            sequence bigint,
            revision bigint,
            payload_digest char(64) not null,
            payload_json jsonb not null,
            status text not null default 'RECEIVED',
            disposition text,
            received_at timestamptz not null default now(),
            processed_at timestamptz,
            error_message text,
            unique(device_id,message_id)
        );
        create unique index if not exists uq_mqtt_inbox_boot_sequence
            on mqtt_inbox(device_id,boot_id,sequence)
            where boot_id is not null and sequence is not null;

        create table if not exists command_outbox (
            id uuid primary key,
            command_id bigint not null unique references terminal_command(id),
            terminal_id bigint not null references terminal(id),
            topic text not null,
            envelope_json jsonb not null,
            status text not null default 'PENDING',
            attempt_count integer not null default 0,
            next_attempt_at timestamptz not null default now(),
            locked_by text,
            locked_until timestamptz,
            published_at timestamptz,
            last_error text,
            created_at timestamptz not null default now()
        );
        create index if not exists ix_command_outbox_pending
            on command_outbox(status,next_attempt_at) where status in ('PENDING','RETRY','PUBLISHING');

        create table if not exists mqtt_credential (
            id uuid primary key,
            terminal_id bigint not null references terminal(id),
            username text not null,
            secret_hash char(64) not null,
            version integer not null,
            status text not null default 'PENDING_PROVISION',
            created_at timestamptz not null default now(),
            expires_at timestamptz,
            revoked_at timestamptz,
            last_used_at timestamptz,
            broker_synced_at timestamptz,
            unique(terminal_id,version)
        );
        create unique index if not exists uq_mqtt_credential_active_username
            on mqtt_credential(username) where status='ACTIVE';

        create table if not exists security_event (
            id bigserial primary key,
            event_type text not null,
            device_id text,
            source text not null,
            detail_json jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now()
        );
        create index if not exists ix_security_event_created on security_event(created_at desc);

        alter table production_job add column if not exists hold_reason text;
        alter table production_job add column if not exists manual_review_required boolean not null default false;
        alter table terminal_command add column if not exists published_at timestamptz;
        alter table terminal_command add column if not exists hold_reason text;
    """),
    (5, "admin-rbac-audit-and-device-controls", """
        create table if not exists admin_operator (
            id uuid primary key,
            display_name text not null,
            role text not null check(role in ('VIEWER','OPERATOR','MANAGER','OWNER')),
            status text not null default 'ACTIVE' check(status in ('ACTIVE','SUSPENDED')),
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        );

        create table if not exists admin_api_token (
            id uuid primary key,
            operator_id uuid not null references admin_operator(id),
            token_hash char(64) not null unique,
            label text not null,
            status text not null default 'ACTIVE' check(status in ('ACTIVE','REVOKED')),
            expires_at timestamptz,
            last_used_at timestamptz,
            created_at timestamptz not null default now(),
            revoked_at timestamptz
        );
        create index if not exists ix_admin_api_token_operator on admin_api_token(operator_id,created_at desc);

        create table if not exists audit_log (
            id bigserial primary key,
            actor_type text not null,
            actor_id text not null,
            actor_name text not null,
            action text not null,
            resource_type text not null,
            resource_id text,
            request_id text,
            detail_json jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now()
        );
        create index if not exists ix_audit_log_created on audit_log(created_at desc);
        create index if not exists ix_audit_log_resource on audit_log(resource_type,resource_id,created_at desc);
    """),
    (6, "terminal-deployment-profile", """
        alter table terminal add column if not exists device_name text;
        alter table terminal add column if not exists store_name text;
        alter table terminal add column if not exists store_description text;
        alter table terminal add column if not exists city_code text;
        alter table terminal add column if not exists timezone text;
        alter table terminal add column if not exists profile_source text;
        alter table terminal add column if not exists profile_completed_at timestamptz;
    """),
    (7, "latest-telemetry-mode", """
        alter table terminal add column if not exists heartbeat_count bigint not null default 0;
        update terminal as t
           set heartbeat_count = counts.total
          from (
                select terminal_id, count(*)::bigint as total
                  from heartbeat_inbox
                 group by terminal_id
               ) as counts
         where t.id = counts.terminal_id;
    """),
    (8, "event-driven-terminal-dispatch", """
        create table if not exists terminal_dispatch_request (
            terminal_id bigint primary key references terminal(id),
            reason text not null,
            status text not null default 'PENDING' check(status in ('PENDING','PROCESSING','RETRY')),
            requested_at timestamptz not null default now(),
            revision bigint not null default 1,
            attempt_count integer not null default 0,
            next_attempt_at timestamptz not null default now(),
            locked_by text,
            locked_until timestamptz,
            last_error text
        );
        create index if not exists ix_terminal_dispatch_request_ready
            on terminal_dispatch_request(status,next_attempt_at,requested_at);
        create unique index if not exists uq_production_job_active_terminal
            on production_job(terminal_id)
            where status in ('DISPATCHED','ACCEPTED','EXECUTING','HOLD','UNKNOWN');
    """),
)


class Database:
    def __init__(
        self,
        database_url: str,
        *,
        min_size: int = 2,
        max_size: int = 10,
        timeout: float = 10,
    ) -> None:
        self.database_url = database_url
        if min_size > max_size:
            raise ValueError("database pool min_size cannot exceed max_size")
        self.pool = ConnectionPool(
            conninfo=database_url,
            kwargs={"row_factory": dict_row},
            min_size=min_size,
            max_size=max_size,
            timeout=timeout,
            open=False,
        )

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        with self.pool.connection() as connection:
            yield connection

    def initialize(self) -> None:
        self.pool.open(wait=True)
        with self.connect() as connection:
            connection.execute(SCHEMA_SQL)
            for version, name, sql in MIGRATIONS:
                applied = connection.execute("select 1 from schema_migration where version=%s", (version,)).fetchone()
                if applied:
                    continue
                connection.execute(sql)
                connection.execute("insert into schema_migration(version,name) values(%s,%s)", (version, name))

    def ping(self) -> None:
        with self.connect() as connection:
            connection.execute("select 1").fetchone()

    def close(self) -> None:
        self.pool.close()
