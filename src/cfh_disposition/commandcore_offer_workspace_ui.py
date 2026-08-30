from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cfh_disposition.commandcore_offer_engine import OfferAssumptions, OfferDealInput, analyze_deal, money


EXIT_MODES = ["Auto", "Slow Flip Only", "Wholesale Only"]
RENT_CONFIDENCE_OPTIONS = ["Weak", "Medium", "Strong"]


def text(value: Any) -> str:
    return str(value or "").strip()


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def first_number(*values: Any) -> float:
    for value in values:
        parsed = number(value)
        if parsed > 0:
            return parsed
    return 0.0


def property_address(property_record: dict[str, Any] | None) -> str:
    record = property_record or {}
    return text(record.get("address")) or text(record.get("property_address"))


def property_market(property_record: dict[str, Any] | None) -> str:
    record = property_record or {}
    return ", ".join(
        item
        for item in [text(record.get("city")), text(record.get("state"))]
        if item
    )


def default_values(deal: dict[str, Any], property_record: dict[str, Any] | None) -> dict[str, Any]:
    property_record = property_record or {}
    return {
        "address": property_address(property_record) or text(deal.get("address")),
        "market": property_market(property_record) or text(deal.get("market")),
        "asking_price": first_number(
            deal.get("asking_price"),
            property_record.get("asking_price"),
            deal.get("seller_asking_price"),
        ),
        "rent": first_number(deal.get("rent"), property_record.get("rent"), property_record.get("market_rent")),
        "arv": first_number(deal.get("arv"), property_record.get("arv"), property_record.get("estimated_arv")),
        "repairs": first_number(deal.get("repairs"), property_record.get("repairs"), deal.get("repair_estimate")),
        "beds": first_number(property_record.get("bedrooms"), property_record.get("beds")),
        "baths": first_number(property_record.get("bathrooms"), property_record.get("baths")),
        "sqft": first_number(property_record.get("square_feet"), property_record.get("sqft")),
        "taxes": first_number(property_record.get("annual_taxes"), property_record.get("taxes")),
        "days_on_market": int(first_number(property_record.get("days_on_market"), deal.get("days_on_market"))),
        "status": text(deal.get("status")) or "Active",
        "occupancy": text(property_record.get("occupancy")) or text(deal.get("occupancy")) or "Unknown",
        "livable": text(property_record.get("livable")) or text(deal.get("livable")) or "Unknown",
        "notes": "\n".join(
            item
            for item in [text(deal.get("notes")), text(property_record.get("notes"))]
            if item
        ),
    }


def build_input(values: dict[str, Any]) -> OfferDealInput:
    return OfferDealInput(
        address=text(values.get("address")),
        market=text(values.get("market")),
        lead_type=text(values.get("lead_type")) or "Agent",
        exit_mode=text(values.get("exit_mode")) or "Auto",
        asking_price=number(values.get("asking_price")),
        rent=number(values.get("rent")),
        beds=number(values.get("beds")),
        baths=number(values.get("baths")),
        sqft=number(values.get("sqft")),
        taxes=number(values.get("taxes")),
        status=text(values.get("status")) or "Active",
        occupancy=text(values.get("occupancy")) or "Unknown",
        livable=text(values.get("livable")) or "Unknown",
        days_on_market=int(number(values.get("days_on_market"))),
        notes=text(values.get("notes")),
        arv=number(values.get("arv")),
        repairs=number(values.get("repairs")),
        rent_source=text(values.get("rent_source")) or "Missing / RentCast unavailable",
        rent_confidence=text(values.get("rent_confidence")) or "Weak",
        rent_verification_needed=text(values.get("rent_verification_needed")) or "Yes",
    )


def analysis_status(result: dict[str, Any]) -> str:
    if text(result.get("best_exit")) in {"Needs Human Review", "Pass"} or text(result.get("grade")) in {"Review", "Pass"}:
        return "analysis_needs_review"
    return "analysis_complete"


