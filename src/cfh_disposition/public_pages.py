from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from html import escape
from urllib.parse import urlsplit
from uuid import UUID

import pandas as pd
import streamlit as st

from .analytics import (
    LIVE_TRAFFIC,
    TEST_TRAFFIC,
    UNCLASSIFIED_TRAFFIC,
    AnalyticsError,
    ClickAnalyticsStore,
    ClickEvent,
    click_summary,
    traffic_type_counts,
)
from .channel_tracking import (
    build_channel_links,
    canonical_channel_key,
    channel_name,
    channel_scorecard,
    unmapped_clicks,
)
from .channels import CHANNELS
from .dwelyx import (
    build_direct_dwelyx_url,
    build_dwelyx_url,
    dwelyx_base_url,
    tracking_app_base_url,
)
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
    st.caption(
        "Owner-financing opportunities with clear terms and straightforward property information."
    )


def _browse_dwelyx_url(
    *,
    medium: str,
    property_id: UUID | None = None,
    target: str | None = None,
) -> str:
    return build_dwelyx_url(
        target or dwelyx_base_url(st.secrets),
        source="credit_friendly_homes",
        medium=medium,
        property_id=property_id,
        tracking_base_url=tracking_app_base_url(st.secrets),
    )


def _render_portal(storage: Storage) -> None:
    _render_header()
    st.link_button(
        "Browse All Owner-Finance Homes on Dwelyx",
        _browse_dwelyx_url(medium="property_page"),
        type="primary",
        use_container_width=True,
    )
    st.caption(
        "Dwelyx is the main marketplace. Buyers can browse every available owner-finance home there."
    )
    st.subheader("Featured Owner-Finance Homes")
    properties = _available_properties(storage)
    if not properties:
        st.info(
            "No featured homes are available here right now. Browse Dwelyx for the full inventory."
        )
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
            st.markdown(
                f"[View featured-home details]({public_property_path(item.property_id)})"
            )
            st.link_button(
                "Browse All Homes on Dwelyx",
                _browse_dwelyx_url(
                    medium="property_page",
                    property_id=item.property_id,
                ),
                use_container_width=True,
            )
            st.divider()

    st.caption(
        "Availability and terms are subject to verification. Equal Housing Opportunity."
    )


def _render_property_detail(storage: Storage, property_id: str) -> None:
    _render_header()
    properties = _available_properties(storage)
    selected = next(
        (item for item in properties if str(item.property_id) == property_id),
        None,
    )
    if selected is None:
        st.warning("This featured property is not currently available.")
        st.link_button(
            "Browse All Owner-Finance Homes on Dwelyx",
            _browse_dwelyx_url(medium="property_page"),
            type="primary",
            use_container_width=True,
        )
        return

    location = public_location(selected)
    st.markdown(f"[← Browse featured homes]({public_portal_path()})")
    st.header(f"Owner-Finance Home — {location}")

    st.link_button(
        "Browse All Owner-Finance Homes on Dwelyx",
        _browse_dwelyx_url(
            medium="property_page",
            property_id=selected.property_id,
        ),
        type="primary",
        use_container_width=True,
    )
    st.caption(
        "This home may not be the right fit. Dwelyx shows the full owner-finance inventory."
    )

    if selected.photo_urls:
        st.image(
            [str(item) for item in selected.photo_urls],
            use_container_width=True,
        )

    price, down, monthly = st.columns(3)
    price.metric("Purchase price", money(selected.total_price))
    down.metric("Down payment", money(selected.down_payment))
    monthly.metric("Monthly payment", money(selected.monthly_payment))

    details = st.columns(4)
    details[0].metric(
        "Bedrooms",
        selected.bedrooms if selected.bedrooms is not None else "—",
    )
    details[1].metric(
        "Bathrooms",
        selected.bathrooms if selected.bathrooms is not None else "—",
    )
    details[2].metric(
        "Square feet",
        f"{selected.square_feet:,}" if selected.square_feet else "—",
    )
    details[3].metric(
        "Acreage",
        selected.acreage if selected.acreage is not None else "—",
    )

    st.subheader("Property condition")
    st.write(selected.condition_summary)

    if selected.repairs_needed:
        st.subheader("Known repairs or work needed")
        st.write(selected.repairs_needed)

    st.subheader("Important disclosures")
    st.write(selected.public_disclosures)

    listing_url = str(selected.application_url) if selected.application_url else ""
    if _is_dwelyx_listing(listing_url):
        st.link_button(
            "View This Home on Dwelyx",
            _browse_dwelyx_url(
                medium="property_page",
                property_id=selected.property_id,
                target=listing_url,
            ),
            use_container_width=True,
        )

    st.caption(
        "This page is an advertisement for an owner-financing opportunity, not a promise of approval. "
        "Terms, availability, and property information are subject to verification. Equal Housing Opportunity."
    )


