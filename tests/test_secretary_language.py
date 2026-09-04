import pytest
from pydantic import ValidationError

from cfh_disposition.secretary_language import (
    LanguageAssessment,
    SecretaryLanguage,
    detect_secretary_language,
    resolve_preferred_language,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello, I am interested in this house", SecretaryLanguage.ENGLISH),
        ("Hola, necesito información de esta casa", SecretaryLanguage.SPANISH),
        ("¿Cuánto es el pago mensual?", SecretaryLanguage.SPANISH),
    ],
)
def test_detects_supported_languages_deterministically(
    text: str, expected: SecretaryLanguage
) -> None:
    result = detect_secretary_language(text)

    assert result.detected_language is expected
    assert result.preferred_language is expected
    assert result.confidence >= 0.65
    assert result.evidence


@pytest.mark.parametrize("text", ["OK", "123 Main St", "$1,250", "Maria", ""])
def test_ambiguous_turn_preserves_established_preference(text: str) -> None:
    result = detect_secretary_language(
        text, established_preferred_language=SecretaryLanguage.SPANISH
    )

    assert result.original_text == text
    assert result.detected_language is SecretaryLanguage.UNCERTAIN
    assert result.preferred_language is SecretaryLanguage.SPANISH
    assert not result.preference_changed


def test_strong_language_evidence_can_switch_preference() -> None:
    result = detect_secretary_language(
        "I need information about the property",
        established_preferred_language=SecretaryLanguage.SPANISH,
    )

    assert result.detected_language is SecretaryLanguage.ENGLISH
    assert result.preferred_language is SecretaryLanguage.ENGLISH
    assert result.preference_changed


def test_weak_mixed_evidence_does_not_switch_preference() -> None:
    result = detect_secretary_language(
        "Hola property", established_preferred_language=SecretaryLanguage.ENGLISH
    )

    assert result.detected_language is SecretaryLanguage.UNCERTAIN
    assert result.preferred_language is SecretaryLanguage.ENGLISH
    assert not result.preference_changed


def test_original_text_and_caller_supplied_va_summary_remain_separate() -> None:
    original = "  ¿Cuál es el precio de $125,000?  "
    summary = "Customer asked about the listed price. Verify it in inventory."

    result = detect_secretary_language(original, english_va_summary=summary)

    assert result.original_text == original
    assert result.english_va_summary == summary
    assert "$125,000" in result.original_text


def test_helper_does_not_generate_a_translation_or_summary() -> None:
    result = detect_secretary_language("Necesito información de la propiedad")

    assert result.english_va_summary is None
    assert not hasattr(result, "translated_property_facts")


def test_spanish_automated_outbound_is_never_authorized() -> None:
    result = detect_secretary_language("Hola, necesito información de esta casa")

    assert result.detected_language is SecretaryLanguage.SPANISH
    assert result.spanish_automated_outbound_authorized is False


def test_numeric_and_address_only_text_provides_no_language_authority() -> None:
    result = detect_secretary_language("3 bed / 2 bath, $225,000, 123 Main St")

    assert result.detected_language is SecretaryLanguage.UNCERTAIN
    assert result.preferred_language is None
    assert result.confidence == 0.0


def test_resolve_preferred_language_uses_same_safe_transition() -> None:
    assert (
        resolve_preferred_language("OK", SecretaryLanguage.ENGLISH)
        is SecretaryLanguage.ENGLISH
    )


def test_uncertain_cannot_be_stored_as_preference() -> None:
    with pytest.raises(ValueError, match="English or Spanish"):
        detect_secretary_language("OK", established_preferred_language="Uncertain")

    with pytest.raises(ValidationError):
        LanguageAssessment(
            original_text="OK",
            detected_language=SecretaryLanguage.UNCERTAIN,
            confidence=0,
            evidence=(),
            preferred_language=SecretaryLanguage.UNCERTAIN,
        )
