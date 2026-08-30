from __future__ import annotations

from dataclasses import dataclass

import pytest

from cfh_disposition.marketing_intelligence import IntelligenceSurface
from cfh_disposition.public_competitor_collector import (
    PublicCompetitorCollectionError,
    collect_public_competitor_page,
    parse_public_page,
)


@dataclass
class FakeResponse:
    status_code: int
    text: str
    headers: dict[str, str]

    @property
    def content(self) -> bytes:
        return self.text.encode()


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    def get(self, url: str, **kwargs):  # noqa: ANN003, ANN201
        del kwargs
        self.calls.append(url)
        return self.responses.pop(0)


def test_parse_public_page_keeps_short_signals_not_article_body() -> None:
    parsed = parse_public_page(
        """
        <html><head><title>Sell Your House Fast</title></head>
        <body>
          <h1>Need to sell in Decatur?</h1>
          <h2>Simple cash offer process</h2>
          <p>This is a long article body that should never be returned.</p>
          <a href='/offer'>Get Offer Today</a>
        </body></html>
        """
    )
    assert parsed.title == "Sell Your House Fast"
    assert parsed.headings == ("Need to sell in Decatur?", "Simple cash offer process")
    assert parsed.calls_to_action == ("Get Offer Today",)


def test_collect_public_competitor_page_respects_robots_and_builds_observation() -> None:
    session = FakeSession(
        [
            FakeResponse(200, "User-agent: *\nAllow: /\n", {"Content-Type": "text/plain"}),
            FakeResponse(
                200,
                "<html><head><title>Owner Financing Homes</title></head>"
                "<body><h1>Homes with flexible terms</h1><a>See Homes</a></body></html>",
                {"Content-Type": "text/html; charset=utf-8"},
            ),
        ]
    )
    observation = collect_public_competitor_page(
        url="https://example.com/blog/owner-financing",
        market="Decatur, IL",
        source_name="Example Homes",
        session=session,
    )
    assert observation.surface == IntelligenceSurface.BLOG
    assert observation.market == "Decatur, IL"
    assert observation.headline_or_topic == "Owner Financing Homes"
    assert "Homes with flexible terms" in observation.hook
    assert observation.call_to_action == "See Homes"
    assert "No article body" in observation.evidence_note
    assert session.calls[0] == "https://example.com/robots.txt"


def test_collect_public_competitor_page_blocks_disallowed_robots() -> None:
    session = FakeSession(
        [FakeResponse(200, "User-agent: *\nDisallow: /\n", {"Content-Type": "text/plain"})]
    )
    with pytest.raises(PublicCompetitorCollectionError, match="robots policy"):
        collect_public_competitor_page(
            url="https://example.com/landing",
            market="Peoria, IL",
            source_name="Example",
            session=session,
        )
    assert session.calls == ["https://example.com/robots.txt"]


def test_collect_public_competitor_page_rejects_non_html() -> None:
    session = FakeSession(
        [
            FakeResponse(404, "", {}),
            FakeResponse(200, "%PDF", {"Content-Type": "application/pdf"}),
        ]
    )
    with pytest.raises(PublicCompetitorCollectionError, match="not an HTML page"):
        collect_public_competitor_page(
            url="https://example.com/report.pdf",
            market="Rockford, IL",
            source_name="Example",
            session=session,
        )
