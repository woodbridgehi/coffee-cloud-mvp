from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.services.admin_access import AdminAccessService, ROLE_PERMISSIONS
from app.services.admin_operations import AdminOperationsService
from app.services.errors import ServiceError


class NoDatabaseUnitOfWork:
    def transaction(self):  # pragma: no cover - bootstrap auth must not query storage
        raise AssertionError("bootstrap authentication unexpectedly accessed the database")


def service() -> AdminAccessService:
    return AdminAccessService(
        NoDatabaseUnitOfWork(),  # type: ignore[arg-type]
        SimpleNamespace(admin_token="bootstrap-admin-token-at-least-24-characters"),  # type: ignore[arg-type]
    )


def test_bootstrap_admin_is_owner_without_database_lookup() -> None:
    principal = service().authenticate("bootstrap-admin-token-at-least-24-characters")
    assert principal["role"] == "OWNER"
    assert principal["actorType"] == "BOOTSTRAP"
    assert set(principal["permissions"]) == set(ROLE_PERMISSIONS["OWNER"])


def test_role_permissions_are_monotonic_and_viewer_cannot_mutate() -> None:
    assert ROLE_PERMISSIONS["VIEWER"] < ROLE_PERMISSIONS["OPERATOR"]
    assert ROLE_PERMISSIONS["OPERATOR"] < ROLE_PERMISSIONS["MANAGER"]
    assert ROLE_PERMISSIONS["MANAGER"] < ROLE_PERMISSIONS["OWNER"]
    assert "devices.manage" not in ROLE_PERMISSIONS["VIEWER"]
    assert "access.manage" not in ROLE_PERMISSIONS["MANAGER"]


def test_permission_check_rejects_missing_capability() -> None:
    principal = {"permissions": sorted(ROLE_PERMISSIONS["VIEWER"])}
    with pytest.raises(ServiceError) as error:
        service().require(principal, "devices.manage")
    assert error.value.status_code == 403


def test_pending_device_cannot_bypass_activation_via_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeUnitOfWork:
        @contextmanager
        def transaction(self):
            yield object()

    class FakeTerminalRepository:
        def __init__(self, _: object) -> None:
            pass

        def find(self, _: str, *, for_update: bool = False) -> dict[str, object]:
            assert for_update
            return {"id": 1, "lifecycle_status": "PENDING"}

        def update_lifecycle(self, *_: object) -> None:  # pragma: no cover - safety guard
            raise AssertionError("pending terminal lifecycle was updated")

    monkeypatch.setattr(
        "app.services.admin_operations.TerminalRepository", FakeTerminalRepository
    )
    operations = AdminOperationsService(
        FakeUnitOfWork(),  # type: ignore[arg-type]
        offline_threshold_seconds=30,
        refresh_offline_status=lambda: None,
    )

    with pytest.raises(ServiceError) as error:
        operations.update_lifecycle("coffee-bot-pending", "ACTIVE")
    assert error.value.status_code == 409
