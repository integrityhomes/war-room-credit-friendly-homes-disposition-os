from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd
import streamlit as st

from .marketplace import build_meta_safe_marketplace_package, review_marketplace_copy
from .marketplace_calendar import (
    MARKETPLACE_MONTHLY_LIMIT,
    MarketplaceCalendarError,
    MarketplaceCalendarStore,
    MarketplaceListingType,
    close_marketplace_listing,
    marketplace_ledger_rows,
    marketplace_month_status,
    record_marketplace_listing,
)
from .models import OwnerFinanceProperty


def _property_options(
    properties: Sequence[OwnerFinanceProperty],
) -> dict[str, OwnerFinanceProperty]:
    return {item.display_address or str(item.property_id): item for item in properties}


def render_marketplace_guard(
    properties: Sequence[OwnerFinanceProperty],
    secrets: Mapping[str, Any],
) -> None:
    st.subheader("Facebook Marketplace Compliance & Monthly Safety Guard")
    st.caption(
        "One active Marketplace listing per property. Homes for Sale or Rent listings are capped "
        "at five per calendar month, including listings later deleted."
    )

    options = _property_options(properties)
    if not options:
        st.info("Add a property before preparing Marketplace copy.")
        return

    selected_name = st.selectbox(
        "Choose property",
        list(options),
        key="marketplace_property",
    )
    selected = options[selected_name]

    try:
        store = MarketplaceCalendarStore(secrets)
        ledger = store.load()
    except MarketplaceCalendarError as exc:
        st.error(
            "Facebook Marketplace ad creation is locked because the permanent monthly counter "
            f"could not be loaded: {exc}"
        )
        st.info(
            "This is a safety lock, not a broken ad generator. Restore the Supabase connection "
            "before the team creates another Marketplace listing."
        )
        return

    status = marketplace_month_status(ledger, property_id=selected.property_id)
    metric_columns = st.columns(3)
    metric_columns[0].metric("Used This Month", f"{status.used} / {MARKETPLACE_MONTHLY_LIMIT}")
    metric_columns[1].metric("Remaining", status.remaining)
    metric_columns[2].metric("Next Reset", status.reset_at.strftime("%b %d, %Y"))

    if status.blocked:
        st.error(status.message)
        st.info(
            "Marketplace ad copy is intentionally hidden until the counter resets so the team "
            "does not mistake the monthly limit for a system failure. Other marketing channels remain available."
        )
    elif status.active_duplicate:
        st.error(status.message)
        st.info(
            "Do not post the same house once under For Sale and again under For Rent. "
            "Use the existing listing or close it before preparing another listing."
        )
    else:
        st.success(status.message)
        if status.expected_listing_type:
            listing_type = status.expected_listing_type
            st.text_input(
                "Required category for the next different property",
                value=listing_type.value,
                disabled=True,
            )
            st.caption(
                "The system alternates different properties between For Sale and For Rent. "
                "The ad itself still clearly states that the monthly owner-finance payment is not rent."
            )
        else:
            listing_type = st.selectbox(
                "Facebook category for the first recorded listing",
                list(MarketplaceListingType),
                format_func=lambda value: value.value,
            )
            st.caption(
                "After the first listing, the system requires the opposite category for the next different property."
            )

        package = build_meta_safe_marketplace_package(selected)
        title = st.text_input("Marketplace title", value=package.title)
        description = st.text_area(
            "Marketplace description",
            value=package.description,
            height=360,
        )
        check = review_marketplace_copy(
            selected,
            title,
            description,
            listings_used_this_month=status.used,
        )

        if check.passed:
            st.success("Marketplace package passed the configured compliance checks.")
        else:
            st.error("Do not publish until these items are corrected:")
            for error in check.errors:
                st.write(f"- {error}")
        for warning in check.warnings:
            st.warning(warning)

        st.info(
            "No Dwelyx link or other website link is included in Facebook Marketplace copy. "
            "Buyers are instructed to message through Facebook Marketplace first."
        )

        operator = st.text_input(
            "Person creating the Facebook listing",
            value="Sabrina",
            key="marketplace_operator",
        )
        notes = st.text_area(
            "Optional Facebook listing ID or notes",
            key="marketplace_record_notes",
            height=80,
        )
        confirmed = st.checkbox(
            "I confirm this listing was actually created on Facebook Marketplace. "
            "Recording it permanently uses one monthly slot even if the listing is later deleted.",
            key="marketplace_created_confirmation",
        )
        if st.button(
            "Record Marketplace Listing Created",
            type="primary",
            disabled=not check.passed or not confirmed,
            use_container_width=True,
        ):
            try:
                ledger = record_marketplace_listing(
                    ledger,
                    property_id=selected.property_id,
                    address=selected.display_address,
                    listing_type=listing_type,
                    created_by=operator,
                    notes=notes,
                )
                store.save(ledger)
                refreshed = marketplace_month_status(
                    ledger,
                    property_id=selected.property_id,
                )
                st.success(
                    f"Marketplace listing recorded. {refreshed.used} of "
                    f"{MARKETPLACE_MONTHLY_LIMIT} monthly slots are now used."
                )
                st.rerun()
            except MarketplaceCalendarError as exc:
                st.error(str(exc))

    current_rows = marketplace_ledger_rows(ledger)
    st.write("### Marketplace listings created this month")
    if current_rows:
        st.dataframe(
            pd.DataFrame(current_rows),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No Marketplace listings have been recorded for the current calendar month.")

    active = [item for item in ledger.listings if item.active]
    if active:
        st.write("### Close an existing Marketplace listing")
        st.caption(
            "Closing or deleting a listing does not restore the monthly slot. This only prevents "
            "the system from treating the property as an active duplicate."
        )
        active_options = {
            f"{item.address} — {item.listing_type.value} — {item.created_at.date()}": item
            for item in active
        }
        active_name = st.selectbox(
            "Active listing",
            list(active_options),
            key="marketplace_active_listing",
        )
        close_operator = st.text_input(
            "Closed by",
            value="Sabrina",
            key="marketplace_close_operator",
        )
        if st.button("Mark Selected Listing Inactive or Sold"):
            try:
                ledger = close_marketplace_listing(
                    ledger,
                    listing_id=active_options[active_name].listing_id,
                    closed_by=close_operator,
                )
                store.save(ledger)
                st.success(
                    "Listing marked inactive. Its original monthly slot remains counted, as required by the safety counter."
                )
                st.rerun()
            except MarketplaceCalendarError as exc:
                st.error(str(exc))
