from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

META_COMPLIANCE_POLICY_VERSION = "2026-09-14"
META_CHANNELS = ("marketplace", "facebook_groups", "meta_ads", "instagram")
KNOWN_HOUSING_AD_ERROR_CODES = frozenset({"2909037", "2909036", "2909035"})


class ComplianceDecision(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCK = "BLOCK"


class MetaAccessState(StrEnum):
    WORKING = "WORKING"
    MANUAL = "MANUAL"
    ACCESS_BLOCKED_BY_META = "ACCESS_BLOCKED_BY_META"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    UNKNOWN = "UNKNOWN"


class MetaCommerceState(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    DEACTIVATED = "DEACTIVATED"
    ACTIVE_HEALTHY = "ACTIVE_HEALTHY"
    STALE_OFFSITE = "STALE_OFFSITE"
    DEPRECATED_OFFSITE = "DEPRECATED_OFFSITE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class MetaComplianceFinding:
    rule_id: str
    decision: ComplianceDecision
    channels: tuple[str, ...]
    message: str


@dataclass(frozen=True, slots=True)
class MetaAccountHealth:
    profile_access: MetaAccessState = MetaAccessState.WORKING
    marketplace_access: MetaAccessState = MetaAccessState.WORKING
    facebook_groups_access: MetaAccessState = MetaAccessState.WORKING
    ad_account_access: MetaAccessState = MetaAccessState.WORKING
    page_access: MetaAccessState = MetaAccessState.WORKING
    alternate_account_bypass_requested: bool = False


@dataclass(frozen=True, slots=True)
class MetaHousingAdConfig:
    special_ad_category: str
    min_age: int
    max_age: int
    max_age_is_plus: bool
    gender: str
    detailed_targeting: tuple[str, ...] = ()
    active_error_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MetaCommerceHealth:
    state: MetaCommerceState = MetaCommerceState.NOT_REQUIRED
    detail: str = ""


@dataclass(frozen=True, slots=True)
class MetaComplianceResult:
    policy_version: str
    decision: ComplianceDecision
    findings: tuple[MetaComplianceFinding, ...]

    @property
    def blocked_channels(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    channel
                    for finding in self.findings
                    if finding.decision == ComplianceDecision.BLOCK
                    for channel in finding.channels
                }
            )
        )

    def is_blocked(self, channel: str) -> bool:
        return channel in self.blocked_channels

    def block_reason(self, channel: str) -> str:
        messages = [
            finding.message
            for finding in self.findings
            if finding.decision == ComplianceDecision.BLOCK and channel in finding.channels
        ]
        return " | ".join(dict.fromkeys(messages))

    def as_dict(self) -> dict[str, object]:
        return {
            "policy_version": self.policy_version,
            "decision": self.decision.value,
            "blocked_channels": list(self.blocked_channels),
            "findings": [
                {
                    "rule_id": finding.rule_id,
                    "decision": finding.decision.value,
                    "channels": list(finding.channels),
                    "message": finding.message,
                }
                for finding in self.findings
            ],
        }


def _finding(
    rule_id: str,
    decision: ComplianceDecision,
    channels: tuple[str, ...],
    message: str,
) -> MetaComplianceFinding:
    return MetaComplianceFinding(
        rule_id=rule_id,
        decision=decision,
        channels=channels,
        message=message,
    )


def _review_access_state(
    findings: list[MetaComplianceFinding],
    *,
    rule_id: str,
    label: str,
    state: MetaAccessState,
    channels: tuple[str, ...],
) -> None:
    if state in {MetaAccessState.ACCESS_BLOCKED_BY_META, MetaAccessState.NEEDS_REVIEW}:
        findings.append(
            _finding(
                rule_id,
                ComplianceDecision.BLOCK,
                channels,
                f"{label} is {state.value}. Do not publish through the affected Meta channel until Meta restores or clears access.",
            )
        )
    elif state == MetaAccessState.UNKNOWN:
        findings.append(
            _finding(
                rule_id,
                ComplianceDecision.WARNING,
                channels,
                f"{label} health is unknown. Verify account health before a high-risk Meta publication.",
            )
        )
    elif state == MetaAccessState.MANUAL:
        findings.append(
            _finding(
                rule_id,
                ComplianceDecision.WARNING,
                channels,
                f"{label} is manual-only. Keep the final platform action human-controlled.",
            )
        )


def _review_account_health(
    findings: list[MetaComplianceFinding],
    account: MetaAccountHealth,
) -> None:
    if account.alternate_account_bypass_requested:
        findings.append(
            _finding(
                "META-ACCOUNT-001",
                ComplianceDecision.BLOCK,
                META_CHANNELS,
                "Do not use another profile, Page, ad account, or identity to bypass a Meta restriction. Resolve the original restriction first.",
            )
        )

    _review_access_state(
        findings,
        rule_id="META-ACCOUNT-002",
        label="Facebook profile",
        state=account.profile_access,
        channels=META_CHANNELS,
    )
    _review_access_state(
        findings,
        rule_id="META-ACCOUNT-003",
        label="Facebook Marketplace access",
        state=account.marketplace_access,
        channels=("marketplace",),
    )
    _review_access_state(
        findings,
        rule_id="META-ACCOUNT-004",
        label="Facebook Group posting access",
        state=account.facebook_groups_access,
        channels=("facebook_groups",),
    )
    _review_access_state(
        findings,
        rule_id="META-ACCOUNT-005",
        label="Meta ad account",
        state=account.ad_account_access,
        channels=("meta_ads",),
    )
    _review_access_state(
        findings,
        rule_id="META-ACCOUNT-006",
        label="Facebook Page",
        state=account.page_access,
        channels=("meta_ads", "instagram"),
    )


