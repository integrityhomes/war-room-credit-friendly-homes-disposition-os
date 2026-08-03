from __future__ import annotations

from decimal import Decimal
from urllib.parse import urlsplit
from uuid import UUID

import streamlit as st

from .dwelyx import build_dwelyx_url, dwelyx_base_url
from .launch_plan import build_launch_plan
from .models import OwnerFinanceProperty, PropertyStatus
from .storage import Storage, StorageError

PUBLIC_PROPERTY_STATUSES = {PropertyStatus.READY, PropertyStatus.LIVE}


def money(value: Decimal | None) -> str:
    return "Contact us" if value is None else f"${value:,.0f}"


def public_location(item: OwnerFinanceProperty) -> str:
    """Return a marketing-safe location without exposing the street address."""
    parts = [item.city, item.state, item.zip_code]
    return ", ".join(part for part in parts if part)


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
    st.header(f"Owner-Finance Home in {location}")

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


def render_public_request(storage: Storage) -> bool:
    """Render a public route before the private password gate.

    Returns True when a public route was requested, even if the property is unavailable.
    """
    property_id = str(st.query_params.get("property", "")).strip()
    homes = str(st.query_params.get("homes", "")).strip().lower()

    if property_id:
        _render_property_detail(storage, property_id)
        return True
    if homes in {"1", "true", "yes"}:
        _render_portal(storage)
        return True
    return False
