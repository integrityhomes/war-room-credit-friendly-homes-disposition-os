from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any

MAX_FOLLOWUP_NOTE_LENGTH = 240


def _text(value: Any) -> str:
    return str(value or "").strip()


def build_followup_record(
    *,
    deal_id: str,
    note: str,
    due: date | datetime,
    assigned_to: str = "",
    priority: str = "medium",
) -> dict[str, Any]:
    """Build the shared internal CRM task used by Deal and Pipeline follow-up forms."""
    normalized_deal_id = _text(deal_id)
    normalized_note = _text(note)
    if not normalized_deal_id:
        raise ValueError("A Deal is required before scheduling a follow-up.")
    if not normalized_note:
        raise ValueError("Enter a short follow-up note before saving.")
    if len(normalized_note) > MAX_FOLLOWUP_NOTE_LENGTH:
        raise ValueError(f"Keep the follow-up note to {MAX_FOLLOWUP_NOTE_LENGTH} characters or fewer.")

    due_field = "due_at" if isinstance(due, datetime) else "due_date"
    due_value = due.isoformat(timespec="minutes") if isinstance(due, datetime) else due.isoformat()
    normalized_owner = _text(assigned_to)
    fingerprint = hashlib.sha256(
        f"{normalized_deal_id}|{due_value}|{normalized_owner.casefold()}|{normalized_note.casefold()}".encode()
    ).hexdigest()[:24]

    return {
        "external_id": f"deal-follow-up-{fingerprint}",
        "title": normalized_note,
        "status": "open",
        "priority": _text(priority).casefold() or "medium",
        due_field: due_value,
        "assigned_to": normalized_owner or None,
        "task_type": "crm_follow_up",
        "links": {"deal_id": normalized_deal_id},
        "source": "commandcore-follow-up",
        "internal_only": True,
        "external_action_started": False,
    }
