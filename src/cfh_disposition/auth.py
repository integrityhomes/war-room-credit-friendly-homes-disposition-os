from __future__ import annotations

import hmac
from collections.abc import Mapping
from typing import Any


def configured_password(secrets: Mapping[str, Any]) -> str:
    value = secrets.get("APP_PASSWORD", "")
    return str(value).strip()


def password_matches(submitted: str, expected: str) -> bool:
    if not expected:
        return False
    return hmac.compare_digest(submitted.encode("utf-8"), expected.encode("utf-8"))
