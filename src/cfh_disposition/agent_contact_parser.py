from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

PHONE_PATTERN = re.compile(
    r"(?:\+?1[\s.\-]?)?\(?(?P<area>\d{3})\)?[\s.\-]*(?P<prefix>\d{3})[\s.\-]*(?P<line>\d{4})"
)
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")


@dataclass(frozen=True, slots=True)
class ContactCandidate:
    kind: str
    value: str
    source_link: str
    score: int


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_phone(match: re.Match[str]) -> str:
    return f"({match.group('area')}) {match.group('prefix')}-{match.group('line')}"


def _result_text(result: dict[str, Any]) -> str:
    return " ".join(
        [
            _text(result.get("title")),
            _text(result.get("snippet")),
            _text(result.get("link")),
        ]
    )


def _name_parts(agent_name: str) -> tuple[str, ...]:
    ignored = {"jr", "sr", "ii", "iii", "iv", "realtor", "agent"}
    return tuple(
        part
        for part in re.findall(r"[A-Za-z0-9]+", agent_name.casefold())
        if len(part) >= 3 and part not in ignored
    )


def _brokerage_parts(brokerage: str) -> tuple[str, ...]:
    ignored = {
        "realty",
        "realtor",
        "realtors",
        "properties",
        "property",
        "management",
        "group",
        "company",
        "services",
        "service",
        "team",
        "llc",
        "inc",
        "corp",
        "corporation",
        "the",
        "and",
    }
    cleaned = brokerage.replace("/", " ").replace("&", " ").casefold()
    return tuple(
        part
        for part in re.findall(r"[A-Za-z0-9]+", cleaned)
        if len(part) >= 4 and part not in ignored
    )


def relevance_score(
    result: dict[str, Any],
    *,
    agent_name: str,
    brokerage: str,
    city: str,
    state: str,
) -> int:
    text = _result_text(result).casefold()
    link = _text(result.get("link")).casefold()
    score = 0

    full_name = agent_name.casefold().strip()
    full_brokerage = brokerage.casefold().strip()
    if full_name and full_name in text:
        score += 60
    score += 12 * sum(1 for part in _name_parts(agent_name) if part in text)
    if full_brokerage and full_brokerage in text:
        score += 35
    score += 8 * sum(1 for part in _brokerage_parts(brokerage) if part in text)
    if city.casefold().strip() and city.casefold().strip() in text:
        score += 12
    if state.casefold().strip() and state.casefold().strip() in text:
        score += 6

    trusted = (
        "zillow.com",
        "remax.com",
        "realtor.com",
        "homes.com",
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
    if any(domain in link for domain in trusted):
        score += 15
    if any(domain in link for domain in discouraged):
        score -= 35
    if any(term in text for term in ("email list", "agent database", "lead list", "bulk data", "data broker")):
        score -= 40
    return score


def _email_matches_agent(email: str, agent_name: str, brokerage: str, source_link: str) -> bool:
    if "@" not in email:
        return False
    username, domain = email.casefold().split("@", 1)
    if domain in {"example.com", "sentry.io", "google.com", "gmailusercontent.com", "wixpress.com"}:
        return False

    source_domain = urlparse(source_link).netloc.casefold().removeprefix("www.")
    name_parts = _name_parts(agent_name)
    brokerage_parts = _brokerage_parts(brokerage)
    name_match = any(part in username for part in name_parts)
    brokerage_match = any(part in username or part in domain for part in brokerage_parts)
    source_match = bool(source_domain and (domain == source_domain or source_domain.endswith(f".{domain}")))
    return name_match or brokerage_match or source_match


def extract_contact_candidates(
    results: list[dict[str, Any]],
    *,
    agent_name: str,
    brokerage: str,
    city: str,
    state: str,
) -> tuple[ContactCandidate, ...]:
    candidates: dict[tuple[str, str], ContactCandidate] = {}
    for result in results:
        source_link = _text(result.get("link"))
        base_score = relevance_score(
            result,
            agent_name=agent_name,
            brokerage=brokerage,
            city=city,
            state=state,
        )
        text = _result_text(result)

        for match in PHONE_PATTERN.finditer(text):
            value = _normalize_phone(match)
            key = ("phone", value)
            candidate = ContactCandidate("phone", value, source_link, base_score)
            if key not in candidates or candidate.score > candidates[key].score:
                candidates[key] = candidate

        for email in EMAIL_PATTERN.findall(text):
            normalized = email.casefold()
            if not _email_matches_agent(normalized, agent_name, brokerage, source_link):
                continue
            key = ("email", normalized)
            candidate = ContactCandidate("email", normalized, source_link, base_score)
            if key not in candidates or candidate.score > candidates[key].score:
                candidates[key] = candidate

    return tuple(sorted(candidates.values(), key=lambda candidate: candidate.score, reverse=True))


def best_contact_values(candidates: tuple[ContactCandidate, ...]) -> dict[str, str]:
    phone = next((candidate.value for candidate in candidates if candidate.kind == "phone"), "")
    email = next((candidate.value for candidate in candidates if candidate.kind == "email"), "")
    return {"phone": phone, "email": email}
