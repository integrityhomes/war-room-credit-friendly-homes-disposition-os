from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


class AgentFinderError(RuntimeError):
    """Raised when CommandCore cannot safely run an agent lookup."""


@dataclass(frozen=True, slots=True)
class AgentLookupRequest:
    agent_name: str
    city: str
    state: str
    brokerage: str = ""
    property_address: str = ""
    listing_url: str = ""


@dataclass(frozen=True, slots=True)
class AgentContactResult:
    agent_name: str
    brokerage: str
    phone: str
    email: str
    brokerage_phone: str
    website: str
    facebook_url: str
    linkedin_url: str
    source_links: tuple[str, ...]
    confidence_score: int
    status: str
    next_action: str


def _text(value: Any) -> str:
    return str(value or "").strip()


def validate_lookup_request(request: AgentLookupRequest) -> None:
    if not request.agent_name.strip():
        raise AgentFinderError("Enter the agent name before searching.")
    if not request.city.strip():
        raise AgentFinderError("Enter the city before searching.")
    if not request.state.strip():
        raise AgentFinderError("Enter the state before searching.")


def build_agent_search_queries(request: AgentLookupRequest) -> tuple[str, ...]:
    validate_lookup_request(request)
    name = request.agent_name.strip()
    city = request.city.strip()
    state = request.state.strip()
    brokerage = request.brokerage.strip()
    location = f"{city}, {state}"
    queries: list[str] = []

    if request.property_address.strip():
        address = request.property_address.strip()
        queries.extend(
            [
                f'"{address}" "{name}" realtor',
                f'site:zillow.com "{address}" "{name}"',
            ]
        )
    if request.listing_url.strip():
        queries.append(f'"{request.listing_url.strip()}" "{name}"')
    if brokerage:
        queries.extend(
            [
                f'"{name}" "{brokerage}" phone email',
                f'"{name}" "{brokerage}" contact',
            ]
        )
    queries.extend(
        [
            f'"{name}" "{location}" realtor phone',
            f'"{name}" "{location}" realtor email',
            f'"{name}" "{location}" real estate agent contact',
            f'site:realtor.com "{name}" "{location}"',
            f'site:homes.com "{name}" "{location}"',
            f'site:linkedin.com/in "{name}" real estate',
        ]
    )
    return tuple(dict.fromkeys(queries))


def dedupe_source_links(links: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    output: list[str] = []
    for raw in links:
        link = _text(raw)
        if not link:
            continue
        normalized = link.rstrip("/").casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        output.append(link)
    return tuple(output)


def trusted_source_score(link: str) -> int:
    host = urlparse(_text(link)).netloc.casefold()
    trusted = (
        "zillow.com",
        "realtor.com",
        "homes.com",
        "remax.com",
        "coldwellbanker.com",
        "century21.com",
        "kw.com",
        "kellerwilliams.com",
        "compass.com",
        "bhhs.com",
        "redfin.com",
        "linkedin.com",
    )
    discouraged = ("zoominfo.com", "apollo.io", "rocketreach.co")
    if any(domain in host for domain in discouraged):
        return -25
    if any(domain in host for domain in trusted):
        return 15
    return 0


def normalize_agent_result(raw: dict[str, Any]) -> AgentContactResult:
    sources = dedupe_source_links(tuple(raw.get("source_links") or ()))
    confidence = int(raw.get("confidence_score") or 0)
    confidence += sum(trusted_source_score(link) for link in sources)
    confidence = max(0, min(confidence, 100))
    phone = _text(raw.get("best_phone") or raw.get("phone"))
    email = _text(raw.get("best_email") or raw.get("email"))

    if confidence >= 75 and (phone or email):
        status = "Strong match"
        next_action = "Verify the contact details before outreach."
    elif confidence >= 45 and (phone or email):
        status = "Possible match"
        next_action = "Review the sources and verify the contact details before outreach."
    else:
        status = "Needs verification"
        next_action = "No high-confidence public contact was confirmed. Verify manually before outreach."

    return AgentContactResult(
        agent_name=_text(raw.get("agent_name")),
        brokerage=_text(raw.get("brokerage")),
        phone=phone,
        email=email,
        brokerage_phone=_text(raw.get("brokerage_phone")),
        website=_text(raw.get("agent_website") or raw.get("website")),
        facebook_url=_text(raw.get("facebook_url")),
        linkedin_url=_text(raw.get("linkedin_url")),
        source_links=sources,
        confidence_score=confidence,
        status=status,
        next_action=next_action,
    )


def connection_requirements() -> dict[str, str]:
    return {
        "SEARCHAPI_API_KEY": "Required to search public web results through SearchApi.io.",
        "OPENAI_API_KEY": "Optional for AI-assisted extraction; deterministic validation should remain available.",
    }
