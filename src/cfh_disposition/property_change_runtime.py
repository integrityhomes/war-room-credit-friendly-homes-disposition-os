"""Shared local checkpoint for UI and scheduled reads. No external writes."""
from datetime import UTC, datetime
from threading import Lock

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
        attempted = datetime.now(UTC).isoformat()
        try:
            rows, source = load_baseline_source(secrets)
            client = create_client(text(secrets.get("SUPABASE_URL")), text(secrets.get("SUPABASE_SERVICE_ROLE_KEY")))
            properties = read_canonical_records(client, "properties")
            result = detect_property_changes(rows, properties, source_reference=source, previous=previous)
        except Exception:
            save_cache(path, {**cached, "version": 1, "last_attempt_at": attempted,
                              "error": "The complete property check failed. Last successful evidence was retained."})
            raise
        save_cache(path, {"version": 1, "last_attempt_at": attempted, "error": "", "result": encode_result(result)})
        return result
