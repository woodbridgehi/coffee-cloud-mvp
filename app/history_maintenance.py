"""Drain expired history in small batches, yielding between backlog passes."""


class HistoryMaintenance:
    def __init__(self, interval_seconds: float, batch_size: int, backlog_delay: float = 5) -> None:
        self.interval_seconds = interval_seconds
        self.batch_size = batch_size
        self.backlog_delay = backlog_delay
        self.next_at = 0.0

    def due(self, now: float) -> bool:
        return now >= self.next_at

    def completed(self, now: float, counts: dict[str, int]) -> None:
        backlog = any(count >= self.batch_size for count in counts.values())
        self.next_at = now + (self.backlog_delay if backlog else self.interval_seconds)
