from __future__ import annotations

from dataclasses import dataclass

import pytest

from cfh_disposition.public_competitor_collector import PublicCompetitorCollectionError, collect_public_competitor_page


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


def test_rejects_oversize_page() -> None:
    session = FakeSession([FakeResponse(404, "", {}), FakeResponse(200, "<html>too large</html>", {"Content-Type": "text/html"})])
    with pytest.raises(PublicCompetitorCollectionError, match="safe collection limit"):
        collect_public_competitor_page(url="https://example.com/page", market="Decatur, IL", source_name="Example", session=session, max_response_bytes=5)
