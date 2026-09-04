"""Owner-facing diagnostics for the verified read-only Google property source."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

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


class PropertyDiagnosticFailureCategory(StrEnum):
    MISSING_RUNTIME_SECRET = "MISSING_RUNTIME_SECRET"
    MALFORMED_SERVICE_ACCOUNT = "MALFORMED_SERVICE_ACCOUNT"
    CREDENTIAL_CREATION_FAILED = "CREDENTIAL_CREATION_FAILED"
    SPREADSHEET_OPEN_FAILED = "SPREADSHEET_OPEN_FAILED"
    WORKSHEET_DISCOVERY_FAILED = "WORKSHEET_DISCOVERY_FAILED"
    WORKSHEET_READ_FAILED = "WORKSHEET_READ_FAILED"
    NO_WORKSHEETS_FOUND = "NO_WORKSHEETS_FOUND"
    NO_QUALIFYING_PROPERTIES = "NO_QUALIFYING_PROPERTIES"
    ROW_NORMALIZATION_FAILED = "ROW_NORMALIZATION_FAILED"
    DUPLICATE_PLANNING_FAILED = "DUPLICATE_PLANNING_FAILED"
    READ_ONLY_SAFETY_FAILURE = "READ_ONLY_SAFETY_FAILURE"
    UNKNOWN_SAFE_FAILURE = "UNKNOWN_SAFE_FAILURE"


class SafePropertyDiagnosticFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: PropertyDiagnosticFailureCategory
    explanation: str


_SAFE_FAILURES = {
    PropertyDiagnosticFailureCategory.MISSING_RUNTIME_SECRET: "A required CommandCore runtime secret is not configured.",
    PropertyDiagnosticFailureCategory.MALFORMED_SERVICE_ACCOUNT: "The configured Google service-account information is malformed.",
    PropertyDiagnosticFailureCategory.CREDENTIAL_CREATION_FAILED: "Read-only Google credentials could not be created.",
    PropertyDiagnosticFailureCategory.SPREADSHEET_OPEN_FAILED: "The configured read-only Google spreadsheet could not be opened.",
    PropertyDiagnosticFailureCategory.WORKSHEET_DISCOVERY_FAILED: "Worksheet names could not be discovered safely.",
    PropertyDiagnosticFailureCategory.WORKSHEET_READ_FAILED: "One or more property worksheets could not be read safely.",
    PropertyDiagnosticFailureCategory.NO_WORKSHEETS_FOUND: "No unambiguous worksheets were found in the configured spreadsheet.",
    PropertyDiagnosticFailureCategory.NO_QUALIFYING_PROPERTIES: "No qualifying property rows were found in the approved source.",
    PropertyDiagnosticFailureCategory.ROW_NORMALIZATION_FAILED: "Property rows could not be normalized safely.",
    PropertyDiagnosticFailureCategory.DUPLICATE_PLANNING_FAILED: "Duplicate-property planning could not be completed safely.",
    PropertyDiagnosticFailureCategory.READ_ONLY_SAFETY_FAILURE: "The diagnostic stopped because its read-only safety contract could not be confirmed.",
    PropertyDiagnosticFailureCategory.UNKNOWN_SAFE_FAILURE: "The read-only diagnostic failed safely without exposing provider or property details.",
}


def safe_property_diagnostic_failure(
    error: GoogleBridgeError,
) -> SafePropertyDiagnosticFailure:
    """Map sanitized bridge errors to a fixed public allowlist without echoing them."""
    message = str(error).casefold()
    if "runtime secret is missing" in message:
        category = PropertyDiagnosticFailureCategory.MISSING_RUNTIME_SECRET
    elif "service account secret is malformed" in message:
        category = PropertyDiagnosticFailureCategory.MALFORMED_SERVICE_ACCOUNT
    elif "credentials could not be created" in message:
        category = PropertyDiagnosticFailureCategory.CREDENTIAL_CREATION_FAILED
    elif "spreadsheet could not be opened" in message:
        category = PropertyDiagnosticFailureCategory.SPREADSHEET_OPEN_FAILED
    elif "no property worksheets were discovered" in message or "no unambiguous worksheet" in message:
        category = PropertyDiagnosticFailureCategory.NO_WORKSHEETS_FOUND
    elif "worksheet names could not be listed" in message or "ambiguous worksheet names" in message:
        category = PropertyDiagnosticFailureCategory.WORKSHEET_DISCOVERY_FAILED
    elif "worksheet could not be read" in message or "worksheets could not be read" in message:
        category = PropertyDiagnosticFailureCategory.WORKSHEET_READ_FAILED
    elif "no qualifying property rows" in message:
        category = PropertyDiagnosticFailureCategory.NO_QUALIFYING_PROPERTIES
    elif "normalize" in message or "normalization" in message:
        category = PropertyDiagnosticFailureCategory.ROW_NORMALIZATION_FAILED
    elif "duplicate" in message and "plan" in message:
        category = PropertyDiagnosticFailureCategory.DUPLICATE_PLANNING_FAILED
    elif any(
        marker in message
        for marker in (
            "read-only",
            "three-row limit",
            "three-row safety limit",
            "source type",
            "worksheet did not match",
            "dependencies are incomplete",
        )
    ):
        category = PropertyDiagnosticFailureCategory.READ_ONLY_SAFETY_FAILURE
    else:
        category = PropertyDiagnosticFailureCategory.UNKNOWN_SAFE_FAILURE
    return SafePropertyDiagnosticFailure(
        category=category,
        explanation=_SAFE_FAILURES[category],
    )


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
