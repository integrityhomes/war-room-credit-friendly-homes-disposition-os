"""Shared local checkpoint for UI and scheduled reads. No external writes."""
from dataclasses import replace
from datetime import UTC, datetime
from threading import Lock

from .corepilot_inventory import observe_inventory, stale_checkpoint
from .property_baseline import load_baseline_source
from .property_change_cache import cache_path, decode_result, encode_result, exclusive_check, read_cache, save_cache
from .property_change_detection import detect_property_changes
from .property_sync_preview import read_canonical_records, text

_lock = Lock()


def latest_property_check(secrets):
    return read_cache(cache_path(secrets))


def read_property_changes(secrets, *, force=False):
    from supabase import create_client

    path = cache_path(secrets)
    cached = read_cache(path)
    if not force and cached.get("result"):
        return decode_result(cached["result"])
    with _lock, exclusive_check(path):
        cached = read_cache(path)
        if not force and cached.get("result"):
            return decode_result(cached["result"])
        previous = decode_result(cached["result"]).state if cached.get("result") else None
        if previous and not previous.source_states:
            previous = replace(previous, source_states={pid: {"values": {"marketing_status": obs.get("marketing_status")}}
                                                       for pid, obs in cached.get("inventory_observations", {}).items()})
        attempted = datetime.now(UTC).isoformat()
        try:
            rows, source = load_baseline_source(secrets, include_marketing=True)
            client = create_client(text(secrets.get("SUPABASE_URL")), text(secrets.get("SUPABASE_SERVICE_ROLE_KEY")))
            properties = read_canonical_records(client, "properties")
            result = detect_property_changes(rows, properties, source_reference=source, previous=previous,
                                             lockbox_key=text(secrets.get("SUPABASE_SERVICE_ROLE_KEY")))
        except Exception:
            save_cache(path, {**cached, "version": 1, "last_attempt_at": attempted,
                              "error": "The complete property check failed. Last successful evidence was retained."})
            raise
        encoded = encode_result(result)
        archive = cached.get("change_evidence", {})
        for item in (*encoded["changes"], *encoded["observed_changes"]):
            archive.setdefault(item["event_id"], {"detected_at": result.checked_at, "evidence": item})
        observations = observe_inventory(rows, properties, cached.get("inventory_observations"), checked_at=result.checked_at, history=archive)
        stale = stale_checkpoint(properties, observations, cached.get("stale_inventory"))
        from .property_source_coverage import reconcile_coverage
        coverage = reconcile_coverage(rows.coverage, rows, properties) if hasattr(rows, "coverage") else {}
        from .corepilot_portfolio import portfolio
        portfolio_records = {"properties": properties}
        missing_sources = []
        if stale["attention"]:
            for entity in ("deals", "contacts", "communications", "tasks", "activities"):
                try:
                    portfolio_records[entity] = read_canonical_records(client, entity)
                except Exception:
                    missing_sources.append(entity)
        stale["disposition_plans"] = portfolio(portfolio_records, observations, history=result.changes)
        stale["unavailable_diagnosis_sources"] = missing_sources
        save_cache(path, {**cached, "version": 1, "last_attempt_at": attempted, "error": "", "result": encoded,
                          "change_evidence": archive, "inventory_observations": observations, "stale_inventory": stale,
                          "source_coverage": coverage})
        return result
