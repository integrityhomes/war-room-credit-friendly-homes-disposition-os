"""Read-only portfolio disposition plans over existing marketing observations."""

from decimal import Decimal, InvalidOperation

from .corepilot_inventory import advise_property, inventory_items
from .property_sync_preview import FIELD_ALIASES, first


def financial_options(prop):
    """Only calculate from recorded inputs; never choose a market value or target."""
    def number(field):
        value = first(prop, FIELD_ALIASES[field])
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError("Invalid recorded input")
        return result

    try:
        price, down = number("asking_or_sale_price"), number("down_payment")
        if down >= price:
            return ()
        principal = price - down
        options = [f"PROPOSED REVIEW — Keep recorded price ${price:,.2f} and down payment ${down:,.2f}: implied principal ${principal:,.2f}, before fees. No terms changed."]
        # A payment structure requires an explicit recorded amortization period.
        months = Decimal(str(prop.get("amortization_months")))
        rate = number("interest_rate") / 1200
        if months != int(months) or not 1 <= months <= 600:
            return tuple(options)
        payment = principal / months if rate == 0 else principal * rate / (1 - (1 + rate) ** -int(months))
        options.append(f"PROPOSED REVIEW — Using the recorded {int(months)}-month amortization and rate, calculated principal-and-interest is ${payment:,.2f}/month. "
                       "This assumes fixed-rate monthly amortization and excludes taxes, insurance, fees and balloon provisions; verify the contract before considering it.")
        return tuple(options)
    except (InvalidOperation, ValueError, TypeError, ZeroDivisionError, OverflowError):
        return tuple(locals().get("options", ()))


def diagnose(prop, records, item, history=()):
    advice = advise_property(prop, records, item)
    facts = list(advice["facts"])
    missing = list(advice["missing"])
    if "communications" not in records or "contacts" not in records:
        facts = [f for f in facts if not f.startswith("Linked buyer inquiries:")]
        missing.append("Buyer inquiry count unavailable: the complete communication/contact source was not read.")
    if "activities" not in records:
        facts = [f for f in facts if not f.startswith("Linked marketing activities:")]
        missing.append("Marketing activity source unavailable.")
    pid = prop["id"]
    deals = {r["id"] for r in records.get("deals", ()) if (r.get("links") or {}).get("property_id", r.get("property_id")) == pid}

    def linked(row):
        links = row.get("links") or {}
        return links.get("property_id", row.get("property_id")) == pid or bool(deals and links.get("deal_id", row.get("deal_id")) in deals)

    tasks = [r for r in records.get("tasks", ()) if linked(r) and not r.get("archived")]
    followups = [r for r in tasks if any(t in str(r.get("title", "")).casefold() for t in ("follow up", "follow-up", "contact buyer", "call buyer"))]
    completed = [r for r in followups if r.get("status") in {"done", "completed"}]
    open_followups = [r for r in followups if r.get("status") not in {"done", "completed", "closed", "cancelled", "canceled"}]
    blocked = [r for r in tasks if r.get("status") == "blocked" or r.get("blocked_reason") or r.get("blocker")]
    reasons = [f"MEDIUM evidence of possible sales friction — {r}" for r in advice["causes"] if not r.startswith("No likely cause")]
    plan = []
    if open_followups:
        reasons.append(f"HIGH evidence of unfinished work: {len(open_followups)} linked follow-up tasks remain open; this does not establish buyer disinterest.")
        plan.append(f"Review the {len(open_followups)} existing follow-up tasks today, confirm owners and consent, and prepare private buyer follow-ups; do not create duplicate work.")
    if blocked:
        plan.append(f"Resolve or investigate the {len(blocked)} recorded work blockers with their existing owners before changing the offer.")
    if "terms" in advice["categories"]:
        plan.append("Review the recorded buyer payment/down-payment objections, ask for an affordability target through an approved follow-up, and prepare terms scenarios for owner review.")
    if "price" in advice["categories"]:
        plan.append("Review the recorded price objections and obtain comparable evidence before preparing a specific price adjustment range.")
    plan.append("Review existing buyer inquiries and unlinked inbox messages today; prepare a consent-checked follow-up shortlist. Zero recorded inquiries is not proof of zero interest.")
    activities = [r for r in records.get("activities", ()) if linked(r) and not r.get("archived") and r.get("activity_type") in {"marketing", "listing", "campaign"}]
    channels = sorted({str(r["channel"]) for r in activities if r.get("channel")})
    if channels:
        plan.append("Review recorded channels (" + ", ".join(channels) + ") for current availability, accurate price/payment copy and buyer responses; prepare a listing refresh for review.")
    else:
        reasons.append("MISSING DATA — Channel exposure cannot be evaluated; missing activity is not proof that marketing is absent.")
        plan.append("Audit where the property is currently listed and collect views/inquiries; prepare a verified-facts listing refresh before proposing additional configured channels.")
    if prop.get("photo_urls") or prop.get("photo_link"):
        plan.append("Inspect the recorded photos for current condition and clarity; propose replacements only for identified shortcomings.")
    else:
        plan.append("Request current property photos for a private review; do not make condition claims without evidence.")
    plan.append("Recheck buyer responses and recorded follow-up outcomes after 72 hours; escalate an owner-reviewed price/terms proposal only if the new evidence supports it.")
    evidence = list(advice["evidence"])
    for event in history:
        if event.evidence.property_id == pid:
            evidence.append(f"Observed source event {event.event_id}: {event.evidence.changes}")
    return {"property_id": pid, "address": item["address"], "priority": item["priority"], "days": item["days_active"],
            "age_basis": item["age_basis"], "since": item["active_since"], "days_since_change": item["days_since_change"],
            "unchanged_observed_days": item["unchanged_observed_days"],
            "facts": (*facts, f"Completed follow-up tasks: {len(completed)} recorded; coverage may be incomplete." if "tasks" in records else "Completed follow-up count unavailable."),
            "reasons": tuple(reasons), "plan": tuple(plan), "missing": tuple(missing), "options": financial_options(prop),
            "evidence": tuple(evidence), "categories": advice["categories"], "blocked_count": len(blocked), "open_followups": len(open_followups)}


