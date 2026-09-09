"""Shared process-memory detector checkpoint. No external writes or scheduler."""
from threading import Lock

from .property_baseline import load_baseline_source
from .property_change_detection import DetectionState, detect_property_changes
from .property_sync_preview import read_canonical_records, text

_lock = Lock()
_states: dict[str, DetectionState] = {}


def read_property_changes(secrets):
    from supabase import create_client

    # Serialize a full check so two browser sessions cannot both emit the same
    # new events. A failed read never advances the checkpoint.
    with _lock:
        rows, source = load_baseline_source(secrets)
        client = create_client(text(secrets.get("SUPABASE_URL")), text(secrets.get("SUPABASE_SERVICE_ROLE_KEY")))
        properties = read_canonical_records(client, "properties")
        scope = source + "|" + text(secrets.get("SUPABASE_URL"))
        result = detect_property_changes(rows, properties, source_reference=source, previous=_states.get(scope))
        _states[scope] = result.state
        return result