def offer_record(
    *,
    deal_id: str,
    result: dict[str, Any],
    values: dict[str, Any],
    status: str | None = None,
    existing_id: str = "",
) -> dict[str, Any]:
    best = result.get("best", {}) if isinstance(result.get("best"), dict) else {}
    amount = first_number(best.get("offer_to_send"), best.get("first_offer"))
    record = {
        "amount": amount,
        "status": status or analysis_status(result),
        "source": "commandcore-offer-engine",
        "terms": {
            "strategy": result.get("best_exit"),
            "grade": result.get("grade"),
            "starting_offer": amount,
            "maximum_offer": number(best.get("max_offer")),
            "buyer_or_resale_target": first_number(best.get("buyer_target"), best.get("resale_to_slow_flipper")),
            "estimated_margin_at_ask": number(best.get("estimated_fee_at_ask")),
            "facts": {
                "address": text(values.get("address")),
                "market": text(values.get("market")),
                "asking_price": number(values.get("asking_price")),
                "rent": number(values.get("rent")),
                "arv": number(values.get("arv")),
                "repairs": number(values.get("repairs")),
                "rent_source": text(values.get("rent_source")),
                "rent_confidence": text(values.get("rent_confidence")),
                "rent_verification_needed": text(values.get("rent_verification_needed")),
            },
            "internal_only": True,
            "external_action_started": False,
        },
        "links": {"deal_id": deal_id},
        "external_action_started": False,
    }
    if existing_id:
        record["id"] = existing_id
    return record


def activity_record(deal_id: str, result: dict[str, Any]) -> dict[str, Any]:
    best = result.get("best", {}) if isinstance(result.get("best"), dict) else {}
    starting = first_number(best.get("offer_to_send"), best.get("first_offer"))
    maximum = number(best.get("max_offer"))
    return {
        "activity_type": "deal_analysis",
        "title": "Offer Engine analysis saved",
        "summary": (
            f"{text(result.get('best_exit')) or 'Review'} recommendation; "
            f"start {money(starting)}, max {money(maximum)}, grade {text(result.get('grade')) or 'Review'}."
        ),
        "source": "commandcore-offer-engine",
        "details": {
            "best_exit": result.get("best_exit"),
            "grade": result.get("grade"),
            "starting_offer": starting,
            "maximum_offer": maximum,
            "external_action_started": False,
        },
        "links": {"deal_id": deal_id},
    }


def _session_key(deal_id: str, suffix: str) -> str:
    return f"commandcore_offer_{deal_id}_{suffix}"