def _query_value(name: str, default: str = "") -> str:
    return str(st.query_params.get(name, default)).strip()


def _query_flag(name: str) -> bool:
    return _query_value(name).lower() in {"1", "true", "yes", "on"}


def _test_tracking_url(url: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}test_mode=1"


def _render_dwelyx_redirect() -> None:
    configured_target = dwelyx_base_url(st.secrets)
    requested_target = _query_value("target", configured_target)
    target = (
        requested_target
        if _is_dwelyx_listing(requested_target)
        else configured_target
    )
    source = _query_value("source", "credit_friendly_homes")
    medium = _query_value("medium", "unknown")
    campaign = _query_value("campaign", "owner_finance_homes")
    property_id = _query_value("property_id") or None
    traffic_type = TEST_TRAFFIC if _query_flag("test_mode") else LIVE_TRAFFIC

    destination = build_direct_dwelyx_url(
        target,
        source=source,
        medium=medium,
        campaign=campaign,
        property_id=property_id,
    )

    signature = f"{source}|{medium}|{campaign}|{property_id or ''}|{traffic_type}"
    session_key = f"dwelyx_click_logged::{signature}"
    if not st.session_state.get(session_key):
        try:
            ClickAnalyticsStore(st.secrets).record(
                ClickEvent(
                    occurred_at=datetime.now(UTC),
                    source=source,
                    medium=medium,
                    campaign=campaign,
                    property_id=property_id,
                    traffic_type=traffic_type,
                )
            )
            st.session_state[session_key] = True
        except AnalyticsError:
            # Never block a buyer from reaching Dwelyx because analytics is unavailable.
            pass

    st.title("Opening Dwelyx")
    if traffic_type == TEST_TRAFFIC:
        st.info("Test link opened. This click is marked as TEST and excluded from live buyer metrics.")
    else:
        st.write("You are being sent to the full owner-finance marketplace.")
    st.link_button(
        "Continue to Dwelyx",
        destination,
        type="primary",
        use_container_width=True,
    )
    safe_destination = escape(destination, quote=True)
    st.markdown(
        f'<meta http-equiv="refresh" content="0; url={safe_destination}">',
        unsafe_allow_html=True,
    )


