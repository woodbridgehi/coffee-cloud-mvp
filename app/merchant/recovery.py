"""Operator alerts, scoped by the already-authorized terminal row."""
from datetime import datetime


def recovery_alerts(c, row):
    status = row.get('reported_status') or {}
    recovery = status.get('recovery')
    pending = c.execute("""select id,payload_json,created_at,hold_reason from terminal_command
        where terminal_id=%s and command_type='MAKE_DRINK' and status='UNKNOWN'
        order by created_at desc""", (row['id'],)).fetchall()
    candidates = {x['payload_json'].get('taskId'): x for x in pending if x['payload_json'].get('taskId')}
    if isinstance(recovery, dict) and isinstance(recovery.get('taskId'), str) and recovery['taskId']:
        candidates.setdefault(recovery['taskId'], {})
    elif status.get('deviceStatus') == 'RECOVERING' and status.get('currentTaskId'):
        candidates.setdefault(status['currentTaskId'], {})
    alerts = []
    for task_id, command in candidates.items():
        event = c.execute("""select x.payload_json,x.created_at from terminal_command_transition x
            join terminal_command cmd on cmd.id=x.command_id
            where cmd.terminal_id=%s and cmd.payload_json->>'taskId'=%s and x.to_status='UNKNOWN'
            order by x.id asc limit 1""", (row['id'], task_id)).fetchone()
        payload = (event or {}).get('payload_json') or {}
        detail = payload.get('payload') or {}
        info = recovery if isinstance(recovery, dict) and recovery.get('taskId') == task_id else detail.get('recovery') or {}
        if not isinstance(info, dict): info = {}
        # Read only tenant-scoped command transitions, never the global event log.
        progress = c.execute("""select x.payload_json from terminal_command_transition x
            join terminal_command cmd on cmd.id=x.command_id where cmd.terminal_id=%s
            and cmd.payload_json->>'taskId'=%s and x.to_status='EXECUTING' order by x.id desc limit 1""",
            (row['id'], task_id)).fetchone()
        progress = (progress or {}).get('payload_json') or {}
        step = info.get('stepName') or (progress.get('payload') or {}).get('currentStepName') or (progress.get('payload') or {}).get('stepName') or (progress.get('payload') or {}).get('stepId') or '未记录'
        order_id = detail.get('orderId') or command.get('payload_json', {}).get('orderId') or ''
        kind = info.get('taskKind') or ('DEBUG' if str(order_id).startswith('debug-') else 'ORDER')
        occurred = info.get('detectedAt') or payload.get('occurredAt') or (event or {}).get('created_at')
        if isinstance(occurred, datetime): occurred = occurred.isoformat()
        reason = info.get('reason') or '制作结果未知，需在终端核对杯子和工作区后取消中断任务'
        alerts.append({'id': 'recovery:'+task_id, 'severity': 'ERROR', 'code': info.get('reasonCode') or command.get('hold_reason') or 'DEVICE_RESTARTED_OUTCOME_UNKNOWN',
                       'title': (row.get('device_name') or row['device_id'])+' · 重启中断／待人工处理',
                       'description': ('调试任务' if kind == 'DEBUG' else '订单任务')+' · '+str(step)+' · '+str(reason),
                       'deviceId': str(row['id']), 'taskId': task_id, 'taskKind': kind, 'occurredAt': occurred,
                       'stepName': step, 'reason': reason, 'action': 'VERIFY_AT_TERMINAL'})
    return alerts
