from __future__ import annotations

from dataclasses import dataclass

import pytest

from cfh_disposition.public_competitor_collector import (
    PublicCompetitorCollectionError,
    collect_public_competitor_page,
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

    def get(self, url: str, **kwargs):  # noqa: ANN003, ANN201
        del url, kwargs
        return self.responses.pop(0)


def test_collector_blocks_robots_disallow() -> None:
    session = FakeSession([FakeResponse(200, "User-agent: *\nDisallow: /\n", {"Content-Type": "text/plain"})])
    with pytest.raises(PublicCompetitorCollectionError, match="robots policy"):
        collect_public_competitor_page(
            url="https://example.com/landing",
            market="Peoria, IL",
            source_name="Example",
            session=session,
        )


def test_collector_rejects_non_html() -> None:
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