def _render_channel_center(storage: Storage) -> None:
    channel_count = len(CHANNELS)
    st.title(f"{channel_count}-Channel Link Center")
    st.caption(
        "Create a separate tracked Dwelyx link for every marketing channel so the dashboard can show what is producing traffic."
    )

    properties = _available_properties(storage)
    property_options: dict[str, OwnerFinanceProperty | None] = {
        "All Dwelyx inventory": None
    }
    property_options.update(
        {item.display_address: item for item in properties}
    )

    left, right = st.columns(2)
    campaign = left.text_input("Campaign name", value="owner_finance_homes")
    selected_property_name = right.selectbox(
        "Property — optional",
        list(property_options),
    )
    selected_property = property_options[selected_property_name]

    links = build_channel_links(
        dwelyx_base_url(st.secrets),
        campaign=campaign,
        property_id=(
            selected_property.property_id if selected_property else None
        ),
        tracking_base_url=tracking_app_base_url(st.secrets),
    )

    st.success(f"{len(links)} separate channel links are ready.")
    selected_channel_name = st.selectbox(
        "Choose a channel to copy or test",
        [row["Channel"] for row in links],
    )
    selected_row = next(
        row for row in links if row["Channel"] == selected_channel_name
    )
    live_tracking_url = selected_row["Tracked Dwelyx link"]
    st.text_input(
        "Copy this channel's LIVE tracked Dwelyx link",
        value=live_tracking_url,
    )
    st.link_button(
        "Test This Channel Link — records TEST click",
        _test_tracking_url(live_tracking_url),
        type="primary",
    )
    st.caption("Test-link clicks are kept for diagnostics but excluded from live buyer metrics and optimization decisions.")

    st.subheader(f"Complete {channel_count}-channel link sheet")
    link_table = pd.DataFrame(links)
    st.dataframe(
        link_table,
        use_container_width=True,
        hide_index=True,
        height=max(420, channel_count * 35 + 45),
    )
    st.download_button(
        f"Download {channel_count}-channel link sheet (CSV)",
        data=link_table.to_csv(index=False).encode("utf-8"),
        file_name=(
            f"cfh_{channel_count}_channel_links_"
            f"{campaign.strip() or 'campaign'}.csv"
        ),
        mime="text/csv",
    )
    st.info(
        "Use the matching live link in each channel. For a sign or QR-code campaign, use the Property Landing Page link and give the campaign a specific name such as saltville_signs_august_2026."
    )
    st.markdown(
        f"[Open the {channel_count}-Channel Marketing Analytics dashboard](?analytics=1)"
    )


