from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html import escape
from urllib.parse import urlsplit
from uuid import UUID

import pandas as pd
import streamlit as st

from .analytics import AnalyticsError, ClickAnalyticsStore, ClickEvent, click_summary
from .dwelyx import build_direct_dwelyx_url, build_dwelyx_url, dwelyx_base_url
from .launch_plan import build_launch_plan
from .models import OwnerFinanceProperty, PropertyStatus
from .storage import Storage, StorageError

PUBLIC_PROPERTY_STATUSES = {PropertyStatus.READY, PropertyStatus.LIVE}


def money(value: Decimal | None) -> str:
    return "Contact us" if value is None else f"${value:,.0f}"


def public_location(item: OwnerFinanceProperty) -> str:
    """Return the complete marketing address, including the street address."""
    city_state = ", ".join(part for part in [item.city, item.state] if part)
    locality = f"{city_state} {item.zip_code}".strip()
    return ", ".join(part for part in [item.address, locality] if part)


def is_public_property(item: OwnerFinanceProperty) -> bool:
    return item.status in PUBLIC_PROPERTY_STATUSES and build_launch_plan(item).can_launch


def public_property_path(property_id: UUID) -> str:
    return f"?property={property_id}"


def public_portal_path() -> str:
    return "?homes=1"


def _is_dwelyx_listing(url: str | None) -> bool:
    if not url:
        return False
    hostname = (urlsplit(url).hostname or "").lower()
    return hostname == "dwelyx.com" or hostname.endswith(".dwelyx.com")


def _available_properties(storage: Storage) -> list[OwnerFinanceProperty]:
    try:
        properties = storage.list_properties()
    except StorageError:
        return []
    return [item for item in properties if is_public_property(item)]


def _render_header() -> None:
    st.title("Credit Friendly Homes")
    st.caption("Owner-financing opportunities with clear terms and straightforward property information.")


def _browse_dwelyx_url(*, medium: str, property_id: UUID | None = None) -> str:
    return build_dwelyx_url(
        dwelyx_base_url(st.secrets),
        source="credit_friendly_homes",
        medium=medium,
        property_id=property_id,
    )


def _render_portal(storage: Storage) -> None:
    _render_header()
    st.link_button(
        "Browse All Owner-Finance Homes on Dwelyx",
        _browse_dwelyx_url(medium="available_homes_portal"),
        type="primary",
        use_container_width=True,
    )
    st.caption("Dwelyx is the main marketplace. Buyers can browse every available owner-finance home there.")
    st.subheader("Featured Owner-Finance Homes")
    properties = _available_properties(storage)
    if not properties:
        st.info("No featured homes are available here right now. Browse Dwelyx for the full inventory.")
        st.caption("Equal Housing Opportunity")
        return

    columns = st.columns(3)
    for index, item in enumerate(properties):
        with columns[index % 3]:
            if item.photo_urls:
                st.image(str(item.photo_urls[0]), use_container_width=True)
            st.markdown(f"### {public_location(item)}")
            st.write(f"**{item.bedrooms or 0} bed · {item.bathrooms or 0} bath**")
            st.write(f"Price: **{money(item.total_price)}**")
            st.write(f"Down payment: **{money(item.down_payment)}**")
            st.write(f"Monthly payment: **{money(item.monthly_payment)}**")
            st.markdown(f"[View featured-home details]({public_property_path(item.property_id)})")
            st.link_button(
                "Browse All Homes on Dwelyx",
                _browse_dwelyx_url(medium="featured_home_card", property_id=item.property_id),
                use_container_width=True,
            )
            st.divider()

    st.caption("Availability and terms are subject to verification. Equal Housing Opportunity.")


def _render_property_detail(storage: Storage, property_id: str) -> None:
    _render_header()
    properties = _available_properties(storage)
    selected = next((item for item in properties if str(item.property_id) == property_id), None)
    if selected is None:
        st.warning("This featured property is not currently available.")
        st.link_button(
            "Browse All Owner-Finance Homes on Dwelyx",
            _browse_dwelyx_url(medium="unavailable_property_page"),
            type="primary",
            use_container_width=True,
        )
        return

    location = public_location(selected)
    st.markdown(f"[← Browse featured homes]({public_portal_path()})")
    st.header(f"Owner-Finance Home — {location}")

    st.link_button(
        "Browse All Owner-Finance Homes on Dwelyx",
        _browse_dwelyx_url(medium="property_landing_page", property_id=selected.property_id),
        type="primary",
        use_container_width=True,
    )
    st.caption("This home may not be the right fit. Dwelyx shows the full owner-finance inventory.")

    if selected.photo_urls:
        st.image([str(item) for item in selected.photo_urls], use_container_width=True)

    price, down, monthly = st.columns(3)
    price.metric("Purchase price", money(selected.total_price))
    down.metric("Down payment", money(selected.down_payment))
    monthly.metric("Monthly payment", money(selected.monthly_payment))

    details = st.columns(4)
    details[0].metric("Bedrooms", selected.bedrooms if selected.bedrooms is not None else "—")
    details[1].metric("Bathrooms", selected.bathrooms if selected.bathrooms is not None else "—")
    details[2].metric("Square feet", f"{selected.square_feet:,}" if selected.square_feet else "—")
    details[3].metric("Acreage", selected.acreage if selected.acreage is not None else "—")

    st.subheader("Property condition")
    st.write(selected.condition_summary)

    if selected.repairs_needed:
        st.subheader("Known repairs or work needed")
        st.write(selected.repairs_needed)

    st.subheader("Important disclosures")
    st.write(selected.public_disclosures)

    listing_url = str(selected.application_url) if selected.application_url else ""
    if _is_dwelyx_listing(listing_url):
        st.link_button("View This Home on Dwelyx", listing_url, use_container_width=True)

    st.caption(
        "This page is an advertisement for an owner-financing opportunity, not a promise of approval. "
        "Terms, availability, and property information are subject to verification. Equal Housing Opportunity."
    )


