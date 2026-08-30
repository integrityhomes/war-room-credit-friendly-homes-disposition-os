from __future__ import annotations

from collections.abc import Callable
from typing import Any

import requests

from .agent_contact_finder import (
    AgentContactResult,
    AgentFinderError,
    AgentLookupRequest,
    build_agent_search_queries,
    normalize_agent_result,
)
from .agent_contact_parser import best_contact_values, extract_contact_candidates

SEARCHAPI_URL = "https://www.searchapi.io/api/v1/search"


SearchTransport = Callable[..., Any]


def _search_one(query: str, *, api_key: str, transport: SearchTransport) -> list[dict[str, Any]]:
    if not api_key.strip():
        raise AgentFinderError("Agent Finder is not connected yet. Add the SearchApi connection in CommandCore setup.")
    try:
        response = transport(
            SEARCHAPI_URL,
            params={
                "engine": "google",
                "q": query,
                "api_key": api_key,
                "num": 8,
                "gl": "us",
                "hl": "en",
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise AgentFinderError("Agent Finder could not reach the public-search provider.") from exc

    if int(getattr(response, "status_code", 0) or 0) != 200:
        raise AgentFinderError("Agent Finder's public-search provider returned an error. Try again later.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise AgentFinderError("Agent Finder received an unreadable response from the public-search provider.") from exc

    organic = payload.get("organic_results", []) if isinstance(payload, dict) else []
    if not isinstance(organic, list):
        return []
    return [
        {
            "title": str(item.get("title") or "").strip(),
            "snippet": str(item.get("snippet") or "").strip(),
            "link": str(item.get("link") or "").strip(),
            "query_used": query,
        }
        for item in organic
        if isinstance(item, dict)
    ]


def search_agent_contacts(
    request: AgentLookupRequest,
    *,
    api_key: str,
    transport: SearchTransport = requests.get,
) -> AgentContactResult:
    queries = build_agent_search_queries(request)
    search_results: list[dict[str, Any]] = []
    seen_links: set[str] = set()

    for query in queries:
        for result in _search_one(query, api_key=api_key, transport=transport):
            link = str(result.get("link") or "").strip()
            normalized = link.rstrip("/").casefold()
            if normalized and normalized in seen_links:
                continue
            if normalized:
                seen_links.add(normalized)
            search_results.append(result)

    candidates = extract_contact_candidates(
        search_results,
        agent_name=request.agent_name,
        brokerage=request.brokerage,
        city=request.city,
        state=request.state,
    )
    best = best_contact_values(candidates)
    strongest_score = max((candidate.score for candidate in candidates), default=0)
    source_links = tuple(
        dict.fromkeys(candidate.source_link for candidate in candidates if candidate.source_link)
    )

    raw = {
        "agent_name": request.agent_name,
        "brokerage": request.brokerage,
        "best_phone": best["phone"],
        "best_email": best["email"],
        "source_links": source_links,
        "confidence_score": max(0, min(strongest_score, 100)),
    }
    result = normalize_agent_result(raw)
    if not search_results:
        return AgentContactResult(
            agent_name=request.agent_name,
            brokerage=request.brokerage,
            phone="",
            email="",
            brokerage_phone="",
            website="",
            facebook_url="",
            linkedin_url="",
            source_links=(),
            confidence_score=0,
            status="No public match found",
            next_action="Check the agent name, city, or brokerage and try again.",
        )
    return result
