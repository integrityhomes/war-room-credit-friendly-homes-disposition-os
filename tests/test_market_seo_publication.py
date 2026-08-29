from pathlib import Path

from cfh_disposition.market_seo_public import market_page_path, market_slug

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
ADAPTER = ROOT / "supabase/functions/commandcore-market-seo/index.ts"
WORKFLOW = ROOT / ".github/workflows/deploy-commandcore-receiver.yml"


def test_market_slug_and_route_are_stable() -> None:
    assert market_slug("Virginia Beach", "VA") == "virginia-beach-va"
    assert market_page_path("Virginia Beach", "VA") == "?market=virginia-beach-va"


def test_public_market_route_runs_before_private_navigation() -> None:
    source = APP.read_text(encoding="utf-8")
    assert "render_market_seo_request" in source
    assert source.index("if render_market_seo_request(storage):") < source.index("pages = {")


def test_market_seo_adapter_points_to_public_route() -> None:
    source = ADAPTER.read_text(encoding="utf-8")
    assert 'const SEO_VERSION = "2026-08-29.1"' in source
    assert "public_market_pages_enabled: true" in source
    assert "page_route_contract" in source
    assert "page_path: `?market=${marketSlug}`" in source
    assert "external_action_started: false" in source


def test_deploy_validates_and_verifies_market_seo_contract() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Check market SEO adapter" in workflow
    assert "deno check supabase/functions/commandcore-market-seo/index.ts" in workflow
    assert "Verify live market SEO health contract" in workflow
    assert '"version":"2026-08-29.1"' in workflow
    assert '"public_market_pages_enabled":true' in workflow