def _query_value(name: str, default: str = "") -> str:
    return str(st.query_params.get(name, default)).strip()


def _render_dwelyx_redirect() -> None:
    configured_target = dwelyx_base_url(st.secrets)
    requested_target = _query_value("target", configured_target)
    target = requested_target if _is_dwelyx_listing(requested_target) else configured_target
    source = _query_value("source", "credit_friendly_homes")
    medium = _query_value("medium", "unknown")
    campaign = _query_value("campaign", "owner_finance_homes")
    property_id = _query_value("property_id") or None

    destination = build_direct_dwelyx_url(
        target,
        source=source,
        medium=medium,
        campaign=campaign,
        property_id=property_id,
    )

    signature = f"{source}|{medium}|{campaign}|{property_id or ''}"
    session_key = f"dwelyx_click_logged::{signature}"
    if not st.session_state.get(session_key):
        try:
            ClickAnalyticsStore(st.secrets).record(
                ClickEvent(
                    occurred_at=datetime.now(timezone.utc),
                    source=source,
                    medium=medium,
                    campaign=campaign,
                    property_id=property_id,
                )
            )
            st.session_state[session_key] = True
        except AnalyticsError:
            # Never block a buyer from reaching Dwelyx because analytics is unavailable.
            pass

    st.title("Opening Dwelyx")
    st.write("You are being sent to the full owner-finance marketplace.")
    st.link_button("Continue to Dwelyx", destination, type="primary", use_container_width=True)
    safe_destination = escape(destination, quote=True)
    st.markdown(
        f'<meta http-equiv="refresh" content="0; url={safe_destination}">',
        unsafe_allow_html=True,
    )


def _render_click_analytics(storage: Storage) -> None:
    st.title("Dwelyx Click Analytics")
    st.caption("See which channels, campaigns, and properties send buyers into Dwelyx.")
    days = st.selectbox("Reporting window", [7, 30, 90], index=1, format_func=lambda value: f"Last {value} days")

    try:
        events = ClickAnalyticsStore(st.secrets).list_recent(days)
    except AnalyticsError as exc:
        st.error(str(exc))
        return

    summary = click_summary(events)
    now = datetime.now(timezone.utc)
    seven_day_clicks = sum(event.occurred_at >= now - timedelta(days=7) for event in events)
    columns = st.columns(4)
    columns[0].metric("Total clicks", summary["total"])
    columns[1].metric("Clicks in last 7 days", seven_day_clicks)
    columns[2].metric("Active channels", len(summary["sources"]))
    columns[3].metric("Active campaigns", len(summary["campaigns"]))

    if not events:
        st.info("No tracked Dwelyx clicks have been recorded in this reporting window yet.")
        st.caption("Use links created by the app. Each buyer click will be recorded automatically before Dwelyx opens.")
        return

    properties = {str(item.property_id): item.display_address for item in _available_properties(storage)}
    source_rows = [
        {"Channel": source.replace("_", " ").title(), "Clicks": clicks}
        for source, clicks in summary["sources"].items()
    ]
    st.subheader("Clicks by channel")
    st.dataframe(pd.DataFrame(source_rows), use_container_width=True, hide_index=True)

    campaign_rows = [
        {"Campaign": campaign.replace("_", " ").title(), "Clicks": clicks}
        for campaign, clicks in summary["campaigns"].items()
    ]
    st.subheader("Clicks by campaign")
    st.dataframe(pd.DataFrame(campaign_rows), use_container_width=True, hide_index=True)

    recent_rows = []
    for event in events[:250]:
        recent_rows.append(
            {
                "Date and time (UTC)": event.occurred_at.strftime("%Y-%m-%d %H:%M:%S"),
                "Channel": event.medium.replace("_", " ").title(),
                "Campaign": event.campaign.replace("_", " ").title(),
                "Property": properties.get(event.property_id or "", event.property_id or "All Dwelyx inventory"),
            }
        )
    st.subheader("Recent tracked clicks")
    st.dataframe(pd.DataFrame(recent_rows), use_container_width=True, hide_index=True)
    st.caption("Click events contain marketing attribution only. No buyer names, emails, phone numbers, or private application data are stored here.")


def render_public_request(storage: Storage) -> bool:
    """Render public routes before the private password gate."""
    go = _query_value("go").lower()
    analytics = _query_value("analytics").lower()
    property_id = _query_value("property")
    homes = _query_value("homes").lower()

    if go == "dwelyx":
        _render_dwelyx_redirect()
        return True
    if analytics in {"1", "true", "yes"} and st.session_state.get("authenticated"):
        _render_click_analytics(storage)
        return True
    if property_id:
        _render_property_detail(storage, property_id)
        return True
    if homes in {"1", "true", "yes"}:
        _render_portal(storage)
        return True
    return False
