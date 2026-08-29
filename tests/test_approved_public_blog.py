from pathlib import Path

from cfh_disposition.blog_public import PUBLISHABLE_BLOG_STATUSES, blog_page_path
from cfh_disposition.campaign_launch import LaunchStatus

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
BLOG = ROOT / "src/cfh_disposition/blog_public.py"


def test_blog_route_is_stable_and_campaign_scoped() -> None:
    assert blog_page_path("property-123") == "?blog=property-123&campaign=owner_finance_homes"


def test_blog_publication_requires_persisted_campaign_approval() -> None:
    source = BLOG.read_text(encoding="utf-8")
    assert "CampaignLaunchStore(st.secrets).load" in source
    assert "state.approved_at is None" in source
    assert 'state.channels.get("blog")' in source
    assert "blog.status not in PUBLISHABLE_BLOG_STATUSES" in source
    assert "is_public_property(property_)" in source
    assert PUBLISHABLE_BLOG_STATUSES == {
        LaunchStatus.READY,
        LaunchStatus.SCHEDULED,
        LaunchStatus.POSTED,
    }


def test_blog_uses_fact_locked_owned_web_builder_and_tracked_link() -> None:
    source = BLOG.read_text(encoding="utf-8")
    assert "build_owned_web_package" in source
    assert 'channel_key="blog"' in source
    assert "build_channel_links" in source
    assert 'row["Channel key"] == "blog"' in source


def test_blog_route_runs_before_private_navigation() -> None:
    source = APP.read_text(encoding="utf-8")
    assert "render_blog_request" in source
    assert source.index("if render_blog_request(storage):") < source.index("pages = {")


def test_blog_route_cannot_publish_without_approval() -> None:
    source = BLOG.read_text(encoding="utf-8")
    approval_check = source.index("state.approved_at is None")
    render_title = source.index("st.set_page_config(page_title=package.title")
    assert approval_check < render_title
