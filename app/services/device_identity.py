from __future__ import annotations

import logging
import secrets
import uuid
from datetime import timedelta
from typing import Any, Callable

from ..db import UnitOfWork
from ..protocol import DeviceOnboardingProfile, canonical_digest, utc_now
from ..repositories import IdentityRepository, TerminalRepository
from ..security import hash_token, tokens_equal
from .errors import ServiceError
from .presenters import iso


class DeviceIdentityService:
    def __init__(
        self, uow: UnitOfWork, *, settings: Any,
        provisioner_factory: Callable[[], Any | None], logger: logging.Logger,
    ) -> None:
        self.uow = uow
        self.settings = settings
        self.provisioner_factory = provisioner_factory
        self.logger = logger

    @staticmethod
    def credential_payload(row: dict[str, Any], *, duplicate: bool = False) -> dict[str, Any]:
        return {
            "credentialId": str(row["credential_id"]), "version": row["version"],
            "status": row["status"], "notBefore": iso(row.get("not_before")),
            "expiresAt": iso(row.get("expires_at")),
            "graceExpiresAt": iso(row.get("grace_expires_at")), "duplicate": duplicate,
        }

    @staticmethod
    def _terminal(repository: TerminalRepository, identifier: str, *, for_update: bool = False) -> dict[str, Any]:
        terminal = repository.find(identifier, for_update=for_update)
        if not terminal:
            raise ServiceError(404, "device not found")
        return terminal

    def authenticate(self, device_id: str, header_device: str | None, token: str | None) -> dict[str, Any]:
        if header_device != device_id:
            raise ServiceError(401, "device identity mismatch")
        if token is None:
            raise ServiceError(401, "missing device credential")
        with self.uow.transaction() as connection:
            identity = IdentityRepository(connection).authenticate(device_id, hash_token(token))
        if not identity:
            raise ServiceError(401, "invalid device credential")
        return identity

    def bootstrap_device(self) -> None:
        if not self.settings.bootstrap_device_enabled:
            return
        if not self.settings.device_token:
            raise RuntimeError("DEVICE_TOKEN is required when BOOTSTRAP_DEVICE_ENABLED=true")
        token_hash = hash_token(self.settings.device_token)
        now = utc_now()
        with self.uow.transaction() as connection:
            terminal = TerminalRepository(connection).upsert_bootstrap(
                device_id=self.settings.device_id,
                serial_number=self.settings.device_serial_number,
                instance_id=self.settings.device_instance_id,
                store_id=self.settings.device_store_id,
            )
            identity = IdentityRepository(connection)
            if not identity.token_exists(token_hash):
                identity.create_http_credential(
                    terminal_id=terminal["id"], token_hash=token_hash,
                    version=identity.next_http_version(terminal["id"]), now=now,
                )

    def create_activation_code(self, identifier: str, ttl_seconds: int | None) -> dict[str, Any]:
        ttl = ttl_seconds or self.settings.activation_ttl_seconds
        code = secrets.token_urlsafe(24)
        activation_id = uuid.uuid4()
        expires_at = utc_now() + timedelta(seconds=ttl)
        with self.uow.transaction() as connection:
            terminal = self._terminal(TerminalRepository(connection), identifier, for_update=True)
            identity = IdentityRepository(connection)
            identity.cancel_pending_activations(terminal["id"])
            identity.create_activation((
                activation_id, terminal["id"], hash_token(code),
                self.settings.activation_max_attempts, expires_at,
            ))
        return {
            "activationId": str(activation_id), "deviceId": terminal["device_id"],
            "activationCode": code, "expiresAt": iso(expires_at),
            "warning": "activationCode is returned once and must not be logged",
        }

    def activate(
        self, device_id: str, activation_code: str, device_token: str,
        profile: DeviceOnboardingProfile | None = None, serial_number: str | None = None,
    ) -> dict[str, Any]:
        code_hash = hash_token(activation_code)
        token_hash = hash_token(device_token)
        now = utc_now()
        with self.uow.transaction() as connection:
            terminal = self._terminal(TerminalRepository(connection), device_id, for_update=True)
            if serial_number is not None and terminal["serial_number"] != serial_number:
                raise ServiceError(409, "device serial number does not match pre-registration")
            repository = IdentityRepository(connection)
            activation = repository.activation_by_code(terminal["id"], code_hash)
            if activation is None:
                pending = repository.pending_activation(terminal["id"])
                if pending:
                    attempts = pending["attempt_count"] + 1
                    repository.record_failed_attempt(
                        pending["id"], attempts,
                        "LOCKED" if attempts >= pending["max_attempts"] else "PENDING",
                    )
                raise ServiceError(401, "invalid or expired activation code")
            if activation["status"] == "CONSUMED":
                credential = repository.credential_by_id(activation["consumed_credential_id"])
                if credential and tokens_equal(credential["token_hash"].strip(), token_hash):
                    return {
                        "deviceId": terminal["device_id"], **self.credential_payload(credential, duplicate=True),
                        "profile": self.profile_payload(terminal),
                    }
                raise ServiceError(409, "activation code already consumed")
            if activation["status"] != "PENDING" or activation["expires_at"] <= now:
                if activation["status"] == "PENDING":
                    repository.expire_activation(activation["id"])
                raise ServiceError(401, "invalid or expired activation code")
            if repository.token_exists(token_hash):
                raise ServiceError(409, "credential token already registered")
            version = repository.next_http_version(terminal["id"])
            repository.grace_active_http_credentials(
                terminal["id"], now + timedelta(seconds=self.settings.credential_grace_seconds)
            )
            credential = repository.create_http_credential(
                terminal_id=terminal["id"], token_hash=token_hash, version=version, now=now
            )
            repository.consume_activation(activation["id"], credential["id"], now)
            repository.activate_terminal(terminal["id"], now)
            if profile is not None:
                terminal = TerminalRepository(connection).complete_onboarding_profile(
                    terminal["id"], profile.model_dump()
                )
        return {
            "deviceId": terminal["device_id"], **self.credential_payload(credential),
            "profile": self.profile_payload(terminal),
            "mqttCredential": self.issue_mqtt_credential(terminal),
        }

    @staticmethod
    def profile_payload(terminal: dict[str, Any]) -> dict[str, Any]:
        return {
            "deviceName": terminal.get("device_name"), "storeId": terminal.get("store_id"),
            "storeName": terminal.get("store_name"), "storeDescription": terminal.get("store_description"),
            "cityCode": terminal.get("city_code"), "timezone": terminal.get("timezone"),
            "source": terminal.get("profile_source"),
        }

    def issue_mqtt_credential(self, terminal: dict[str, Any]) -> dict[str, Any]:
        password = secrets.token_urlsafe(36)
        credential_id = uuid.uuid4()
        with self.uow.transaction() as connection:
            repository = IdentityRepository(connection)
            version = repository.next_mqtt_version(terminal["id"])
            repository.create_pending_mqtt(credential_id, terminal, hash_token(password), version)
        broker_status = "PENDING_PROVISION"
        provisioner = self.provisioner_factory()
        if provisioner:
            try:
                provisioner.provision_device(terminal["device_id"], password)
                with self.uow.transaction() as connection:
                    IdentityRepository(connection).activate_mqtt(terminal["id"], credential_id)
                broker_status = "ACTIVE"
            except Exception:
                self.logger.exception("MQTT credential broker provisioning failed device=%s", terminal["device_id"])
        return {
            "credentialId": str(credential_id), "version": version, "status": broker_status,
            "username": terminal["device_id"], "password": password,
            "host": "mqtt-api.woodbridge.top", "port": 8883, "tls": True,
            "warning": "MQTT password is returned once and must not be logged",
        }

    def revoke_mqtt(self, identifier: str) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            terminal = self._terminal(TerminalRepository(connection), identifier, for_update=True)
            changed = IdentityRepository(connection).revoke_mqtt(terminal["id"])
        provisioner = self.provisioner_factory()
        broker_status = "NOT_CONFIGURED"
        if provisioner:
            try:
                provisioner.revoke_device(terminal["device_id"])
                broker_status = "REVOKED"
            except Exception as exc:
                self.logger.exception("MQTT credential broker revoke failed device=%s", terminal["device_id"])
                broker_status = f"RETRY_REQUIRED:{type(exc).__name__}"
        return {"deviceId": terminal["device_id"], "revokedCredentials": changed, "brokerStatus": broker_status}

    def rotate_http(
        self, identity: dict[str, Any], device_id: str, new_token: str, idempotency_key: str | None,
        request_body: dict[str, Any],
    ) -> dict[str, Any]:
        if not idempotency_key or len(idempotency_key) > 160:
            raise ServiceError(400, "Idempotency-Key is required and must be <= 160 characters")
        token_hash = hash_token(new_token)
        digest = canonical_digest(request_body)
        now = utc_now()
        grace_expires_at = now + timedelta(seconds=self.settings.credential_grace_seconds)
        with self.uow.transaction() as connection:
            repository = IdentityRepository(connection)
            existing = repository.rotation_request(identity["id"], idempotency_key)
            if existing:
                if existing["request_digest"].strip() != digest:
                    raise ServiceError(409, "Idempotency-Key payload conflict")
                return {**existing["response_json"], "duplicate": True}
            old = repository.credential_by_id(identity["credential_db_id"], for_update=True)
            if not old:
                raise ServiceError(401, "credential no longer exists")
            if tokens_equal(old["token_hash"].strip(), token_hash):
                raise ServiceError(400, "new credential must differ from current credential")
            if repository.token_exists(token_hash):
                raise ServiceError(409, "credential token already registered")
            repository.grace_http_credential(old["id"], grace_expires_at)
            credential = repository.create_http_credential(
                terminal_id=identity["id"], token_hash=token_hash,
                version=repository.next_http_version(identity["id"]), now=now, rotated_from_id=old["id"],
            )
            response = {
                "deviceId": device_id, **self.credential_payload(credential),
                "previousCredentialGraceExpiresAt": iso(grace_expires_at),
            }
            repository.save_rotation_request(
                identity["id"], idempotency_key, digest, old["id"], credential["id"], response
            )
        return response

    def list_http(self, identifier: str) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            terminal = self._terminal(TerminalRepository(connection), identifier)
            rows = IdentityRepository(connection).list_http_credentials(terminal["id"])
        return {"deviceId": terminal["device_id"], "credentials": [self.credential_payload(row) for row in rows]}

    def revoke_http(self, identifier: str, credential_id: uuid.UUID) -> dict[str, Any]:
        with self.uow.transaction() as connection:
            terminal = self._terminal(TerminalRepository(connection), identifier)
            repository = IdentityRepository(connection)
            before = repository.http_credential(terminal["id"], credential_id)
            if not before:
                raise ServiceError(404, "credential not found")
            duplicate = before["status"] == "REVOKED"
            credential = repository.revoke_http_credential(terminal["id"], credential_id) or before
        return {"deviceId": terminal["device_id"], **self.credential_payload(credential, duplicate=duplicate)}
