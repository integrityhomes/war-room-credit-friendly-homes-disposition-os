from __future__ import annotations

import os

from cfh_disposition.commandcore_crm_client import (
    call_crm,
    is_demo_mode,
    reset_crm_clients_for_tests,
)
from cfh_disposition.commandcore_crm_demo import DemoCrmBackend
from cfh_disposition.commandcore_demo_data import DEMO_BANNER, build_demo_crm_seed
from cfh_disposition.storage import InMemoryStorage, SupabaseStorage, build_storage


def setup_function() -> None:
    reset_crm_clients_for_tests()
    os.environ.pop("COMMANDCORE_DEMO_MODE", None)
    os.environ.pop("SUPABASE_URL", None)
    os.environ.pop("SUPABASE_SECRET_KEY", None)
    os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)


def teardown_function() -> None:
    setup_function()


def test_demo_mode_when_supabase_missing() -> None:
    assert is_demo_mode({}) is True
    assert "Demo mode" in DEMO_BANNER


def test_demo_mode_forced_even_with_credentials() -> None:
    secrets = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SECRET_KEY": "sb_secret_test",
        "COMMANDCORE_DEMO_MODE": "1",
    }
    assert is_demo_mode(secrets) is True


def test_live_mode_when_supabase_configured() -> None:
    secrets = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SECRET_KEY": "sb_secret_test",
    }
    assert is_demo_mode(secrets) is False


def test_demo_backend_list_seed_and_upsert() -> None:
    backend = DemoCrmBackend(build_demo_crm_seed())
    listed = backend.handle({"action": "list", "entity": "deals", "limit": 50})
    assert listed["ok"] is True
    assert listed["count"] >= 1
    assert any("DEMO" in str(row.get("title", "")) for row in listed["records"])

    created = backend.handle(
        {
            "action": "upsert",
            "entity": "contacts",
            "record": {"name": "DEMO New Contact", "demo": True},
        }
    )
    assert created["ok"] is True
    assert created["created"] is True
    contact_id = created["record"]["id"]
    fetched = backend.handle({"action": "get", "entity": "contacts", "id": contact_id})
    assert fetched["ok"] is True
    assert fetched["record"]["name"] == "DEMO New Contact"


def test_call_crm_uses_demo_backend_without_secrets() -> None:
    reset_crm_clients_for_tests()
    result = call_crm({"action": "list", "entity": "properties", "limit": 10}, secrets={})
    assert result["ok"] is True
    assert result["count"] >= 1
    assert any("DEMO" in str(row.get("address", "")) for row in result["records"])


def test_build_storage_demo_forced_skips_supabase() -> None:
    storage = build_storage(
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SECRET_KEY": "sb_secret_test",
            "COMMANDCORE_DEMO_MODE": "1",
        }
    )
    assert isinstance(storage, InMemoryStorage)
    assert storage.mode == "Demo memory"


def test_build_storage_uses_supabase_when_configured() -> None:
    storage = build_storage(
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SECRET_KEY": "sb_secret_test",
        }
    )
    assert isinstance(storage, SupabaseStorage)
