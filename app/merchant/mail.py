"""Encrypted email outbox sender; never logs message bodies or link tokens."""
import json
import smtplib
import ssl
from email.message import EmailMessage

from .security import cipher


def deliver_one(database, settings):
    if not settings.merchant_enabled or not settings.merchant_smtp_host or not settings.merchant_mail_from:
        return False
    with database.connect() as c:
        row = c.execute("""select * from merchant_mail_outbox where status='PENDING' and next_attempt_at<=now()
            order by created_at for update skip locked limit 1""").fetchone()
        if not row:
            return False
        try:
            content = json.loads(cipher(settings.merchant_encryption_key).decrypt(row['encrypted_message'].encode()))
            message = EmailMessage()
            message['From'], message['To'], message['Subject'] = settings.merchant_mail_from, row['recipient'], content['subject']
            message.set_content(content['body'])
            context = ssl.create_default_context()
            client = smtplib.SMTP_SSL(settings.merchant_smtp_host, settings.merchant_smtp_port, timeout=10, context=context) \
                if settings.merchant_smtp_port == 465 else smtplib.SMTP(settings.merchant_smtp_host, settings.merchant_smtp_port, timeout=10)
            with client:
                if settings.merchant_smtp_port != 465:
                    client.starttls(context=context)
                if settings.merchant_smtp_user:
                    client.login(settings.merchant_smtp_user, settings.merchant_smtp_password or '')
                client.send_message(message)
            c.execute("update merchant_mail_outbox set status='SENT',sent_at=now(),encrypted_message='',last_error=null where id=%s", (row['id'],))
        except Exception:
            c.execute("""update merchant_mail_outbox set attempts=attempts+1,last_error='DELIVERY_FAILED',
                status=case when attempts>=9 then 'FAILED' else 'PENDING' end,
                next_attempt_at=now()+interval '1 minute'*least(60,power(2,attempts)) where id=%s""", (row['id'],))
        return True