def _render_click_analytics(storage: Storage) -> None:
    channel_count = len(CHANNELS)
    st.title(f"{channel_count}-Channel Marketing Analytics")
    st.caption(
        f"See which of the {channel_count} channels, campaigns, and properties send real buyers into Dwelyx."
    )
    days = st.selectbox(
        "Reporting window",
        [7, 30, 90],
        index=1,
        format_func=lambda value: f"Last {value} days",
    )

    try:
        all_events = ClickAnalyticsStore(st.secrets).list_recent(
            days,
            include_test=True,
            include_unclassified=True,
        )
    except AnalyticsError as exc:
        st.error(str(exc))
        return

    counts = traffic_type_counts(all_events)
    traffic_view = st.selectbox(
        "Traffic shown in the dashboard",
        [
            "Live buyer traffic",
            "Live + unclassified legacy traffic",
            "All traffic including tests",
        ],
        index=0,
    )
    if traffic_view == "Live buyer traffic":
        events = [event for event in all_events if event.traffic_type == LIVE_TRAFFIC]
    elif traffic_view == "Live + unclassified legacy traffic":
        events = [event for event in all_events if event.traffic_type != TEST_TRAFFIC]
    else:
        events = list(all_events)

    status_columns = st.columns(3)
    status_columns[0].metric("Live buyer clicks", counts[LIVE_TRAFFIC])
    status_columns[1].metric("Test clicks", counts[TEST_TRAFFIC])
    status_columns[2].metric("Unclassified legacy clicks", counts[UNCLASSIFIED_TRAFFIC])

    if counts[TEST_TRAFFIC]:
        st.info(
            f"{counts[TEST_TRAFFIC]} test click(s) are stored for diagnostics and excluded from live metrics by default."
        )
    if counts[UNCLASSIFIED_TRAFFIC]:
        st.warning(
            f"{counts[UNCLASSIFIED_TRAFFIC]} older click(s) were recorded before traffic classification existed. "
            "They are labeled UNCLASSIFIED and excluded from live metrics unless you explicitly include them."
        )

    scorecard = channel_scorecard(events)
    mapped_clicks = sum(row.clicks for row in scorecard)
    active_channels = sum(row.clicks > 0 for row in scorecard)
    zero_channels = len(CHANNELS) - active_channels
    top_row = max(scorecard, key=lambda row: row.clicks)
    top_channel = top_row.channel.name if top_row.clicks else "No traffic yet"

    columns = st.columns(4)
    columns[0].metric("Displayed tracked clicks", mapped_clicks)
    columns[1].metric(
        "Active channels",
        f"{active_channels} of {channel_count}",
    )
    columns[2].metric("Channels with zero traffic", zero_channels)
    columns[3].metric("Top channel", top_channel)

    st.subheader(f"All {channel_count} channels")
    score_rows = [row.as_row() for row in scorecard]
    st.dataframe(
        pd.DataFrame(score_rows),
        use_container_width=True,
        hide_index=True,
        height=max(420, channel_count * 35 + 45),
    )

    if not events:
        if all_events:
            st.info("No clicks match the selected traffic classification. Live buyer metrics remain at zero until a verified live click arrives.")
        else:
            st.info(
                "No tracked Dwelyx clicks have been recorded in this reporting window yet."
            )
        st.caption(
            f"Use live links from the {channel_count}-Channel Link Center. Each buyer click is classified before Dwelyx opens."
        )
        st.markdown(
            f"[Open the {channel_count}-Channel Link Center](?channel_center=1)"
        )
        return

    summary = click_summary(events)
    now = datetime.now(UTC)
    seven_day_clicks = sum(
        event.occurred_at >= now - timedelta(days=7)
        for event in events
    )
    st.caption(f"Displayed clicks recorded in the last 7 days: {seven_day_clicks}")

    campaign_rows = [
        {
            "Campaign": campaign.replace("_", " ").title(),
            "Clicks": clicks,
        }
        for campaign, clicks in summary["campaigns"].items()
    ]
    st.subheader("Clicks by campaign")
    st.dataframe(
        pd.DataFrame(campaign_rows),
        use_container_width=True,
        hide_index=True,
    )

    properties = {
        str(item.property_id): item.display_address
        for item in _available_properties(storage)
    }
    property_counts = Counter(
        event.property_id or "all_inventory"
        for event in events
        if canonical_channel_key(event.medium)
    )
    property_rows = [
        {
            "Property": (
                "All Dwelyx inventory"
                if property_id == "all_inventory"
                else properties.get(property_id, property_id)
            ),
            "Clicks": clicks,
        }
        for property_id, clicks in property_counts.most_common()
    ]
    st.subheader("Clicks by property")
    st.dataframe(
        pd.DataFrame(property_rows),
        use_container_width=True,
        hide_index=True,
    )

    recent_rows = []
    for event in events[:250]:
        recent_rows.append(
            {
                "Date and time (UTC)": event.occurred_at.strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "Traffic": event.traffic_type.title(),
                "Channel": channel_name(event.medium),
                "Campaign": event.campaign.replace("_", " ").title(),
                "Property": properties.get(
                    event.property_id or "",
                    event.property_id or "All Dwelyx inventory",
                ),
            }
        )
    st.subheader("Recent tracked clicks")
    st.dataframe(
        pd.DataFrame(recent_rows),
        use_container_width=True,
        hide_index=True,
    )

    other_events = unmapped_clicks(events)
    if other_events:
        st.subheader("Other or legacy traffic")
        other_counts = Counter(event.medium for event in other_events)
        other_rows = [
            {"Source": channel_name(medium), "Clicks": clicks}
            for medium, clicks in other_counts.most_common()
        ]
        st.dataframe(
            pd.DataFrame(other_rows),
            use_container_width=True,
            hide_index=True,
        )

    st.caption(
        "Click events contain marketing attribution only. No buyer names, emails, phone numbers, or private application data are stored here."
    )
    st.markdown(
        f"[Open the {channel_count}-Channel Link Center](?channel_center=1)"
    )


def render_public_request(storage: Storage) -> bool:
    """Render public routes before the private password gate."""
    go = _query_value("go").lower()
    analytics = _query_value("analytics").lower()
    channel_center = _query_value("channel_center").lower()
    property_id = _query_value("property")
    homes = _query_value("homes").lower()

    if go == "dwelyx":
        _render_dwelyx_redirect()
        return True
    if (
        channel_center in {"1", "true", "yes"}
        and st.session_state.get("authenticated")
    ):
        _render_channel_center(storage)
        return True
    if (
        analytics in {"1", "true", "yes"}
        and st.session_state.get("authenticated")
    ):
        _render_click_analytics(storage)
        return True
    if property_id:
        _render_property_detail(storage, property_id)
        return True
    if homes in {"1", "true", "yes"}:
        _render_portal(storage)
        return True
    return False
