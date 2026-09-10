"""Read-only inventory aging and evidence-led advice for the existing Command Bot."""

from datetime import UTC, date, datetime

from .property_change_detection import digest
from .property_sync_preview import FIELD_ALIASES, REVIEW, TERM_FIELDS, comparable, compare_properties, first

STALE_THRESHOLDS = (10, 14, 21)
PRICE_TERMS = TERM_FIELDS | {"asking_or_sale_price"}


def day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def inventory_question(query):
    q = query.casefold().replace("’", "'")
    return any(
        t in q
        for t in (
            "stale",
            "for sale more than",
            "isn't this property selling",
            "is not this property selling",
            "sell this one",
            "need a price change",
            "need better terms",
            "make this property move",
            "oldest active",
            "no meaningful change",
        )
    )


def observe_inventory(rows, properties, previous=None, *, checked_at=None, history=None):
    """Reuse validated matching; save only IDs, hashes and observation dates locally."""
    checked_at = checked_at or datetime.now(UTC).isoformat()
    prior = previous or {}
    canonical_status = {p.get("id"): comparable("availability", first(p, FIELD_ALIASES["availability"])) for p in properties}
    observations = {}
    for prop in properties:
        pid = prop.get("id")
        if pid and (pid in prior or prop.get("source") == "cfh-google-sheet"):
            observations[pid] = {**prior.get(pid, {}), "status": "Needs review", "checked_at": checked_at, "marketing_status": "unknown", "marketing_observed_since": ""}
    preview = compare_properties(rows, properties)
    for row, item in zip(rows, preview.items, strict=False):
        if item.property_id and item.property_id not in observations:
            observations[item.property_id] = {"status": "Needs review", "checked_at": checked_at, "marketing_status": "unknown", "marketing_observed_since": ""}
        if not item.property_id or REVIEW in item.categories:
            continue
        old = prior.get(item.property_id, {})
        status = comparable("availability", row.fields.get("availability"))
        values = {key: comparable(key, row.fields.get(key)) for key in PRICE_TERMS}
        fingerprint = digest(values)
        marketed = status == "available" and row.marketing_status == "yellow"
        continuous = old.get("status") == "available" and old.get("marketing_status") == "yellow"
        marketing_since = old.get("marketing_observed_since", "") if continuous else ""
        observations[item.property_id] = {
            "status": status,
            "checked_at": checked_at,
            "marketing_status": row.marketing_status,
            "marketing_observed_since": (marketing_since or checked_at) if marketed else "",
            "marketing_restarted": old.get("marketing_restarted", False) or bool(marketed and old.get("marketing_status") and not continuous),
            "price_terms_hash": fingerprint,
            "last_change_observed_at": checked_at if old.get("price_terms_hash") and old["price_terms_hash"] != fingerprint else old.get("last_change_observed_at", ""),
            "unchanged_observed_since": old.get("unchanged_observed_since", checked_at) if old.get("price_terms_hash") == fingerprint else checked_at,
            "restarted": old.get("restarted", False)
            or bool(old and old.get("status") != "available" and status == "available")
            or (status == "available" and canonical_status.get(item.property_id) != "available"),
        }
    for entry in (history or {}).values():
        evidence = entry.get("evidence", {}).get("evidence", {})
        pid = evidence.get("property_id")
        timestamp = entry.get("detected_at", "")
        if pid in observations and day(timestamp) and any(c.get("field") in PRICE_TERMS and c.get("proposed") not in (None, "") for c in evidence.get("changes", [])):
            current = observations[pid].get("last_change_observed_at", "")
            if not day(current) or day(timestamp) > day(current):
                observations[pid]["last_change_observed_at"] = timestamp
    return observations


