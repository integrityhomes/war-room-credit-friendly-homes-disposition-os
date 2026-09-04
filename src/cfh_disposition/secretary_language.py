"""Deterministic language handling for the test-mode bilingual Secretary.

This module deliberately performs no translation and makes no network calls.  The
original customer text remains authoritative; an English VA summary can only be
supplied by the caller as a separate, non-authoritative field.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SecretaryLanguage(StrEnum):
    ENGLISH = "English"
    SPANISH = "Spanish"
    UNCERTAIN = "Uncertain"


class LanguageAssessment(BaseModel):
    """Language evidence and safe preference state for one inbound turn."""

    model_config = ConfigDict(frozen=True)

    original_text: str
    detected_language: SecretaryLanguage
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: tuple[str, ...]
    established_preferred_language: SecretaryLanguage | None = None
    preferred_language: SecretaryLanguage | None = None
    preference_changed: bool = False
    english_va_summary: str | None = None
    spanish_automated_outbound_authorized: bool = False

    @field_validator("established_preferred_language", "preferred_language")
    @classmethod
    def _preference_must_be_known(
        cls, value: SecretaryLanguage | None
    ) -> SecretaryLanguage | None:
        if value is SecretaryLanguage.UNCERTAIN:
            raise ValueError("A preferred language must be English or Spanish")
        return value


_SPANISH_MARKERS = {
    "buenas",
    "busco",
    "casa",
    "comprar",
    "cuando",
    "cuanto",
    "donde",
    "espanol",
    "financiamiento",
    "gracias",
    "hola",
    "informacion",
    "mensual",
    "necesito",
    "precio",
    "propiedad",
    "quiero",
    "tiene",
    "vendedor",
}
_ENGLISH_MARKERS = {
    "buy",
    "buyer",
    "down",
    "financing",
    "hello",
    "home",
    "house",
    "information",
    "interested",
    "monthly",
    "need",
    "payment",
    "price",
    "property",
    "seller",
    "thanks",
    "want",
    "when",
    "where",
}
_SPANISH_FUNCTION_WORDS = {
    "como",
    "con",
    "cual",
    "de",
    "el",
    "en",
    "esta",
    "la",
    "me",
    "para",
    "por",
    "que",
    "una",
}
_ENGLISH_FUNCTION_WORDS = {
    "and",
    "are",
    "for",
    "how",
    "is",
    "of",
    "the",
    "this",
    "to",
    "what",
    "with",
    "you",
}
_TOKEN_PATTERN = re.compile(r"[^\W\d_]+", flags=re.UNICODE)


def _coerce_preference(
    value: SecretaryLanguage | str | None,
) -> SecretaryLanguage | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        language = SecretaryLanguage(value)
    except ValueError as exc:
        raise ValueError("Preferred language must be English or Spanish") from exc
    if language is SecretaryLanguage.UNCERTAIN:
        raise ValueError("Preferred language must be English or Spanish")
    return language


def detect_secretary_language(
    original_text: str,
    *,
    established_preferred_language: SecretaryLanguage | str | None = None,
    english_va_summary: str | None = None,
) -> LanguageAssessment:
    """Detect English/Spanish and transition preference without guessing.

    Numbers do not contribute language evidence.  Ambiguous turns retain an
    established preference.  A new preference or language switch requires at
    least two deterministic signals, except for unmistakable Spanish
    punctuation/diacritics combined with a Spanish word.
    """

    if not isinstance(original_text, str):
        raise TypeError("original_text must be a string")
    established = _coerce_preference(established_preferred_language)
    normalized = original_text.casefold()
    tokens = _TOKEN_PATTERN.findall(normalized)

    spanish_terms = sorted(
        {token for token in tokens if token in _SPANISH_MARKERS | _SPANISH_FUNCTION_WORDS}
    )
    english_terms = sorted(
        {token for token in tokens if token in _ENGLISH_MARKERS | _ENGLISH_FUNCTION_WORDS}
    )
    spanish_orthography = bool(re.search(r"[¿¡áéíóúüñ]", normalized))
    spanish_score = len(spanish_terms) + (1 if spanish_orthography else 0)
    english_score = len(english_terms)

    evidence: list[str] = []
    if spanish_terms:
        evidence.append(f"Spanish language markers: {', '.join(spanish_terms)}")
    if english_terms:
        evidence.append(f"English language markers: {', '.join(english_terms)}")
    if spanish_orthography:
        evidence.append("Spanish punctuation or diacritics detected")

    lead = abs(spanish_score - english_score)
    strongest = max(spanish_score, english_score)
    sufficient = strongest >= 2 and lead >= 2
    if sufficient and spanish_score > english_score:
        detected = SecretaryLanguage.SPANISH
    elif sufficient and english_score > spanish_score:
        detected = SecretaryLanguage.ENGLISH
    else:
        detected = SecretaryLanguage.UNCERTAIN
        evidence.append("Not enough unambiguous language evidence")

    confidence = 0.0
    if detected is not SecretaryLanguage.UNCERTAIN:
        confidence = min(0.99, 0.65 + (0.08 * lead) + (0.03 * strongest))
    elif strongest:
        confidence = min(0.49, 0.15 + (0.08 * lead))

    preferred = detected if detected is not SecretaryLanguage.UNCERTAIN else established
    changed = preferred is not None and preferred != established

    return LanguageAssessment(
        original_text=original_text,
        detected_language=detected,
        confidence=round(confidence, 2),
        evidence=tuple(evidence),
        established_preferred_language=established,
        preferred_language=preferred,
        preference_changed=changed,
        english_va_summary=english_va_summary,
        # Spanish outbound remains blocked until compliance-equivalence work is approved.
        spanish_automated_outbound_authorized=False,
    )


def resolve_preferred_language(
    original_text: str,
    established_preferred_language: SecretaryLanguage | str | None = None,
) -> SecretaryLanguage | None:
    """Convenience wrapper for consumers that only need the preference result."""

    return detect_secretary_language(
        original_text,
        established_preferred_language=established_preferred_language,
    ).preferred_language
