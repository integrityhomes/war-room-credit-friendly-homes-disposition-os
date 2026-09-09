"""Local detector checkpoint/evidence, never canonical property storage."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .property_change_detection import DetectionResult, DetectionState, PropertyChange, digest
from .property_sync_preview import FieldChange, PreviewItem

RUNTIME_ROOT = Path(__file__).resolve().parents[2] / ".commandcore-runtime" / "property-changes"


def cache_path(secrets) -> Path:
    sheet = str(secrets.get("GOOGLE_SHEET_ID", "")).strip()
    crm = str(secrets.get("SUPABASE_URL", "")).strip()
    if not sheet or not crm:
        raise ValueError("Source configuration is incomplete")
    return RUNTIME_ROOT / (digest([sheet, crm]) + ".json")


def encode_result(result):
    payload = asdict(result)
    payload["state"] = result.state.checkpoint()
    return payload


def decode_result(payload):
    def event(value):
        evidence = dict(value["evidence"])
        evidence["changes"] = tuple(FieldChange(**item) for item in evidence["changes"])
        for field in ("categories", "linked_deals", "review_reasons"):
            evidence[field] = tuple(evidence[field])
        return PropertyChange(value["event_id"], tuple(value["categories"]), PreviewItem(**evidence))
    return DetectionResult(tuple(event(item) for item in payload["changes"]), tuple(event(item) for item in payload["new_events"]),
                           DetectionState.from_checkpoint(payload["state"]), payload["checked_at"], payload["review_rows"], payload["unchanged"])


def read_cache(path):
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("version") != 1:
        raise ValueError("Unsupported property checkpoint")
    if value.get("result"):
        decode_result(value["result"])
    return value


def save_cache(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@contextmanager
def exclusive_check(path):
    """One worker per source across processes; OS releases crashed locks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