def render_offer_workspace(
    st: Any,
    *,
    deal: dict[str, Any],
    deal_id: str,
    property_record: dict[str, Any] | None,
    upsert_record: Callable[[str, dict[str, Any]], dict[str, Any]],
    save_related: Callable[[str, str, dict[str, Any]], bool],
) -> None:
    defaults = default_values(deal, property_record)
    st.markdown("### Deal Analysis")
    st.caption(
        "CommandCore uses the Offer Engine rules inside this Deal. Running analysis is internal only; it does not send or approve an offer."
    )

    with st.form(_session_key(deal_id, "analysis_form")):
        top = st.columns([1.6, 1, 1])
        address = top[0].text_input("Property", value=defaults["address"])
        exit_mode = top[1].selectbox("Deal lane", EXIT_MODES)
        asking_price = top[2].number_input("Asking price", min_value=0.0, value=float(defaults["asking_price"]), step=500.0)

        numbers = st.columns(3)
        rent = numbers[0].number_input("Monthly rent", min_value=0.0, value=float(defaults["rent"]), step=50.0)
        arv = numbers[1].number_input("ARV / value", min_value=0.0, value=float(defaults["arv"]), step=1000.0)
        repairs = numbers[2].number_input("Repairs", min_value=0.0, value=float(defaults["repairs"]), step=1000.0)

        with st.expander("Evidence & property details", expanded=False):
            evidence = st.columns(3)
            rent_source = evidence[0].text_input("Rent source", value="Verified comps" if defaults["rent"] > 0 else "")
            rent_confidence = evidence[1].selectbox("Rent confidence", RENT_CONFIDENCE_OPTIONS, index=0)
            rent_verified = evidence[2].checkbox("Rent comps verified", value=False)
            notes = st.text_area("Condition / deal notes", value=defaults["notes"], height=90)

        submitted = st.form_submit_button("Analyze Deal", type="primary", use_container_width=True)

    if submitted:
        values = {
            **defaults,
            "address": address,
            "exit_mode": exit_mode,
            "asking_price": asking_price,
            "rent": rent,
            "arv": arv,
            "repairs": repairs,
            "rent_source": rent_source,
            "rent_confidence": rent_confidence,
            "rent_verification_needed": "No" if rent_verified else "Yes",
            "notes": notes,
            "lead_type": "Agent" if "agent" in text(deal.get("source")).lower() else "Seller",
        }
        result = analyze_deal(build_input(values), OfferAssumptions())
        st.session_state[_session_key(deal_id, "values")] = values
        st.session_state[_session_key(deal_id, "result")] = result
        st.session_state.pop(_session_key(deal_id, "saved_offer_id"), None)

    result = st.session_state.get(_session_key(deal_id, "result"))
    values = st.session_state.get(_session_key(deal_id, "values"))
    if not isinstance(result, dict) or not isinstance(values, dict):
        st.info("Review the available Deal facts above, fill any missing evidence, then choose Analyze Deal.")
        return

    best = result.get("best", {}) if isinstance(result.get("best"), dict) else {}
    with st.container(border=True):
        st.markdown(f"#### {text(result.get('best_exit')) or 'Needs Human Review'}")
        metrics = st.columns(4)
        metrics[0].metric("Starting Offer", money(first_number(best.get("offer_to_send"), best.get("first_offer"))))
        metrics[1].metric("Absolute Maximum", money(best.get("max_offer")))
        metrics[2].metric("Asking Price", money(values.get("asking_price")))
        metrics[3].metric("Grade", text(result.get("grade")) or "Review")
        target = first_number(best.get("buyer_target"), best.get("resale_to_slow_flipper"))
        st.caption(f"Buyer / resale target: {money(target)}")
        if text(result.get("best_exit")) == "Needs Human Review":
            st.warning("The current evidence is not strong enough for a clean buy recommendation. Verify the missing inputs before approval.")
        if text(result.get("best_exit")) == "Pass":
            st.error("The current numbers do not support this deal under the selected lane.")

    saved_id = text(st.session_state.get(_session_key(deal_id, "saved_offer_id")))
    save_col, approval_col = st.columns(2)
    if save_col.button("Save Internal Analysis", type="primary", use_container_width=True, key=_session_key(deal_id, "save")):
        saved = upsert_record("offers", offer_record(deal_id=deal_id, result=result, values=values, existing_id=saved_id))
        saved_id = text(saved.get("id"))
        if saved_id:
            st.session_state[_session_key(deal_id, "saved_offer_id")] = saved_id
        history_saved = save_related("activities", deal_id, activity_record(deal_id, result))
        if saved and history_saved:
            st.success("Analysis saved to Offers and Deal History. Nothing was sent or approved.")
        else:
            st.error("CommandCore could not save the complete analysis record.")

    if approval_col.button("Request Owner Approval", use_container_width=True, key=_session_key(deal_id, "approval")):
        saved = upsert_record(
            "offers",
            offer_record(
                deal_id=deal_id,
                result=result,
                values=values,
                status="draft_pending_owner_approval",
                existing_id=saved_id,
            ),
        )
        saved_id = text(saved.get("id"))
        if saved_id:
            st.session_state[_session_key(deal_id, "saved_offer_id")] = saved_id
            st.success("Offer recommendation sent to the existing Owner Approval Queue. No offer was sent externally.")
        else:
            st.error("CommandCore could not create the owner-approval item.")
