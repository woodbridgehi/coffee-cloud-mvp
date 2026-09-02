"""Software-device bootstrap and merchant pairing for the desktop simulator.

This is intentionally a separate, opt-in development trust path.  It models
the public-key proof that a production STM32 + secure element will perform,
without allowing a simulator-generated key to masquerade as hardware in a
production deployment.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from ..db import UnitOfWork
from ..protocol import SimulatorBootstrapRequest, SimulatorProvisionRequest, SimulatorSessionStatusRequest, utc_now
from ..repositories import IdentityRepository, SimulatorPairingRepository, TerminalRepository
from ..security import hash_token
from .errors import ServiceError
from .presenters import iso


_PAIRING_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"


class SimulatorPairingService:
    def __init__(self, uow: UnitOfWork, *, settings: Any, device_identity: Any) -> None:
        self.uow = uow
        self.settings = settings
        self.device_identity = device_identity

    def _enabled(self) -> None:
        if not self.settings.simulator_bootstrap_enabled:
            raise ServiceError(404, "simulator bootstrap is disabled")

    @staticmethod
    def _message(*, serial_number: str, nonce: str, purpose: str) -> bytes:
        return f"coffee-simulator-pairing:v1:{purpose}:{serial_number}:{nonce}".encode("utf-8")

    @staticmethod
    def _decode_signature(value: str) -> bytes:
        try:
            return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        except (ValueError, TypeError) as exc:
            raise ServiceError(422, "invalid simulator identity proof") from exc

    @classmethod
    def _public_key(cls, pem: str) -> tuple[ec.EllipticCurvePublicKey, str, str]:
        try:
            key = serialization.load_pem_public_key(pem.encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise ServiceError(422, "invalid simulator public key") from exc
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ServiceError(422, "simulator public key must use ECDSA P-256")
        normalized = key.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode("ascii")
        return key, normalized, hashlib.sha256(normalized.encode("ascii")).hexdigest()

    @classmethod
    def _verify(cls, key: ec.EllipticCurvePublicKey, *, serial_number: str, nonce: str, proof: str, purpose: str) -> None:
        try:
            key.verify(
                cls._decode_signature(proof),
                cls._message(serial_number=serial_number, nonce=nonce, purpose=purpose),
                ec.ECDSA(hashes.SHA256()),
            )
        except InvalidSignature as exc:
            raise ServiceError(401, "simulator identity proof is invalid") from exc

    @staticmethod
    def _pairing_code() -> str:
        value = "".join(secrets.choice(_PAIRING_ALPHABET) for _ in range(8))
        return f"{value[:4]}-{value[4:]}"

    @staticmethod
    def _new_device_id(repository: SimulatorPairingRepository) -> str:
        # Cloud-generated, globally scoped and intentionally unrelated to a
        # merchant's display numbering such as “1 号机”.
        for _ in range(32):
            candidate = f"coffee-bot-{secrets.randbelow(1_000_000):06d}"
            if repository.device_id_available(candidate):
                return candidate
        raise ServiceError(503, "unable to allocate device identity")

    def create_session(self, payload: SimulatorBootstrapRequest) -> dict[str, Any]:
        self._enabled()
        key, public_pem, fingerprint = self._public_key(payload.publicKeyPem)
        self._verify(
            key, serial_number=payload.serialNumber, nonce=payload.nonce,
            proof=payload.proof, purpose="bootstrap",
        )
        now = utc_now()
        expires_at = now + timedelta(seconds=self.settings.simulator_pairing_ttl_seconds)
        pairing_code = self._pairing_code()
        session_id = uuid.uuid4()
        with self.uow.transaction() as connection:
            terminals = TerminalRepository(connection)
            pairing = SimulatorPairingRepository(connection)
            terminal = terminals.find(payload.serialNumber, for_update=True)
            if terminal is None:
                terminal = pairing.create_terminal(self._new_device_id(pairing), payload.serialNumber)
            elif terminal.get("device_identity_kind") not in {None, "SIMULATOR_SOFTWARE"}:
                raise ServiceError(409, "device serial number belongs to another identity type")

            # Simulator-created terminals begin as platform inventory, just
            # like factory-imported devices.  Creating the initial ownership
            # revision keeps the later merchant transfer history continuous.
            pairing.ensure_initial_ownership(terminal["id"])
            identity = pairing.identity(terminal["id"])
            if identity and identity["public_key_fingerprint"].strip() != fingerprint:
                raise ServiceError(409, "simulator public key does not match the registered device")
            if identity is None:
                pairing.create_identity(terminal["id"], public_pem, fingerprint, now)
            else:
                pairing.verify_identity(terminal["id"], now)
            pairing.cancel_pending(terminal["id"])
            pairing.mark_pairing_pending(terminal["id"], now)
            pairing.create_session(session_id, terminal["id"], hash_token(pairing_code), expires_at)
        return {
            "sessionId": str(session_id), "deviceId": terminal["device_id"],
            "serialNumber": terminal["serial_number"], "pairingCode": pairing_code,
            "expiresAt": iso(expires_at), "status": "PENDING",
            "identityKind": "SIMULATOR_SOFTWARE", "publicKeyFingerprint": fingerprint,
        }

    def _verified_session(
        self, connection: Any, session_id: uuid.UUID, *, serial_number: str, nonce: str, proof: str,
        purpose: str, for_update: bool = False,
    ) -> dict[str, Any]:
        row = SimulatorPairingRepository(connection).session(session_id, serial_number, for_update=for_update)
        if not row:
            raise ServiceError(404, "pairing session not found")
        key, _, fingerprint = self._public_key(row["public_key_pem"])
        if fingerprint != row["public_key_fingerprint"].strip():
            raise ServiceError(409, "registered simulator identity is corrupted")
        self._verify(key, serial_number=serial_number, nonce=nonce, proof=proof, purpose=purpose)
        return row

    def session_status(self, session_id: uuid.UUID, payload: SimulatorSessionStatusRequest) -> dict[str, Any]:
        self._enabled()
        with self.uow.transaction() as connection:
            row = self._verified_session(
                connection, session_id, serial_number=payload.serialNumber, nonce=payload.nonce,
                proof=payload.proof, purpose="status",
            )
            status = row["status"]
            if status == "PENDING" and row["expires_at"] <= utc_now():
                SimulatorPairingRepository(connection).expire(session_id)
                status = "EXPIRED"
        return {
            "sessionId": str(session_id), "deviceId": row["device_id"], "serialNumber": row["serial_number"],
            "status": status, "expiresAt": iso(row["expires_at"]),
            "provisioningStatus": row.get("provisioning_status"),
        }

    def provision(self, session_id: uuid.UUID, payload: SimulatorProvisionRequest) -> dict[str, Any]:
        self._enabled()
        token_hash = hash_token(payload.deviceToken)
        now = utc_now()
        with self.uow.transaction() as connection:
            pairing = SimulatorPairingRepository(connection)
            row = self._verified_session(
                connection, session_id, serial_number=payload.serialNumber, nonce=payload.nonce,
                proof=payload.proof, purpose="provision", for_update=True,
            )
            if row["status"] == "PENDING" and row["expires_at"] <= now:
                pairing.expire(session_id)
                raise ServiceError(409, "pairing code expired; create a new pairing session")
            if row["status"] not in {"CLAIMED", "PROVISIONED"}:
                raise ServiceError(409, "merchant pairing has not completed")
            identities = IdentityRepository(connection)
            credential = None
            if row["status"] == "PROVISIONED":
                credential = pairing.provisioned_credential(row.get("provisioned_credential_id"), row["terminal_id"])
                if credential is None or credential["token_hash"] != token_hash:
                    raise ServiceError(409, "pairing session has already been provisioned")
            else:
                credential = pairing.credential_for_token(row["terminal_id"], token_hash)
            if credential is None:
                if identities.token_exists(token_hash):
                    raise ServiceError(409, "device credential token is already registered")
                identities.grace_active_http_credentials(
                    row["terminal_id"], now + timedelta(seconds=self.settings.credential_grace_seconds)
                )
                credential = identities.create_http_credential(
                    terminal_id=row["terminal_id"], token_hash=token_hash,
                    version=identities.next_http_version(row["terminal_id"]), now=now,
                )
            identities.activate_terminal(row["terminal_id"], now)
            terminal = pairing.mark_provisioned(row["terminal_id"], session_id, credential["id"], now)
        return {
            "sessionId": str(session_id), "deviceId": terminal["device_id"],
            **self.device_identity.credential_payload(credential),
            "publicKeyFingerprint": row["public_key_fingerprint"].strip(),
            "profile": {
                "deviceName": terminal.get("device_name"),
                "storeName": terminal.get("store_name"),
                "storeId": terminal.get("store_id"),
            },
            "mqttCredential": self.device_identity.issue_mqtt_credential(terminal),
        }
