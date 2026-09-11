"""Consistent failure projection for old and new device event contracts."""
REASONS = {
    'COMPILED_RECIPE_MISMATCH': ('云端指令缺少配方指纹，或配方与设备不一致，设备已拒绝制作。', '核对云端与终端版本，同步设备菜单；确认配方版本和指纹后重新下单。'),
    'RECIPE_VERSION_MISMATCH': ('订单配方版本与设备已安装版本不一致。', '同步配方和菜单，刷新点单页后重新下单。'),
    'RECIPE_NOT_FOUND': ('设备未安装该饮品配方。', '检查设备配方目录和无效配方列表，同步菜单。'),
    'RECIPE_DISABLED': ('该饮品配方已停用。', '核对配方启用状态和菜单缓存。'),
    'INVALID_CUSTOMIZATION': ('饮品定制选项无法执行。', '检查选项、奶量、糖量及定制规则版本。'),
    'MATERIAL_INSUFFICIENT': ('设备物料不足，无法制作。', '核对库存、预占量和本单物料需求，补料后重新下单。'),
    'PICKUP_OCCUPIED': ('取杯位仍被占用，设备无法开始制作。', '确认杯子取走后，通过取杯确认操作释放取杯位。'),
    'DEVICE_BUSY': ('设备正在处理其他任务，暂时无法接单。', '核对设备当前任务与云端排队状态。'),
    'COMMAND_EXPIRED': ('制作指令已超时。', '检查设备连接、消息送达与确认时间；先核实是否已制作。'),
    'PRODUCTION_FAILED': ('设备制作失败，未提供具体故障原因。', '通过订单号和任务编号检查设备事件日志。'),
    'COMMAND_REJECTED': ('设备拒绝了制作指令，未提供具体原因。', '通过任务编号检查设备拒绝事件及指令回执。'),
}
DETAIL_FIELDS = {'recipeId', 'requested', 'installed', 'installedVersion', 'requestedDigest', 'installedDigest',
                 'message', 'materialId', 'required', 'available', 'expiresAt', 'field', 'missingFields'}


def failure_info(order, job=None, *, internal=False):
    job = job or {}
    raw = job.get('failure_json') or {}
    if not isinstance(raw, dict):
        raw = {}
    code = order.get('failure_code') or raw.get('code') or raw.get('errorCode') or raw.get('reasonCode')
    if not isinstance(code, str):
        code = None
    if not code and (order.get('status') == 'FAILED' or job.get('status') in ('FAILED', 'REJECTED')):
        code = 'COMMAND_REJECTED' if job.get('status') == 'REJECTED' else 'PRODUCTION_FAILED'
    if not code:
        return None
    original = raw.get('message') or order.get('failure_message')
    if not isinstance(original, str):
        original = None
    friendly, action = REASONS.get(code, (f'设备报告错误：{code}', '核对故障步骤、设备日志和物料状态。'))
    generic = not original or original in ('制作失败', '任务失败') or original.startswith('任务被拒绝：')
    result = {'code': code, 'message': friendly if generic else original}
    if internal:
        details = raw.get('details') or {}
        result.update(stepId=raw.get('stepId') or job.get('current_step_id'),
                      stepName=raw.get('stepName') or job.get('current_step_name'),
                      taskId=job.get('task_id'), occurredAt=job.get('completed_at') or job.get('updated_at'),
                      retryable=raw.get('retryable'), suggestion=action, deviceMessage=original,
                      details={k: v for k,v in details.items() if k in DETAIL_FIELDS} if isinstance(details, dict) else {})
    return result
