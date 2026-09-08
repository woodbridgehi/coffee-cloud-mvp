from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.order_logic import public_menu, terminal_is_online
from app.services.production import ProductionService


def test_explicit_offline_blocks_menu_and_dispatch_despite_fresh_heartbeat():
    terminal = {"connection_status": "offline", "last_heartbeat_at": datetime.now(timezone.utc),
                "lifecycle_status": "ACTIVE"}
    assert not terminal_is_online(terminal, 90)
    menu = public_menu(terminal, {"products": [{"name": "coffee", "available": True, "maxServings": 5}]}, {}, 90)
    assert not menu["salesEnabled"]
    with patch("app.services.production.OrderRepository") as repository:
        repository.return_value.terminal_for_update.return_value = terminal
        service = ProductionService(SimpleNamespace(offline_threshold_seconds=90), payment_provider=lambda _: None)
        assert service.dispatch_next_order(None, 1) is None
        repository.return_value.next_queued_job.assert_not_called()
    terminal["connection_status"] = "online"
    assert terminal_is_online(terminal, 90)
