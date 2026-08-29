from __future__ import annotations

from uuid import UUID

import streamlit as st

from .campaign_launch import (
    campaign_slug,
    CampaignLaunchStore,
    LaunchStatus,
    LaunchStoreError,
)
from .channel_tracking import build_channel_links
from .dwelyx import dwelyx_base_url, tracking_app_base_url
from .owned_web_channels import OwnedWebPackageError, build_owned_web_package
from .public_pages import is_public_property
from .storage import Storage, StorageError


PUBLISHABLE_BLOG_STATUSES = {
    LaunchStatus.READY,
    LaunchStatus.SCHEDULED,
    LaunchStatus.POSTED,
}


def blog_page_path(property_id: UUID | str, campaign: str = "owner_finance_homes") -> str:
    return f"?blog={property_id}&campaign={campaign_slug(campaign)}"


def _approved_blog_state(property_id: UUID | str, campaign: str):
    try:
        state = CampaignLaunchStore(st.secrets).load(property_id, campaign)
    except LaunchStoreError:
        return None
    if state is None or state.approved_at is None:
        return None
    blog = state.channels.get("blog")
    if blog is None or blog.status not in PUBLISHABLE_BLOG_STATUSES:
        return None
    return state


def render_blog_request(storage: Storage) -> bool:
    requested = str(st.query_params.get("blog", "")).strip()
    if not requested:
        return False

    campaign = campaign_slug(str(st.query_params.get("campaign", "owner_finance_homes")))
    try:
        properties = storage.list_properties()
    except StorageError:
        properties = []
    property_ = next((item for item in properties if str(item.property_id) == requested), None)

    state = _approved_blog_state(requested, campaign) if property_ is not None else None
    if property_ is None or not is_public_property(property_) or state is None:
        st.set_page_config(
            page_title="Credit Friendly Homes Blog",
            page_icon="🏠",
            layout="wide",
        )
        st.title("Credit Friendly Homes")
        st.warning("This article is not available for public viewing.")
        st.caption(
            "Blog content is only published after the property is public and the saved campaign approval is verified."
        )
        return True

    links = build_channel_links(
        dwelyx_base_url(st.secrets),
        campaign=campaign,
        property_id=property_.property_id,
        tracking_base_url=tracking_app_base_url(st.secrets),
    )
    tracked_link = next(
        row["Tracked Dwelyx link"] for row in links if row["Channel key"] == "blog"
    )
    try:
        package = build_owned_web_package(
            property_,
            channel_key="blog",
            channel_name="Owner-Finance Blog",
            tracked_link=tracked_link,
        )
    except OwnedWebPackageError:
        st.set_page_config(
            page_title="Credit Friendly Homes Blog",
            page_icon="🏠",
            layout="wide",
        )
        st.title("Credit Friendly Homes")
        st.warning(
            "This article is temporarily unavailable because its verified property facts are incomplete."
        )
        return True

    st.set_page_config(page_title=package.title, page_icon="🏠", layout="wide")
    st.caption("Credit Friendly Homes · Owner-Finance Education")
    st.title(package.headline)
    st.write(package.body)
    st.link_button(package.call_to_action, package.tracked_link, type="primary")
    st.caption(
        "Property availability and terms can change. This educational content does not guarantee approval. "
        "Equal Housing Opportunity."
    )
    st.caption(
        f"Campaign approved by {state.approved_by or 'authorized operator'} on "
        f"{state.approved_at.strftime('%Y-%m-%d %H:%M UTC')}."
    )
    return True
