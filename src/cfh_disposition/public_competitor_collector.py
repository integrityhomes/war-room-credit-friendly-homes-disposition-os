# ruff: noqa: I001
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from .marketing_intelligence import IntelligenceSurface, MarketObservation


USER_AGENT = "CommandCoreMarketingResearch/1.0"
MAX_RESPONSE_BYTES = 500_000
CTA_TERMS = (
    "get started",
    "learn more",
    "contact",
    "apply",
    "get offer",
    "request offer",
    "see homes",
    "view homes",
    "schedule",
    "call now",
)


class PublicCompetitorCollectionError(RuntimeError):
    """Raised when a public competitor page cannot be collected safely."""


@dataclass(frozen=True, slots=True)
class ParsedPublicPage:
    title: str
    headings: tuple[str, ...]
    calls_to_action: tuple[str, ...]


class _PageSignalsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capture: str = ""
        self._buffer: list[str] = []
        self.title = ""
        self.headings: list[str] = []
        self.calls_to_action: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"title", "h1", "h2", "a", "button"}:
            self._capture = tag
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != self._capture:
            return
        value = " ".join(" ".join(self._buffer).split())
        if value:
            if tag == "title" and not self.title:
                self.title = value[:500]
            elif tag in {"h1", "h2"} and len(self.headings) < 12:
                self.headings.append(value[:500])
            elif tag in {"a", "button"}:
                normalized = value.lower()
                if any(term in normalized for term in CTA_TERMS) and value not in self.calls_to_action:
                    self.calls_to_action.append(value[:120])
        self._capture = ""
        self._buffer = []


def parse_public_page(html: str) -> ParsedPublicPage:
    parser = _PageSignalsParser()
    parser.feed(html)
    return ParsedPublicPage(
        title=parser.title,
        headings=tuple(parser.headings),
        calls_to_action=tuple(parser.calls_to_action[:6]),
    )


def _validated_url(url: str) -> str:
    candidate = str(url or "").strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PublicCompetitorCollectionError("A valid public http/https competitor URL is required.")
    return candidate


def _robots_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


def _robots_allows(session: requests.Session, url: str, *, timeout: float) -> bool:
    try:
        response = session.get(
            _robots_url(url),
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise PublicCompetitorCollectionError("Could not verify the site's robots policy.") from exc

    if response.status_code == 404:
        return True
    if response.status_code >= 400:
        raise PublicCompetitorCollectionError("Could not safely verify the site's robots policy.")

    parser = RobotFileParser()
    parser.parse(response.text.splitlines())
    return parser.can_fetch(USER_AGENT, url)


def _surface_for_url(url: str, requested: IntelligenceSurface | None) -> IntelligenceSurface:
    if requested is not None:
        return requested
    path = urlparse(url).path.lower()
    if any(token in path for token in ("/blog", "/news", "/article", "/resources")):
        return IntelligenceSurface.BLOG
    return IntelligenceSurface.LANDING_PAGE


def collect_public_competitor_page(
    *,
    url: str,
    market: str,
    source_name: str,
    surface: IntelligenceSurface | None = None,
    session: requests.Session | None = None,
    timeout: float = 10.0,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
) -> MarketObservation:
    """Collect bounded public-page patterns without copying article or creative bodies."""

    target = _validated_url(url)
    client = session or requests.Session()
    if not _robots_allows(client, target, timeout=timeout):
        raise PublicCompetitorCollectionError("The site's robots policy does not permit this automated collection.")

    try:
        response = client.get(
            target,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise PublicCompetitorCollectionError("The public competitor page could not be reached.") from exc

    if response.status_code >= 400:
        raise PublicCompetitorCollectionError(f"The public competitor page returned HTTP {response.status_code}.")
    content_type = str(response.headers.get("Content-Type", "")).lower()
    if "text/html" not in content_type:
        raise PublicCompetitorCollectionError("The public competitor URL is not an HTML page.")
    if len(response.content) > max_response_bytes:
        raise PublicCompetitorCollectionError("The public competitor page is larger than the safe collection limit.")

    parsed = parse_public_page(response.text)
    headline = parsed.title or (parsed.headings[0] if parsed.headings else "Public competitor page")
    heading_sample = parsed.headings[:4]
    cta_sample = parsed.calls_to_action[:3]
    pattern_parts = []
    if parsed.title:
        pattern_parts.append("clear page title")
    if parsed.headings:
        pattern_parts.append(f"{len(parsed.headings)} prominent headings")
    if parsed.calls_to_action:
        pattern_parts.append(f"{len(parsed.calls_to_action)} visible action prompts")

    return MarketObservation(
        surface=_surface_for_url(target, surface),
        market=str(market or "Unknown market").strip(),
        source_name=str(source_name or urlparse(target).netloc).strip(),
        source_url=target,
        headline_or_topic=headline[:500],
        hook=" | ".join(heading_sample)[:500],
        call_to_action=" | ".join(cta_sample)[:300],
        keyword_or_intent=" | ".join(heading_sample)[:300],
        landing_page_pattern=", ".join(pattern_parts)[:500],
        evidence_note=(
            "Automatically observed public page metadata, headings, and short action-label patterns only. "
            "No article body or protected creative was copied; public visibility is not evidence of performance."
        ),
    )
