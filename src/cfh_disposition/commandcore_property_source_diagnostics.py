"""Owner-facing diagnostics for the verified read-only Google property source."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .commandcore_property_inventory import CanonicalPropertyRecord
from .google_property_readonly_loader import build_read_only_google_runtime
from .google_property_runtime_bridge import (
    CredentialFactory,
    GoogleBridgeError,
    ReadOnlyBridgeResult,
    ReadOnlySheetLoader,
    run_read_only_property_source_test,
)

PROPERTY_DIAGNOSTIC_WORKSHEET = "Decatur/Quincy"


def run_property_source_diagnostic(
    secrets: Mapping[str, Any],
    *,
    existing_records: Sequence[CanonicalPropertyRecord] = (),
    credential_factory: CredentialFactory | None = None,
    sheet_loader: ReadOnlySheetLoader | None = None,
) -> ReadOnlyBridgeResult:
    """Run the fixed three-row, zero-persistence property-source diagnostic."""
    if (credential_factory is None) != (sheet_loader is None):
        raise GoogleBridgeError("The read-only diagnostic dependencies are incomplete.")
    if credential_factory is None or sheet_loader is None:
        credential_factory, sheet_loader = build_read_only_google_runtime(
            PROPERTY_DIAGNOSTIC_WORKSHEET
        )

    result = run_read_only_property_source_test(
        secrets=secrets,
        credential_factory=credential_factory,
        sheet_loader=sheet_loader,
        existing_records=existing_records,
    )
    if result.google_writes or result.commandcore_persistence or result.external_actions_started:
        raise GoogleBridgeError("The property-source diagnostic did not remain read-only.")
    if not result.rows_read or not result.previews:
        raise GoogleBridgeError("The approved worksheet contained no qualifying property rows.")
    if result.rows_read > 3 or result.rows_displayed > 3:
        raise GoogleBridgeError("The property-source diagnostic exceeded its three-row limit.")
    if any(
        preview.worksheet_or_tab.casefold()
        != PROPERTY_DIAGNOSTIC_WORKSHEET.casefold()
        for preview in result.previews
    ):
        raise GoogleBridgeError("The property-source worksheet did not match the approved source.")
    return result
