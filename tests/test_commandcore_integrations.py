from cfh_disposition.commandcore_integrations import (
    build_integration_connections,
    integration_summary,
    safe_credential_reference,
    sanitize_operational_text,
)
from cfh_disposition.go_live_connections import build_connection_status


def connection(key: str, *, configured: bool = False, registry: dict | None = None):
    values = {"EMAIL_SENDER_WEBHOOK_URL": "https://example.com/email"} if configured else {}
    rows = [row for row in build_connection_status(values) if row.key == key]
    records = [registry] if registry else []
    return build_integration_connections(rows, records)[0]


def test_configuration_presence_is_not_reported_as_connected() -> None:
    item = connection("email_sender", configured=True)

    assert item.connection_state == "Configured"
    assert not item.live_execution_authorized


def test_registry_states_map_to_plain_english() -> None:
    expected = {
        "connected": "Connected",
        "degraded": "Degraded",
        "revoked": "Revoked",
        "pending": "Configured",
        "disconnected": "Setup Missing",
    }
    for stored, label in expected.items():
        item = connection("email_sender", registry={"channel_key": "email_sender", "connection_state": stored})
        assert item.connection_state == label


def test_live_execution_requires_connected_production_and_explicit_permission() -> None:
    base = {
        "channel_key": "email_sender",
        "connection_state": "connected",
        "execution_permitted": True,
    }

    assert not connection("email_sender", registry={**base, "test_mode": True}).live_execution_authorized
    assert not connection("email_sender", registry={**base, "environment": "production", "execution_permitted": False}).live_execution_authorized
    assert connection("email_sender", registry={**base, "environment": "production"}).live_execution_authorized


def test_operational_metadata_is_preserved_without_secret_values() -> None:
    item = connection(
        "email_sender",
        registry={
            "channel_key": "email_sender",
            "connection_state": "degraded",
            "provider": "Example Mail",
            "account_label": "Operations",
            "credential_reference": "Managed email credential",
            "last_successful_sync": "2026-09-03T12:00:00Z",
            "last_safe_test": "2026-09-03T13:00:00Z",
            "last_error": "Provider timed out",
            "retry_state": "Waiting for retry",
            "webhook_health": "Delayed",
            "recent_event": "Delivery status received",
        },
    )

    assert item.provider_account == "Example Mail — Operations"
    assert item.credential_reference == "Managed email credential"
    assert item.last_error == "Provider timed out"
    assert item.retry_state == "Waiting for retry"
    assert item.webhook_health == "Delayed"


def test_secret_like_metadata_is_redacted() -> None:
    secrets = (
        "access_token=do-not-display",
        "API key: do-not-display",
        "Bearer do-not-display",
        "https://hooks.example.com/private/value",
        "sk-proj-1234567890abcdef",
        "abcdefghijklmnopqrstuvwxyz123456",
    )
    for secret in secrets:
        assert "do-not-display" not in sanitize_operational_text(secret)
        assert "do-not-display" not in safe_credential_reference(secret)
    assert safe_credential_reference("abc123") == "Stored securely"


def test_summary_keeps_connection_and_authorization_separate() -> None:
    rows = build_integration_connections(
        build_connection_status({}),
        [
            {
                "channel_key": "email_sender",
                "connection_state": "connected",
                "environment": "production",
                "execution_permitted": False,
            }
        ],
    )
    summary = integration_summary(rows)

    assert summary["connected"] == 1
    assert summary["live_authorized"] == 0
