"""Shared CommandCore CRM client with automatic local demo fallback.

When Supabase credentials are missing, or ``COMMANDCORE_DEMO_MODE=1``, pages use
an in-memory demo backend seeded with fictional DEMO records. Production
behavior is unchanged when Supabase is configured and demo mode is not forced.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from cfh_disposition.app_secrets import get_secrets
from cfh_disposition.commandcore_crm_demo import DemoCrmBackend, DemoSupabaseShim
from cfh_disposition.commandcore_demo_data import (
    DEMO_BANNER,
    DEMO_CONNECT_NEXT_STEP,
    build_demo_crm_seed,
)

_DEMO_BACKEND: DemoCrmBackend | None = None
_DEMO_CLIENT: DemoSupabaseShim | None = None
_LIVE_CLIENT: Any | None = None


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def supabase_credentials(secrets: Mapping[str, Any] | None = None) -> tuple[str, str]:
    values = secrets if secrets is not None else get_secrets()
    url = str(values.get("SUPABASE_URL", "") or "").strip()
    key = str(
        values.get("SUPABASE_SECRET_KEY", "")
        or values.get("SUPABASE_SERVICE_ROLE_KEY", "")
        or ""
    ).strip()
    return url, key


def demo_mode_forced(secrets: Mapping[str, Any] | None = None) -> bool:
    values = secrets if secrets is not None else get_secrets()
    if _truthy(os.environ.get("COMMANDCORE_DEMO_MODE")):
        return True
    return _truthy(values.get("COMMANDCORE_DEMO_MODE"))


def is_demo_mode(secrets: Mapping[str, Any] | None = None) -> bool:
    if demo_mode_forced(secrets):
        return True
    url, key = supabase_credentials(secrets)
    return not (url and key)


def get_demo_backend(*, reset: bool = False) -> DemoCrmBackend:
    global _DEMO_BACKEND, _DEMO_CLIENT
    if reset or _DEMO_BACKEND is None:
        _DEMO_BACKEND = DemoCrmBackend(build_demo_crm_seed())
        _DEMO_CLIENT = DemoSupabaseShim(_DEMO_BACKEND)
    return _DEMO_BACKEND


def get_crm_client(secrets: Mapping[str, Any] | None = None) -> Any:
    """Return a Supabase-like client, or the demo shim when credentials are absent."""
    global _LIVE_CLIENT, _DEMO_CLIENT
    values = secrets if secrets is not None else get_secrets()
    if is_demo_mode(values):
        get_demo_backend()
        assert _DEMO_CLIENT is not None
        return _DEMO_CLIENT

    url, key = supabase_credentials(values)
    if _LIVE_CLIENT is None:
        from supabase import create_client

        _LIVE_CLIENT = create_client(url, key)
    return _LIVE_CLIENT


def call_crm(payload: dict[str, Any], *, secrets: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Invoke the CRM core action surface (live edge function or demo backend)."""
    if is_demo_mode(secrets):
        return get_demo_backend().handle(payload)

    client = get_crm_client(secrets)
    response = client.functions.invoke("commandcore-crm-core", {"body": payload})
    if isinstance(response, dict):
        return response
    data = getattr(response, "data", None)
    return data if isinstance(data, dict) else {}


def list_crm_records(entity: str, *, limit: int = 500, secrets: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    result = call_crm({"action": "list", "entity": entity, "limit": limit}, secrets=secrets)
    records = result.get("records", [])
    return records if isinstance(records, list) else []


def upsert_crm_record(
    entity: str,
    record: dict[str, Any],
    *,
    secrets: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return call_crm({"action": "upsert", "entity": entity, "record": record}, secrets=secrets)


def get_crm_record(
    entity: str,
    record_id: str,
    *,
    secrets: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return call_crm({"action": "get", "entity": entity, "id": record_id}, secrets=secrets)


def render_demo_banner() -> bool:
    """Show the demo-mode banner when active. Returns True when demo mode is on."""
    if not is_demo_mode():
        return False
    import streamlit as st

    st.info(DEMO_BANNER)
    return True


def demo_connection_message() -> str:
    return DEMO_BANNER


def demo_connection_next_step() -> str:
    return DEMO_CONNECT_NEXT_STEP


def reset_crm_clients_for_tests() -> None:
    """Clear cached clients between tests."""
    global _DEMO_BACKEND, _DEMO_CLIENT, _LIVE_CLIENT
    _DEMO_BACKEND = None
    _DEMO_CLIENT = None
    _LIVE_CLIENT = None
