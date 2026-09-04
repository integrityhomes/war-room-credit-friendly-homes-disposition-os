from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .go_live_connections import ConnectionStatus

REGISTRY_STATES = {"disconnected", "pending", "connected", "degraded", "revoked"}
SECRET_WORDS = re.compile(
    r"(?i)(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|oauth[_ -]?secret|signing[_ -]?secret|webhook[_ -]?secret|bearer)"
)
SECRET_ASSIGNMENT = re.compile(r"(?i)\b[\w -]*(?:key|token|password|secret)\s*[:=]\s*\S+")
URL_VALUE = re.compile(r"https?://\S+", re.IGNORECASE)
SECRET_VALUE = re.compile(r"(?i)(?:\b(?:sk|ghp|xox[baprs]|sb)[-_][a-z0-9_-]{8,}|\beyJ[a-z0-9_-]{12,}|\b[a-z0-9_-]{32,}\b)")
REFERENCE_WORDS = re.compile(r"(?i)\b(?:credential|managed|reference|streamlit|vault|environment)\b")


@dataclass(frozen=True, slots=True)
class IntegrationConnection:
    key: str
    name: str
    provider_account: str
    connection_state: str
    credential_reference: str
    environment: str
    last_successful_sync: str
    last_safe_test: str
    last_error: str
    retry_state: str
    webhook_health: str
    recent_event: str
    live_execution_authorized: bool
    next_step: str


def text(value: Any) -> str:
    return str(value or "").strip()


def sanitize_operational_text(value: Any, *, fallback: str = "Not recorded") -> str:
    raw = text(value)
    if not raw:
        return fallback
    if SECRET_VALUE.search(raw):
        return "Sensitive details removed"
    redacted = SECRET_ASSIGNMENT.sub("Sensitive value removed", raw)
    redacted = URL_VALUE.sub("External address removed", redacted)
    if SECRET_WORDS.search(redacted):
        return "Sensitive details removed"
    return redacted[:240]


def safe_credential_reference(value: Any) -> str:
    raw = text(value)
    if not raw:
        return "Not recorded"
    if (
        SECRET_WORDS.search(raw)
        or SECRET_VALUE.search(raw)
        or URL_VALUE.search(raw)
        or "=" in raw
        or len(raw) > 120
        or not REFERENCE_WORDS.search(raw)
    ):
        return "Stored securely"
    return raw


def _registry_by_key(records: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {
        text(record.get("channel_key")): record
        for record in records
        if text(record.get("channel_key"))
    }


def _state(configured: bool, registry: Mapping[str, Any]) -> str:
    state = text(registry.get("connection_state")).casefold()
    if state == "connected":
        return "Connected"
    if state == "degraded":
        return "Degraded"
    if state == "revoked":
        return "Revoked"
    if configured or state == "pending":
        return "Configured"
    return "Setup Missing"


def _environment(registry: Mapping[str, Any]) -> str:
    environment = text(registry.get("environment")).casefold()
    if registry.get("test_mode") is True or environment in {"test", "testing", "sandbox"}:
        return "Test Mode"
    if environment in {"production", "live"}:
        return "Production"
    return "Not recorded"


def _provider_account(row: ConnectionStatus, registry: Mapping[str, Any]) -> str:
    provider = sanitize_operational_text(registry.get("provider"), fallback="")
    account = sanitize_operational_text(registry.get("account_label"), fallback="")
    combined = " — ".join(part for part in (provider, account) if part)
    return combined or row.name


def build_integration_connections(
    configuration_rows: Iterable[ConnectionStatus],
    registry_records: Iterable[Mapping[str, Any]] = (),
) -> tuple[IntegrationConnection, ...]:
    registry_by_key = _registry_by_key(registry_records)
    connections: list[IntegrationConnection] = []
    for row in configuration_rows:
        registry = registry_by_key.get(row.key, {})
        state = _state(row.configured, registry)
        environment = _environment(registry)
        execution_authorized = (
            state == "Connected"
            and environment == "Production"
            and registry.get("execution_permitted") is True
        )
        connections.append(
            IntegrationConnection(
                key=row.key,
                name=row.name,
                provider_account=_provider_account(row, registry),
                connection_state=state,
                credential_reference=safe_credential_reference(registry.get("credential_reference")),
                environment=environment,
                last_successful_sync=sanitize_operational_text(registry.get("last_successful_sync")),
                last_safe_test=sanitize_operational_text(
                    registry.get("last_safe_test") or registry.get("last_verified_at")
                ),
                last_error=sanitize_operational_text(registry.get("last_error")),
                retry_state=sanitize_operational_text(registry.get("retry_state")),
                webhook_health=sanitize_operational_text(
                    registry.get("webhook_health") or registry.get("health_status")
                ),
                recent_event=sanitize_operational_text(
                    registry.get("recent_event") or registry.get("last_event_at")
                ),
                live_execution_authorized=execution_authorized,
                next_step=row.next_step,
            )
        )
    return tuple(connections)


def integration_summary(rows: Iterable[IntegrationConnection]) -> dict[str, int]:
    items = tuple(rows)
    return {
        "total": len(items),
        "connected": sum(row.connection_state == "Connected" for row in items),
        "needs_attention": sum(row.connection_state in {"Setup Missing", "Degraded", "Revoked"} for row in items),
        "live_authorized": sum(row.live_execution_authorized for row in items),
    }
