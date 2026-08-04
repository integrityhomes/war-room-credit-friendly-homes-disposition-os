from __future__ import annotations

import re

RISKY_CONDITION_PATTERNS: dict[str, str] = {
    r"\bmove[\s-]*in[\s-]+ready\b": (
        'Remove "move-in ready." Describe the specific completed work and current observable condition instead.'
    ),
}


def risky_condition_claim_errors(text: str) -> list[str]:
    """Return blocking messages for subjective property-condition claims."""
    errors: list[str] = []
    for pattern, message in RISKY_CONDITION_PATTERNS.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            errors.append(message)
    return errors
