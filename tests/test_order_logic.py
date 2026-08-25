from datetime import datetime, timezone

from app.order_logic import device_progress, order_state_for_event, public_menu
from app.security import derive_order_access_token


def terminal() -> dict:
    return {
        "device_id": "coffee-bot-001",
        "store_id": "store-1",
        "lifecycle_status": "ACTIVE",
        "last_heartbeat_at": datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc),
        "reported_status": {"deviceStatus": "IDLE"},
    }


def test_public_menu_combines_capability_and_connection_state() -> None:
    capabilities = {"products": [{
        "recipeId": "latte-v1", "version": "1", "skuCode": "LATTE", "name": "拿铁",
        "enabled": True, "available": True, "maxServings": 8,
        "display": {"description": "鲜奶咖啡", "sortOrder": 1},
        "visual": {"profile": "iced-latte"}, "estimatedDurationSeconds": 60,
    }]}
    inventory = {"inventoryVersion": 3, "materials": [{"materialId": "milk", "name": "牛奶", "status": "LOW"}]}
    result = public_menu(
        terminal(), capabilities, inventory, 30,
        now=datetime(2026, 8, 25, 10, 0, 10, tzinfo=timezone.utc),
    )
    assert result["online"] is True
    assert result["salesEnabled"] is True
    assert result["products"][0]["remainingServings"] == 8
    assert result["materialAlertCount"] == 1


def test_offline_terminal_disables_all_products() -> None:
    capabilities = {"products": [{
        "recipeId": "espresso", "version": "1", "name": "浓缩", "enabled": True,
        "available": True, "maxServings": 10,
    }]}
    result = public_menu(
        terminal(), capabilities, {"materials": []}, 30,
        now=datetime(2026, 8, 25, 10, 1, tzinfo=timezone.utc),
    )
    assert result["online"] is False
    assert result["products"][0]["available"] is False
    assert "DEVICE_OFFLINE" in result["products"][0]["unavailableReasons"]


def test_order_event_mapping_and_access_token_are_stable() -> None:
    assert order_state_for_event("task.started") == ("MAKING", "EXECUTING")
    assert order_state_for_event("task.succeeded") == ("READY", "SUCCEEDED")
    first = derive_order_access_token("secret", "device", "request")
    assert first == derive_order_access_token("secret", "device", "request")
    assert first != derive_order_access_token("secret", "device", "another")


def test_device_authoritative_progress_is_separate_from_step_progress() -> None:
    overall, step = device_progress(
        {"progress": 0.4, "stepProgress": 0.4, "overallProgress": 0.24},
        current_overall=0.2,
        current_step=0.3,
    )
    assert overall == 0.24
    assert step == 0.4

    legacy_overall, legacy_step = device_progress({"progress": 0.1}, current_overall=0.8)
    assert legacy_overall == 0.8
    assert legacy_step == 0.1
