class PickupConflict(ValueError):
    pass


class PickupRepository:
    def __init__(self, connection):
        self.connection = connection

    def blocked(self, terminal_id):
        row = self.connection.execute('select state from terminal_pickup_slot where terminal_id=%s',
                                      (terminal_id,)).fetchone()
        return bool(row and row['state'] != 'EMPTY')

    def apply(self, terminal_id, slot, collected=False):
        # Keep the order -> slot lock order on every event path.
        order = self.connection.execute('''select o.id from sales_order o
            join production_job j on j.order_id=o.id
            where j.terminal_id=%s and j.task_id=%s for update of o''',
            (terminal_id, slot['taskId'])).fetchone()
        if order:
            self.connection.execute('''update sales_order set pickup_required=true,
                collected_at=case when %s then coalesce(collected_at,now()) else collected_at end
                where id=%s''', (collected, order['id']))
        applied = self.connection.execute('''insert into terminal_pickup_slot(terminal_id,revision,state,task_id)
            values(%s,%s,%s,%s) on conflict(terminal_id) do update set
            revision=excluded.revision,state=excluded.state,task_id=excluded.task_id,updated_at=now()
            where terminal_pickup_slot.revision<excluded.revision returning revision''',
            (terminal_id,slot['revision'],slot['state'],slot['taskId'])).fetchone()
        if not applied:
            current = self.connection.execute('select * from terminal_pickup_slot where terminal_id=%s', (terminal_id,)).fetchone()
            if current['revision'] == slot['revision'] and (current['state'] != slot['state'] or current['task_id'] != slot['taskId']):
                raise PickupConflict('conflicting pickup state at the same revision')