def inventory_items(properties, observations=None, *, today=None, thresholds=STALE_THRESHOLDS):
    today = today or datetime.now(UTC).date()
    observations = observations or {}
    items = []
    for prop in properties:
        pid = prop.get("id")
        if not pid or prop.get("archived"):
            continue
        observed = observations.get(pid, {})
        status = observed.get("status", comparable("availability", first(prop, FIELD_ALIASES["availability"])))
        if status != "available":
            continue
        # Availability is not marketing. Legacy observation dates cannot age yellow periods.
        marketing = observed.get("marketing_status", "unknown")
        dates = [day(prop.get(k)) for k in ("marketing_started_at", "listed_at", "first_listed_date") if prop.get(k)]
        start = max(dates) if dates and all(dates) and marketing == "yellow" else None
        basis = "Actively marketed" if start else "Marketing age cannot yet be verified"
        if observed.get("restarted") or observed.get("marketing_restarted"):
            start = None
        if marketing == "yellow" and not start and observed.get("marketing_observed_since"):
            start = day(observed["marketing_observed_since"])
            basis = "CommandCore has tracked this property as marketed"
        if start and start > today:
            start = None
        if marketing == "white":
            basis = "Not ready to market"
        elif not start:
            basis = "Marketing age cannot yet be verified"
        age = (today - start).days if start else None
        changed = day(observed.get("last_change_observed_at") or prop.get("last_price_terms_change_at"))
        unchanged = day(observed.get("unchanged_observed_since"))
        priority = next(
            (label for cutoff, label in reversed(tuple(zip(thresholds, ("Needs attention", "Higher priority", "Urgent disposition review"), strict=True))) if age is not None and age >= cutoff), ""
        )
        items.append(
            {
                "property_id": pid,
                "address": prop.get("address") or prop.get("property_address") or "Recorded property",
                "days_active": age,
                "active_since": start.isoformat() if start else "Unknown",
                "age_basis": basis,
                "status": status,
                "marketing_status": marketing,
                "priority": priority,
                "last_change": changed.isoformat() if changed and changed <= today else "Unknown",
                "days_since_change": (today - changed).days if changed and changed <= today else None,
                "unchanged_observed_days": (today - unchanged).days if unchanged and unchanged <= today else None,
                "attention_id": digest([pid, start.isoformat() if start else "", priority]) if priority else "",
            }
        )
    return sorted(items, key=lambda i: (-(i["days_active"] if i["days_active"] is not None else -1), i["property_id"]))


def stale_checkpoint(properties, observations, previous=None, *, today=None):
    items = inventory_items(properties, observations, today=today)
    attention = [item for item in items if item["priority"]]
    seen = set((previous or {}).get("seen_ids", []))
    ids = {item["attention_id"] for item in attention}
    return {
        "attention": attention,
        "seen_ids": sorted(seen | ids),
        "new_ids": sorted(ids - seen),
        "unknown_age_count": sum(i["days_active"] is None and i["marketing_status"] != "white" for i in items),
    }


def advise_property(prop, records, item):
    """Rank supported hypotheses, never infer price targets from aging alone."""
    pid = prop.get("id")
    deals = {d.get("id") for d in records.get("deals", ()) if (d.get("links") or {}).get("property_id", d.get("property_id")) == pid}

    def linked(record):
        links = record.get("links") or {}
        return links.get("property_id", record.get("property_id")) == pid or bool(deals and links.get("deal_id", record.get("deal_id")) in deals)

    messages = [m for m in records.get("communications", ()) if linked(m)]
    buyers = {c.get("id") for c in records.get("contacts", ()) if str(c.get("relationship") or c.get("contact_type") or c.get("lead_type") or "").casefold() == "buyer"}
    inquiries = [m for m in messages if (m.get("links") or {}).get("contact_id", m.get("contact_id")) in buyers and m.get("direction") == "inbound"]
    marketing = [a for a in records.get("activities", ()) if linked(a) and str(a.get("activity_type", "")).casefold() in {"marketing", "listing", "campaign"}]
    tasks = [t for t in records.get("tasks", ()) if linked(t) and str(t.get("status", "")).casefold() not in {"done", "completed", "closed", "cancelled", "canceled"}]
    facts = [
        f"VERIFIED FACT: Source classification: {item['status']} (not proof of closing or unsold transaction history).",
        f"{item['age_basis']}" + (f" for {item['days_active']} days · Marketing since: {item['active_since']}" if item["days_active"] is not None else ""),
        f"Last price/terms change observed or explicitly recorded: {item['last_change']} · Days since: {item['days_since_change'] if item['days_since_change'] is not None else 'Unknown'}",
    ]
    for field in ("asking_or_sale_price", "down_payment", "monthly_payment", "interest_rate", "monthly_taxes", "monthly_insurance", "bedrooms", "bathrooms", "square_feet"):
        value = first(prop, FIELD_ALIASES[field])
        facts.append(f"Recorded {field.replace('_', ' ')}: {value if value not in (None, '') else 'Missing'}")
    facts += [f"Linked buyer inquiries: {len(inquiries)} recorded; coverage may be incomplete.", f"Linked marketing activities: {len(marketing)} recorded; reach/conversion not established."]
    missing = []
    if not inquiries:
        missing.append("Buyer-response evidence is missing; zero recorded inquiries does not prove zero interest.")
    if not marketing:
        missing.append("Marketing exposure/activity evidence is missing.")
    if not prop.get("photo_urls") and not prop.get("photo_link"):
        missing.append("Photos are missing from these records; photo quality cannot be judged.")
    missing += ["Verified comparable-market evidence is unavailable to this advisor.", "Verified condition/inspection evidence is unavailable to this advisor."]
    tasks = [t for t in tasks if str(t.get("status", "")).casefold() == "blocked" or t.get("blocked_reason") or t.get("blocker")]
    findings = []
    for m in inquiries:
        body = str(m.get("message_text") or m.get("body") or m.get("message") or m.get("summary") or "")
        lower = body.casefold()
        for phrase, category, action in (
            ("price is too high", "price", "Review the buyer's price objection and obtain verified comparables before proposing a price."),
            ("down payment is too high", "terms", "Review the down-payment concern before proposing any terms."),
            ("monthly payment is too high", "terms", "Review the monthly-payment concern before proposing any terms."),
        ):
            if lower.strip(" .!?") in {phrase, "the " + phrase}:
                findings.append(
                    (
                        3,
                        3,
                        2,
                        category,
                        f"LIKELY CAUSE: A recorded buyer objection may indicate {category} friction; this is not a market valuation.",
                        action,
                        f"communications:{m.get('id')} · Recorded buyer message: {body}",
                    )
                )
    if tasks:
        findings.append(
            (
                2,
                2,
                1,
                "follow-up",
                "LIKELY CAUSE: Blocked linked work may delay disposition; the recorded blocker does not establish the entire sales cause.",
                "Review the existing linked tasks before creating more work.",
                "; ".join(f"tasks:{t.get('id')} · {t.get('title', '')}" for t in tasks),
            )
        )
    findings.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]))
    causes = tuple(dict.fromkeys(f[4] for f in findings)) or ("No likely cause can be established from the available evidence.",)
    recommendations = tuple(dict.fromkeys("RECOMMENDATION: " + f[5] for f in findings))
    recommendations += ("RECOMMENDATION: Gather missing buyer feedback, marketing reach, photos and verified market evidence before changing price or terms.",)
    return {
        "facts": tuple(facts),
        "missing": tuple(missing),
        "causes": causes,
        "recommendations": recommendations,
        "evidence": tuple(f[6] for f in findings),
        "categories": tuple(f[3] for f in findings),
    }


