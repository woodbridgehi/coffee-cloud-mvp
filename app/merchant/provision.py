"""Provision the NOLOGIN, non-owner tenant role using migration credentials.

Run after migrations, before enabling MERCHANT_ENABLED. Runtime SQL never creates
roles or grants privileges. Role grants are restricted to this database schema.
"""
from psycopg import sql


def provision_role(connection, role: str):
    role_id = sql.Identifier(role)
    exists = connection.execute('select rolsuper,rolbypassrls,rolcanlogin from pg_roles where rolname=%s', (role,)).fetchone()
    if exists:
        if exists['rolsuper'] or exists['rolbypassrls'] or exists['rolcanlogin']:
            raise RuntimeError('merchant role must be NOLOGIN NOSUPERUSER NOBYPASSRLS')
    else:
        connection.execute(sql.SQL('create role {} nologin nosuperuser nocreatedb nocreaterole noinherit nobypassrls').format(role_id))
    schema = connection.execute('select current_schema() as name').fetchone()['name']
    current = connection.execute('select current_user as name').fetchone()['name']
    member = connection.execute('select pg_has_role(current_user,%s,\'MEMBER\') as allowed', (role,)).fetchone()['allowed']
    if not member:
        connection.execute(sql.SQL('grant {} to {}').format(role_id, sql.Identifier(current)))
    connection.execute(sql.SQL('grant usage on schema {} to {}').format(sql.Identifier(schema), role_id))
    connection.execute(sql.SQL('grant select,insert,update on {}.merchant_store to {}').format(sql.Identifier(schema), role_id))
    connection.execute(sql.SQL('grant select,insert on {}.merchant_audit to {}').format(sql.Identifier(schema), role_id))
    for table in ('terminal', 'sales_order', 'merchant_device_ownership', 'merchant_price'):
        connection.execute(sql.SQL('grant select on {}.{} to {}').format(sql.Identifier(schema), sql.Identifier(table), role_id))
    for table in ('terminal','sales_order','payment','refund','production_job','terminal_command','terminal_command_transition',
                  'command_outbox','payment_event','order_transition','merchant_operation','merchant_price','merchant_payment_account',
                  'merchant_material','merchant_purchase','merchant_stock','merchant_expense','merchant_daily_summary'):
        connection.execute(sql.SQL('grant select,insert,update on {}.{} to {}').format(sql.Identifier(schema),sql.Identifier(table),role_id))
    for table in ('terminal_snapshot',):
        connection.execute(sql.SQL('grant select on {}.{} to {}').format(sql.Identifier(schema),sql.Identifier(table),role_id))
    for table in ('merchant_ledger','merchant_inventory_movement'):
        connection.execute(sql.SQL('grant select,insert on {}.{} to {}').format(sql.Identifier(schema),sql.Identifier(table),role_id))
    for table in ('terminal_command','terminal_command_transition','payment_event','order_transition'):
        sequence=connection.execute('select pg_get_serial_sequence(%s,%s) as name',(schema+'.'+table,'id')).fetchone()['name']
        if sequence:
            connection.execute(sql.SQL('grant usage on sequence {} to {}').format(sql.Identifier(*sequence.split('.')),role_id))


def main():
    from ..database import Database
    from ..settings import get_settings
    settings = get_settings()
    database = Database(settings.database_url, min_size=1, max_size=1)
    database.initialize(run_migrations=False)
    try:
        with database.connect() as c:
            provision_role(c, settings.merchant_runtime_role)
    finally:
        database.close()


if __name__ == '__main__':
    main()