def portfolio(records, observations, *, today=None, history=()):
    props = {r["id"]: r for r in records.get("properties", ()) if r.get("id")}
    items = inventory_items(list(props.values()), observations, today=today)
    plans = [diagnose(props[i["property_id"]], records, i, history) for i in items if i["marketing_status"] == "yellow" and i["priority"]]
    # Transparent ordering: threshold, actionable evidence, age, unchanged duration.
    priority = {"Needs attention": 1, "Higher priority": 2, "Urgent disposition review": 3}
    return sorted(plans, key=lambda p: (-priority[p["priority"]], -p["blocked_count"], -p["open_followups"],
                                       -len(p["categories"]), -p["days"], -(p["days_since_change"] or 0), p["property_id"]))


def portfolio_answer(query, records, observations, *, today=None, history=()):
    from .corepilot_orchestrator import CorePilotResult

    plans = portfolio(records, observations, today=today, history=history)
    q = query.casefold()
    for phrase, threshold in (("hit 10 days", 10), ("at 14 days", 14), ("at 21 days", 21)):
        if phrase in q:
            plans = [p for p in plans if p["days"] >= threshold]
    if "price adjustment" in q or "need a price change" in q:
        plans = [p for p in plans if "price" in p["categories"]]
    elif "payment problems" in q or "need better terms" in q:
        plans = [p for p in plans if "terms" in p["categories"]]
    elif "more than 10" in q:
        plans = [p for p in plans if p["days"] > 10]
    elif "no meaningful change" in q:
        plans = [p for p in plans if (p["days_since_change"] or 0) >= 14 or (p["unchanged_observed_days"] or 0) >= 14]
    found, actions, evidence = [], [], []
    for index, p in enumerate(plans, 1):
        label = p["priority"].replace("Higher priority", "High priority")
        found.append(f"{index}. {p['address']} — {label} · {p['age_basis']} for {p['days']} days · Last meaningful price/terms change: "
                     + (f"{p['days_since_change']} days ago" if p["days_since_change"] is not None else "not verified"))
        actions.append(f"**{index}. {p['address']} — PROPOSED PLAN**\n\n" + "\n\n".join(f"{n}. {step}" for n, step in enumerate(p["plan"], 1))
                       + ("\n\n" + "\n\n".join(p["options"]) if p["options"] else "\n\nNo supported numerical target is available; no market value or terms were guessed."))
        evidence.append(f"{p['address']}\nVERIFIED / RECORDED FACTS:\n" + "\n".join(p["facts"]) + "\nLIKELY REASONS AND EVIDENCE STRENGTH:\n"
                        + "\n".join(p["reasons"]) + "\nMISSING INFORMATION:\n" + "\n".join(p["missing"]) + "\n" + "\n".join(p["evidence"]))
    return CorePilotResult("complete", tuple(found) or ("No qualifying stale inventory is verified by the available dates.",),
                           (f"{len(plans)} marketed properties need disposition attention. Source availability is not proof of closing.",),
                           "\n\n".join(actions) or "The two-hour checker will flag every qualifying yellow property as its verified marketing age reaches 10, 14 and 21 days.",
                           evidence=tuple(evidence), inventory_causes=tuple(f"{p['address']}: " + "; ".join(p["reasons"]) for p in plans))
