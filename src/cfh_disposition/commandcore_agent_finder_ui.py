from __future__ import annotations

from typing import Any

import streamlit as st

from .agent_contact_finder import AgentFinderError, AgentLookupRequest
from .agent_contact_search import search_agent_contacts


def _text(value: Any) -> str:
    return str(value or "").strip()


def _links(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("links")
    return value if isinstance(value, dict) else {}


def _linked_property_context(
    contact_id: str,
    deals: list[dict[str, Any]],
    properties: list[dict[str, Any]],
) -> tuple[str, str, str, str, str]:
    property_by_id = {_text(row.get("id")): row for row in properties if _text(row.get("id"))}
    for deal in deals:
        deal_links = _links(deal)
        if _text(deal_links.get("contact_id")) != contact_id:
            continue
        deal_id = _text(deal.get("id"))
        property_record = property_by_id.get(_text(deal_links.get("property_id")))
        if not property_record:
            return deal_id, "", "", "", ""
        return (
            deal_id,
            _text(property_record.get("address")),
            _text(property_record.get("city")),
            _text(property_record.get("state")),
            _text(deal.get("listing_url") or property_record.get("listing_url") or property_record.get("zillow_url")),
        )
    return "", "", "", "", ""


def _result_key(contact_id: str) -> str:
    return f"commandcore_agent_finder_result_{contact_id or 'new'}"


def _research_activity(
    *,
    deal_id: str,
    contact_id: str,
    contact_name: str,
    status: str,
    confidence_score: int,
    source_links: tuple[str, ...],
    phone_saved: bool,
    email_saved: bool,
) -> dict[str, Any]:
    saved_parts = []
    if phone_saved:
        saved_parts.append("phone")
    if email_saved:
        saved_parts.append("email")
    saved_label = " and ".join(saved_parts) if saved_parts else "research details"
    return {
        "activity_type": "agent_contact_research_saved",
        "summary": f"Agent Finder saved {saved_label} for {contact_name or 'this contact'}.",
        "source": "commandcore-agent-finder",
        "details": {
            "status": status,
            "confidence_score": confidence_score,
            "source_count": len(source_links),
            "requires_verification_before_outreach": True,
        },
        "links": {"deal_id": deal_id, "contact_id": contact_id},
    }


def render_agent_finder(
    *,
    contact: dict[str, Any],
    deals: list[dict[str, Any]],
    properties: list[dict[str, Any]],
    save_record: Any,
    secrets: Any,
) -> None:
    contact_id = _text(contact.get("id"))
    if not contact_id:
        st.caption("Save this contact first, then CommandCore can research and attach verified public contact details.")
        return

    name = _text(contact.get("name")) or " ".join(
        part for part in [_text(contact.get("first_name")), _text(contact.get("last_name"))] if part
    )
    brokerage = _text(contact.get("company") or contact.get("brokerage"))
    deal_id, address, city, state, listing_url = _linked_property_context(contact_id, deals, properties)

    with st.expander("Find Contact Info", expanded=False):
        st.write("Search public sources for this agent's phone and email without leaving CommandCore.")
        st.caption("CommandCore shows what it found before anything is saved. Always verify contact details before outreach.")

        searchapi_key = _text(secrets.get("SEARCHAPI_API_KEY", ""))
        if not searchapi_key:
            st.info("Agent Finder is not connected yet. Add the SearchApi connection in CommandCore setup before searching.")
            return

        with st.form(f"agent_finder_search_{contact_id}"):
            agent_name = st.text_input("Agent name", value=name)
            brokerage_input = st.text_input("Brokerage", value=brokerage)
            c1, c2 = st.columns(2)
            city_input = c1.text_input("City", value=city)
            state_input = c2.text_input("State", value=state)
            property_address = st.text_input("Property address (optional)", value=address)
            listing = st.text_input("Listing URL (optional)", value=listing_url)
            submitted = st.form_submit_button("Find Contact Info", type="primary", use_container_width=True)

        if submitted:
            try:
                result = search_agent_contacts(
                    AgentLookupRequest(
                        agent_name=agent_name,
                        brokerage=brokerage_input,
                        city=city_input,
                        state=state_input,
                        property_address=property_address,
                        listing_url=listing,
                    ),
                    api_key=searchapi_key,
                )
            except AgentFinderError as exc:
                st.error(str(exc))
            except Exception:
                st.error("CommandCore could not complete this contact search. No CRM records were changed.")
            else:
                st.session_state[_result_key(contact_id)] = result

        result = st.session_state.get(_result_key(contact_id))
        if result is None:
            return

        status = _text(getattr(result, "status", ""))
        if status == "Strong match":
            st.success("Strong match found. Review the details before saving.")
        elif status == "Possible match":
            st.warning("Possible match found. Check the sources before saving.")
        else:
            st.info(status or "No verified public match was confirmed.")

        summary = st.columns(3)
        confidence_score = int(getattr(result, "confidence_score", 0) or 0)
        summary[0].metric("Confidence", f"{confidence_score}%")
        summary[1].metric("Phone", _text(getattr(result, "phone", "")) or "Not found")
        summary[2].metric("Email", _text(getattr(result, "email", "")) or "Not found")
        st.caption(_text(getattr(result, "next_action", "")))

        source_links = tuple(getattr(result, "source_links", ()) or ())
        if source_links:
            with st.expander("Sources reviewed"):
                for link in source_links:
                    st.write(link)

        found_phone = _text(getattr(result, "phone", ""))
        found_email = _text(getattr(result, "email", ""))
        if not (found_phone or found_email):
            return

        replace_existing = st.checkbox(
            "Replace an existing phone/email with the found value",
            value=False,
            key=f"agent_finder_replace_{contact_id}",
            help="Leave this off to fill only blank contact fields.",
        )
        if st.button("Save Found Info", key=f"agent_finder_save_{contact_id}", use_container_width=True):
            updated = {**contact}
            phone_saved = bool(found_phone and (replace_existing or not _text(contact.get("phone"))))
            email_saved = bool(found_email and (replace_existing or not _text(contact.get("email"))))
            if phone_saved:
                updated["phone"] = found_phone
            if email_saved:
                updated["email"] = found_email
            updated["contact_research"] = {
                "source": "commandcore-agent-finder",
                "status": status,
                "confidence_score": confidence_score,
                "source_links": list(source_links),
                "requires_verification_before_outreach": True,
            }
            saved = save_record("contacts", updated)
            if not saved.get("ok"):
                st.error(_text(saved.get("error")) or "CommandCore could not save the found contact info.")
                return

            if deal_id:
                history = save_record(
                    "activities",
                    _research_activity(
                        deal_id=deal_id,
                        contact_id=contact_id,
                        contact_name=name,
                        status=status,
                        confidence_score=confidence_score,
                        source_links=source_links,
                        phone_saved=phone_saved,
                        email_saved=email_saved,
                    ),
                )
                if not history.get("ok"):
                    st.warning("Contact info was saved, but CommandCore could not add the research event to Deal history.")
                    return

            st.success("Contact info saved to CommandCore. Verify it before outreach.")
            st.session_state.pop(_result_key(contact_id), None)
            st.rerun()
