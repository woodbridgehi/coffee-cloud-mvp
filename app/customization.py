"""Select terminal-compiled variants; never duplicate terminal dose arithmetic."""
import hashlib
import hmac
import json
import time
from copy import deepcopy
from .services.errors import ServiceError


def select_variant(product, options, inventory, terminal_ready):
    schema = product.get('optionSchema')
    if not schema:
        if options: raise ServiceError(422, 'customization is not supported')
        return product
    rules = schema['options']
    if set(options or {}) - set(rules): raise ServiceError(422, 'unsupported customization option')
    choices = {key: (options or {}).get(key, rule['default']) for key, rule in rules.items()}
    variant = next((v for v in product.get('customizationVariants', []) if v['customization'] == choices), None)
    if variant is None: raise ServiceError(422, 'unsupported customization combination')
    product = deepcopy({key: value for key, value in product.items() if key != 'customizationVariants'})
    product.update(variant)
    product['priceMinor'] += variant['priceDeltaMinor']
    amounts = {m['materialId']: float(m.get('available', 0)) for m in (inventory or {}).get('materials', [])}
    requirements = variant.get('materialRequirements') or {}
    if not requirements:
        raise ServiceError(422, 'customization has no material requirements')
    product['remainingServings'] = max(0, min(int((amounts.get(mid, 0) + 1e-9) // amount) for mid, amount in requirements.items()))
    reasons = [r for r in product.get('unavailableReasons', []) if r != 'MATERIAL_INSUFFICIENT']
    product['available'] = terminal_ready and not reasons and product['remainingServings'] > 0
    if product['remainingServings'] <= 0: reasons.append('MATERIAL_INSUFFICIENT')
    product['unavailableReasons'] = reasons
    return product


def fingerprint(device_id, product, payment_mode):
    value = {k: product.get(k) for k in ('recipeId', 'recipeVersion', 'customization', 'optionSchemaVersion', 'compiledRecipeDigest', 'priceMinor', 'priceVersion', 'currency')}
    value.update(deviceId=device_id, paymentMode=payment_mode)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def issue_quote(secret, device_id, product, payment_mode, expires=None):
    expires = int(time.time()) + 300 if expires is None else expires
    value = f'{expires}.{fingerprint(device_id, product, payment_mode)}'
    signature = hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f'{value}.{signature}'


def check_quote(token, secret, device_id, product, payment_mode):
    try:
        expires = int(token.split('.')[0])
        if expires < time.time() or expires > time.time() + 301: raise ValueError()
        expected = issue_quote(secret, device_id, product, payment_mode, expires)
        if not hmac.compare_digest(token, expected): raise ValueError()
    except (AttributeError, TypeError, ValueError):
        raise ServiceError(409, {'code': 'QUOTE_CHANGED', 'message': 'quote expired or recipe/price changed; confirm a new quote'})
