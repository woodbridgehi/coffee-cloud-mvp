SCHEMA = """
alter table merchant_user alter column email drop not null;
alter table merchant_user add column username text unique;
alter table merchant_user add constraint merchant_username_format
 check(username is null or username ~ '^[a-z][a-z0-9_.-]{2,31}$');
alter table merchant_user add constraint merchant_login_identity
 check(email is not null or username is not null);
"""
