from __future__ import annotations

import re
from collections.abc import Sequence

import streamlit as st

from .dwelyx import build_dwelyx_url, dwelyx_base_url, tracking_app_base_url
from .models import OwnerFinanceProperty
from .public_pages import is_public_property, money, public_location, public_property_path
from .storage import Storage, StorageError


def market_slug(city: str, state: str) -> str:
    raw = f"{city}-{state}".strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:120]


def market_page_path(city: str, state: str) -> str:
    return f"?market={market_slug(city, state)}"


def public_market_properties(
    properties: Sequence[OwnerFinanceProperty],
    slug: str,
) -> list[OwnerFinanceProperty]:
    normalized = str(slug or "").strip().lower()
    return [
        item
        for item in properties
        if is_public_property(item) and market_slug(item.city, item.state) == normalized
    ]


def _market_dwelyx_link(city: str, state: str) -> str:
    campaign = f"market_seo_{market_slug(city, state)}"
    return build_dwelyx_url(
        dwelyx_base_url(st.secrets),
        source="credit_friendly_homes",
        medium="market_seo",
        campaign=campaign,
        tracking_base_url=tracking_app_base_url(st.secrets),
    )


def render_market_seo_request(storage: Storage) -> bool:
    requested = str(st.query_params.get("market", "")).strip().lower()
    if not requested:
        return False

    try:
        properties = storage.list_properties()
    except StorageError:
        properties = []

    matches = public_market_properties(properties, requested)
    if not matches:
        st.set_page_config(
            page_title="Owner-Finance Homes | Credit Friendly Homes",
            page_icon="🏠",
            layout="wide",
        )
        st.title("Credit Friendly Homes")
        st.warning("No public owner-finance homes are currently available in this market.")
        st.markdown("[Browse current featured homes](?homes=1)")
        st.caption("Availability and terms are subject to verification. Equal Housing Opportunity.")
        return True

    city = matches[0].city
    state = matches[0].state.upper()
    location = f"{city}, {state}"
    st.set_page_config(
        page_title=f"Owner Financing Homes in {location} | Credit Friendly Homes",
        page_icon="🏠",
        layout="wide",
    )
    st.title(f"Owner Financing Homes in {location}")
    st.caption(
        f"Explore current Credit Friendly Homes owner-finance opportunities in {location}. "
        "Inventory, pricing, down payments, and monthly payments can change, so verify current terms before acting."
    )
    st.link_button(
        f"Browse all owner-finance homes for {location} on Dwelyx",
        _market_dwelyx_link(city, state),
        type="primary",
        use_container_width=True,
    )

    st.subheader(f"Current featured homes in {location}")
    columns = st.columns(3)
    for index, item in enumerate(matches):
        with columns[index % 3]:
            if item.photo_urls:
                st.image(str(item.photo_urls[0]), use_container_width=True)
            st.markdown(f"### {public_location(item)}")
            details = []
            if item.bedrooms is not None:
                details.append(f"{item.bedrooms} bed")
            if item.bathrooms is not None:
                details.append(f"{item.bathrooms:g} bath")
            if details:
                st.write(" · ".join(details))
            st.write(f"Purchase price: **{money(item.total_price)}**")
            st.write(f"Down payment: **{money(item.down_payment)}**")
            st.write(f"Monthly payment: **{money(item.monthly_payment)}**")
            st.markdown(f"[View property details]({public_property_path(item.property_id)})")
            st.divider()

    st.subheader(f"How owner financing works in {location}")
    st.write(
        "Owner-financing opportunities can give buyers another way to purchase a home when a traditional "
        "mortgage is not the right fit. Each property has its own verified terms and availability. Review the "
        "specific property details, ask questions, and use Dwelyx for the current buyer process and next steps."
    )
    st.caption(
        "This page is advertising and educational content, not a promise of buyer approval. "
        "Terms and availability are subject to verification. Equal Housing Opportunity."
    )
    return True