def _review_housing_ad(
    findings: list[MetaComplianceFinding],
    ad: MetaHousingAdConfig,
) -> None:
    # Conservative internal controls based on the Housing enforcement settings verified
    # in the business account. These are deliberately stricter than guessing at what
    # Meta might accept; the purpose is to stop a risky launch and force review.
    if ad.special_ad_category.strip().casefold() != "housing":
        findings.append(
            _finding(
                "META-HOUSING-001",
                ComplianceDecision.BLOCK,
                ("meta_ads",),
                "Housing advertising must use Meta's Housing Special Ad Category before launch.",
            )
        )
    if ad.min_age != 18 or ad.max_age != 65 or not ad.max_age_is_plus:
        findings.append(
            _finding(
                "META-HOUSING-002",
                ComplianceDecision.BLOCK,
                ("meta_ads",),
                "Housing ad audience age must be configured as 18–65+ in the current internal safety profile.",
            )
        )
    if ad.gender.strip().casefold() != "all":
        findings.append(
            _finding(
                "META-HOUSING-003",
                ComplianceDecision.BLOCK,
                ("meta_ads",),
                "Housing ad gender must be All in the current internal safety profile.",
            )
        )
    targeting = tuple(item.strip() for item in ad.detailed_targeting if item.strip())
    if targeting:
        findings.append(
            _finding(
                "META-HOUSING-004",
                ComplianceDecision.BLOCK,
                ("meta_ads",),
                "Detailed targeting must be empty for the conservative Housing ad safety profile. Remove: "
                + ", ".join(targeting),
            )
        )

    codes = tuple(dict.fromkeys(str(code).strip() for code in ad.active_error_codes if str(code).strip()))
    if codes:
        known = [code for code in codes if code in KNOWN_HOUSING_AD_ERROR_CODES]
        detail = ", ".join(codes)
        message = f"Active Meta ad error code(s) must be cleared before launch: {detail}."
        if known:
            message += " This includes a previously observed Housing audience/targeting error family."
        findings.append(
            _finding(
                "META-HOUSING-005",
                ComplianceDecision.BLOCK,
                ("meta_ads",),
                message,
            )
        )


def _review_commerce_health(
    findings: list[MetaComplianceFinding],
    commerce: MetaCommerceHealth,
) -> None:
    if commerce.state in {
        MetaCommerceState.STALE_OFFSITE,
        MetaCommerceState.DEPRECATED_OFFSITE,
        MetaCommerceState.NEEDS_REVIEW,
    }:
        detail = f" ({commerce.detail.strip()})" if commerce.detail.strip() else ""
        findings.append(
            _finding(
                "META-COMMERCE-001",
                ComplianceDecision.BLOCK,
                ("marketplace", "meta_ads"),
                "Meta Commerce configuration has a stale, deprecated, or unresolved status"
                + detail
                + ". Resolve it before Marketplace or paid Meta publishing. Do not create an unnecessary Shop solely to bypass the issue.",
            )
        )
    elif commerce.state == MetaCommerceState.UNKNOWN:
        findings.append(
            _finding(
                "META-COMMERCE-002",
                ComplianceDecision.WARNING,
                ("marketplace", "meta_ads"),
                "Meta Commerce health is unknown. Verify that no stale or deprecated checkout signal is attached before high-risk publishing.",
            )
        )


def review_meta_compliance(
    *,
    account: MetaAccountHealth | None = None,
    housing_ad: MetaHousingAdConfig | None = None,
    commerce: MetaCommerceHealth | None = None,
) -> MetaComplianceResult:
    """Return one auditable PASS/WARNING/BLOCK decision for Meta publication safety.

    Existing Marketplace copy/content checks remain authoritative for listing text. This
    gate adds account health, paid Housing audience settings, Commerce health, and
    anti-circumvention controls without duplicating those existing content rules.
    """

    findings: list[MetaComplianceFinding] = []
    if account is not None:
        _review_account_health(findings, account)
    if housing_ad is not None:
        _review_housing_ad(findings, housing_ad)
    if commerce is not None:
        _review_commerce_health(findings, commerce)

    if any(item.decision == ComplianceDecision.BLOCK for item in findings):
        decision = ComplianceDecision.BLOCK
    elif any(item.decision == ComplianceDecision.WARNING for item in findings):
        decision = ComplianceDecision.WARNING
    else:
        decision = ComplianceDecision.PASS

    return MetaComplianceResult(
        policy_version=META_COMPLIANCE_POLICY_VERSION,
        decision=decision,
        findings=tuple(findings),
    )
