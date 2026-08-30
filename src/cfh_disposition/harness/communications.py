from __future__ import annotations

from typing import Any

from .fixtures import FIXTURE_SOURCE


def prepare_follow_up(fixture: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Turn the canonical inbound fixture message into internal follow-up artifacts."""
    deal = fixture["deal"]
    contact = fixture["contact"]
    inbound = fixture["communication"]
    if inbound.get("direction") != "inbound":
        raise ValueError("Harness follow-up requires an inbound communication.")
    if inbound.get("deal_id") != deal.get("id"):
        raise ValueError("Inbound communication must belong to the fixture Deal.")

    task = {
        **fixture["task"],
        "title": "Reply to fixture seller about property availability",
        "status": "open",
        "internal_only": True,
        "external_action_started": False,
        "fixture_source": FIXTURE_SOURCE,
    }
    reply = {
        "id": "FIXTURE-REPLY-HARRIS-0001",
        "deal_id": deal["id"],
        "contact_id": contact["id"],
        "channel": inbound["channel"],
        "direction": "outbound_draft",
        "to": contact["phone"] if inbound["channel"] == "sms" else contact["email"],
        "body": "Thanks for the update. We are reviewing the property and will follow up shortly.",
        "internal_only": True,
        "external_action_started": False,
        "fixture_source": FIXTURE_SOURCE,
    }
    return {"task": task, "reply_draft": reply}
