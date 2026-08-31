from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
from cryptography.fernet import Fernet


class MerchantError(Exception):
    def __init__(self, status: int, code: str, message: str, fields: dict | None = None):
        self.status, self.code, self.message, self.fields = status, code, message, fields
        super().__init__(message)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# Bound memory under concurrent login attempts. Rate limiting is also applied
# transactionally before entering the KDF across API worker processes.
_hash_slots = threading.BoundedSemaphore(2)


def hash_password(password: str, *, salt: str | None = None) -> str:
    if not isinstance(password, str) or not 15 <= len(password) <= 128:
        raise MerchantError(422, 'INVALID_PASSWORD', '密码须为15至128个字符', {'password': '密码须为15至128个字符'})
    salt = salt or secrets.token_hex(16)
    with _hash_slots:
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**17,
                                r=8, p=1, maxmem=192 * 1024 * 1024, dklen=32).hex()
    return f'scrypt$131072$8$1${salt}${digest}'


def verify_password(password: str, encoded: str) -> bool:
    try:
        method, n, r, p, salt, digest = encoded.split('$')
        if (method, n, r, p) != ('scrypt', '131072', '8', '1'):
            return False
        actual = hash_password(password, salt=salt).split('$')[-1]
        return hmac.compare_digest(actual, digest)
    except (ValueError, MerchantError):
        return False


def cipher(key: str | None) -> Fernet:
    if not key:
        raise MerchantError(503, 'NOT_CONFIGURED', '客户服务密钥尚未配置')
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise MerchantError(503, 'NOT_CONFIGURED', '客户服务密钥配置无效') from exc


OWNER = frozenset('''dashboard.read devices.read devices.manage devices.claim devices.transfer
commands.execute stores.read stores.manage orders.read refunds.manage prices.read prices.manage
inventory.read inventory.manage costs.read costs.manage reports.read reports.export members.read
members.manage payments.read payments.manage tenant.manage audit.read'''.split())
PERMISSIONS = {
    'OWNER': OWNER,
    'OPERATOR': frozenset('''dashboard.read devices.read devices.manage commands.execute stores.read
orders.read prices.read inventory.read inventory.manage'''.split()),
    'FINANCE': frozenset('''dashboard.read devices.read stores.read orders.read costs.read reports.read
reports.export prices.read inventory.read'''.split()),
}