def answer_inventory(query, records, ctx, observations=None, *, today=None, property_changes=None):
    from .corepilot_orchestrator import CorePilotResult

    items = inventory_items(records.get("properties", ()), observations, today=today)
    q = query.casefold().replace("’", "'")
    by_id = {p.get("id"): p for p in records.get("properties", ())}
    specific = any(t in q for t in ("this property", "this one"))
    if specific:
        pid = ctx.get("property_id")
        if not pid:
            return CorePilotResult("needs_context", (), (), "Identify the property first.", clarification="Which property should I analyze?")
        item = next((i for i in items if i["property_id"] == pid), None)
        if not item:
            return CorePilotResult(
                "complete", ("This property is not verified as current active inventory in the available evidence.",), (), "Review its source classification; no sales action is proposed."
            )
        if item["marketing_status"] == "white":
            return CorePilotResult("complete", (item["address"], "Not ready to market — white source row; stale aging is stopped."), (),
                                   "Review pre-marketing readiness. This is not a sold classification and no record change is proposed.")
        advice = advise_property(by_id[pid], records, item)
        recent = tuple(f"Recorded source change: {c.evidence.changes}" for c in property_changes.changes if c.evidence.property_id == pid) if property_changes else ()
        return CorePilotResult(
            "complete", (item["address"], *advice["facts"], *recent), advice["missing"], "\n\n".join(advice["recommendations"]), evidence=advice["evidence"], inventory_causes=advice["causes"]
        )
    if "price change" in q or "better terms" in q:
        category = "price" if "price change" in q else "terms"
        chosen = [i for i in items if i["marketing_status"] == "yellow" and category in advise_property(by_id[i["property_id"]], records, i)["categories"]]
        return CorePilotResult(
            "complete",
            tuple(i["address"] for i in chosen) or ("No recorded buyer objection supports that specific change recommendation.",),
            ("Age alone does not establish that price or terms are wrong.",),
            "Review buyer evidence before proposing any numbers; no changes are applied.",
        )
    if "no meaningful change" in q:
        chosen = [
            i
            for i in items
            if i["marketing_status"] == "yellow"
            and ((i["days_since_change"] is not None and i["days_since_change"] >= 14) or (i["unchanged_observed_days"] is not None and i["unchanged_observed_days"] >= 14))
        ]
    elif "oldest" in q:
        chosen = [i for i in items if i["days_active"] is not None][:10]
    else:
        chosen = [i for i in items if i["priority"] and ("more than" not in q or i["days_active"] > 10)]
    found = tuple(f"{i['address']} · {i['age_basis']} for {i['days_active']} days · {i['priority'] or 'Below attention threshold'}" for i in chosen)
    unknown = sum(i["days_active"] is None and i["marketing_status"] != "white" for i in items)
    return CorePilotResult(
        "complete",
        found or ("No qualifying stale inventory is verified by the available dates.",),
        (f"{sum(i['marketing_status'] == 'white' for i in items)} properties: Not ready to market. {unknown} properties: Marketing age cannot yet be verified.",),
        "Select a property and ask why it isn't selling. Verify buyer and marketing evidence before changing price or terms.",
    )
