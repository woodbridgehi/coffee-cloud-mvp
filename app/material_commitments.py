"""Conservative admission against shared stock; terminal remains authoritative."""
import math


def requirements(value):
    if not isinstance(value, dict) or not value:
        return None
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or
           not math.isfinite(v) or v <= 0 for v in value.values()):
        return None
    return value


def apply_commitments(menu, inventory, commitments, required_version=0):
    available = {m['materialId']: max(0, float(m.get('available', 0)))
                 for m in (inventory or {}).get('materials', [])}
    unknown = False
    for order in commitments:
        demand = requirements((order.get('product_snapshot') or {}).get('materialRequirements'))
        if demand is None:
            unknown = True
            continue
        for material, amount in demand.items():
            available[material] = max(0, available.get(material, 0) - amount)
    for product in menu['products']:
        demand = requirements(product.get('materialRequirements'))
        # Legacy devices cannot safely share a multi-order queue.
        count = product['remainingServings']
        if unknown or (commitments and demand is None):
            count = 0
        elif demand:
            count = min(count, min(int((available.get(mid, 0) + 1e-9) // amount)
                                   for mid, amount in demand.items()))
        product['remainingServings'] = count
        if count <= 0:
            product['available'] = False
            product['unavailableReasons'] = sorted(set(product['unavailableReasons'] + ['QUEUE_MATERIAL_COMMITTED']))
        if int((inventory or {}).get('inventoryVersion') or 0) < required_version:
            product['available'] = False
            product['unavailableReasons'] = sorted(set(product['unavailableReasons'] + ['INVENTORY_SYNC_PENDING']))
    menu['salesEnabled'] = any(p['available'] for p in menu['products'])
    return menu
