from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .fact_lock import MARKETABLE_PROPERTY_STATUSES
from .listing_compliance import ComplianceResult, ComplianceResultState, review_shared_compliance
from .models import OwnerFinanceProperty

META_MARKETPLACE_POLICY_VERSION = "2026-09-14.1"
META_AUDIT_LOGGER = logging.getLogger(__name__)
META_AUDIT_LOGGER.setLevel(logging.INFO)
if not META_AUDIT_LOGGER.handlers:
    META_AUDIT_LOGGER.addHandler(logging.StreamHandler())


@dataclass(frozen=True, slots=True)
class MetaPolicyRule:
    category: str
    pattern: str
    message: str


META_MARKETPLACE_POLICY_CHECKLIST: tuple[str, ...] = (
    "Accurate property facts and no willful misrepresentation",
    "No guaranteed approval, no-credit-check, or no-denial claims",
    "No advance-fee, wire-transfer, gift-card, crypto, or off-platform payment requests",
    "No investment-return, cash-flip, get-rich-quick, grant, debt-relief, or credit-repair claims",
    "No giveaways or rewards tied to registration, personal information, reviews, or referrals",
    "No requests for Social Security numbers, bank details, card details, passwords, or login credentials",
    "No fake documents, fake currency, stolen information, impersonation, or account-credential offers",
    "No gambling, money-muling, money-laundering, cheating, surveillance, or unauthorized-device offers",
    "No discriminatory housing preferences or protected-class targeting",
    "No unsupported condition, neighborhood-safety, crime, school-quality, or buyer-type claims",
    "Exact price, down payment, monthly payment, condition, repairs, and disclosures",
    "Approval, terms, and availability disclaimer; no payment through Facebook; Equal Housing Opportunity",
)


BLOCKING_RULES: tuple[MetaPolicyRule, ...] = (
    MetaPolicyRule(
        "Approval and loan fraud",
        r"\b(?:everyone|anyone)\s+(?:is\s+)?approved\b",
        "Remove claims that everyone or anyone is approved.",
    ),
    MetaPolicyRule(
        "Approval and loan fraud",
        r"\bguaranteed\s+(?:approval|financing|loan)\b",
        "Remove guaranteed approval or financing claims.",
    ),
    MetaPolicyRule(
        "Approval and loan fraud",
        r"\bno\s+one\s+(?:is\s+)?denied\b|\bno\s+denials?\b",
        "Remove no-denial claims.",
    ),
    MetaPolicyRule(
        "Approval and loan fraud",
        r"\bno\s+credit\s+check\b|\bcredit\s+(?:doesn['â€™]?t|does\s+not)\s+matter\b|\bregardless\s+of\s+credit\b",
        "Remove absolute credit claims. State that approval and terms are subject to review.",
    ),
    MetaPolicyRule(
        "Approval and loan fraud",
        r"\b(?:instant|automatic|immediate)\s+approval\b|\bpre[-\s]?approved\s+without\b",
        "Remove instant, automatic, or unsupported pre-approval claims.",
    ),
    MetaPolicyRule(
        "Advance-fee fraud",
        r"\b(?:pay|send|wire|transfer)\b.{0,70}\b(?:application|admin|processing|approval)\s+fee\b",
        "Do not request an application, admin, processing, or approval fee in Marketplace copy.",
    ),
    MetaPolicyRule(
        "Advance-fee fraud",
        r"\b(?:application|admin|processing|approval)\s+fee\b.{0,70}\b(?:approve|approved|approval|qualify|qualification)\b",
        "Do not tie a fee to approval or qualification.",
    ),
    MetaPolicyRule(
        "Unsafe payment request",
        r"\b(?:send|wire|transfer|pay)\b.{0,80}\b(?:gift\s*card|bitcoin|crypto(?:currency)?|wire\s+transfer|cash\s*app|venmo|zelle)\b",
        "Do not request payment by gift card, crypto, wire transfer, Cash App, Venmo, or Zelle in the listing.",
    ),
    MetaPolicyRule(
        "Unsafe payment request",
        r"\b(?:send|pay|wire|transfer)\b.{0,60}\b(?:deposit|down\s+payment)\b.{0,40}\b(?:now|today|before\s+(?:viewing|showing)|to\s+hold)\b",
        "Do not ask buyers to send a deposit or down payment through Marketplace before normal review and documentation.",
    ),
    MetaPolicyRule(
        "Investment fraud",
        r"\b(?:guaranteed|risk[-\s]?free)\s+(?:return|profit|investment)\b|\bguaranteed\s+roi\b",
        "Remove guaranteed or risk-free investment-return claims.",
    ),
    MetaPolicyRule(
        "Investment fraud",
        r"\b(?:cash|money)\s*flip\b|\bdouble\s+your\s+money\b|\bget[-\s]?rich[-\s]?quick\b",
        "Remove cash-flip, money-flip, double-your-money, or get-rich-quick language.",
    ),
    MetaPolicyRule(
        "Government grant fraud",
        r"\b(?:free\s+)?government\s+(?:grant|money|funding)\b|\bguaranteed\s+government\s+program\b",
        "Remove government-grant or government-money claims unless they are verified and directly applicable.",
    ),
    MetaPolicyRule(
        "Debt relief and credit repair fraud",
        r"\b(?:erase|delete|remove|wipe)\b.{0,40}\b(?:bad\s+credit|credit\s+report|collections?|debt)\b",
        "Remove promises to erase credit information, collections, or debt.",
    ),
    MetaPolicyRule(
        "Debt relief and credit repair fraud",
        r"\bnew\s+credit\s+identity\b|\bcredit\s+profile\s+number\b|\bcpn\b",
        "Remove new-credit-identity or CPN claims.",
    ),
    MetaPolicyRule(
        "Giveaway and reward fraud",
        r"\b(?:guaranteed\s+)?(?:cash|money|gift|reward|bonus|free\s+item)\b.{0,100}\b(?:register|sign\s*up|click|visit|share|send|provide)\b",
        "Do not promise money, gifts, or rewards in exchange for registration, clicks, referrals, reviews, or personal information.",
    ),
    MetaPolicyRule(
        "Fake review fraud",
        r"\b(?:buy|sell|pay\s+for|trade|exchange\s+for)\b.{0,50}\b(?:review|rating|testimonial)s?\b",
        "Do not buy, sell, trade, or incentivize reviews or ratings.",
    ),
    MetaPolicyRule(
        "Sensitive information",
        r"\b(?:send|share|provide|message|dm|text)\b.{0,80}\b(?:social\s+security|ssn|bank\s+account|routing\s+number|credit\s+card|debit\s+card|password|login\s+credentials?)\b",
        "Do not request Social Security numbers, bank details, card details, passwords, or login credentials in Marketplace copy.",
    ),
    MetaPolicyRule(
        "Impersonation and deceptive identity",
        r"\b(?:officially|formally)\s+(?:approved|endorsed)\s+by\s+(?:facebook|meta|the\s+government|a\s+bank)\b|\bfacebook[-\s]?approved\b|\bmeta[-\s]?approved\b",
        "Remove unsupported claims of approval or endorsement by Meta, Facebook, government, or a financial institution.",
    ),
    MetaPolicyRule(
        "Fake or stolen goods and information",
        r"\b(?:fake|forged|counterfeit)\s+(?:documents?|currency|certificates?|vouchers?|coupons?)\b|\bstolen\s+(?:credit\s+cards?|personal\s+information|identity|credentials?)\b",
        "Remove fake, forged, counterfeit, or stolen-document and information content.",
    ),
    MetaPolicyRule(
        "Subscription and credential fraud",
        r"\b(?:buy|sell|trade|share)\b.{0,60}\b(?:subscription|streaming|online\s+service)\s+(?:account|login|credentials?)\b",
        "Do not offer subscription-service accounts or login credentials.",
    ),
    MetaPolicyRule(
        "Money laundering and money muling",
        r"\bmoney\s+mul(?:e|ing)\b|\bmoney\s+launder(?:ing)?\b|\buse\s+your\s+bank\s+account\s+to\s+transfer\b",
        "Remove money-muling, money-laundering, or third-party account-transfer content.",
    ),
    MetaPolicyRule(
        "Gambling fraud",
        r"\bguaranteed\s+(?:win|winning)\b|\brigged\s+(?:game|match|outcome)\b|\bmatch[-\s]?fix(?:ing)?\b",
        "Remove guaranteed-winning, rigged-game, or match-fixing content.",
    ),
    MetaPolicyRule(
        "Cheating and unauthorized devices",
        r"\b(?:exam\s+answers?|answer\s+sheets?|pass\s+a\s+drug\s+test|fake\s+drug\s+test)\b|\b(?:spy\s+cam|hidden\s+camera|phone\s+tracker)\b",
        "Remove cheating, drug-test evasion, hidden-surveillance, or unauthorized-device content.",
    ),
    MetaPolicyRule(
        "Fair housing discrimination",
        r"\b(?:no|only|preferred?|preference\s+for)\s+(?:children|kids|families|men|women|males|females|singles|couples|christians|muslims|english\s+speakers|immigrants|disabled\s+people|section\s*8)\b",
        "Remove discriminatory housing preferences. Describe the property, not the preferred buyer.",
    ),
    MetaPolicyRule(
        "Fair housing discrimination",
        r"\badults?\s+only\b|\bno\s+children\b|\bno\s+kids\b",
        "Remove adults-only or no-children preferences unless a verified lawful exemption applies.",
    ),
    MetaPolicyRule(
        "Fair housing discrimination",
        r"\b(?:perfect|ideal|best)\s+for\s+(?:families|a\s+family|young\s+couples?|singles|retirees|students|christians|men|women)\b",
        "Remove buyer-type targeting. Describe property features instead.",
    ),
    MetaPolicyRule(
        "Neighborhood and safety claim",
        r"\b(?:safe|crime[-\s]?free|no[-\s]?crime|low[-\s]?crime)\s+(?:area|neighbou?rhood|community)\b",
        "Remove neighborhood safety or crime claims that cannot be guaranteed.",
    ),
    MetaPolicyRule(
        "Neighborhood and safety claim",
        r"\bfamily[-\s]?friendly\s+(?:area|neighbou?rhood|community)\b",
        "Remove family-friendly neighborhood language; describe objective property facts instead.",
    ),
)


WARNING_RULES: tuple[MetaPolicyRule, ...] = (
    MetaPolicyRule(
        "Pressure language",
        r"\b(?:act\s+now|today\s+only|won['â€™]?t\s+last|hurry|first\s+come\s+first\s+served)\b",
        "Avoid pressure language that can make a legitimate listing appear deceptive.",
    ),
    MetaPolicyRule(
        "Subjective property claim",
        r"\b(?:perfect|flawless|excellent|amazing)\s+condition\b|\bnothing\s+wrong\s+with\b",
        "Replace subjective condition claims with specific observable facts and known repairs.",
    ),
    MetaPolicyRule(
        "Subjective neighborhood claim",
        r"\b(?:great|best|desirable|quiet)\s+neighbou?rhood\b|\b(?:great|best|top[-\s]?rated)\s+schools?\b",
        "Avoid subjective neighborhood or school-quality claims; use objective location facts only.",
    ),
    MetaPolicyRule(
        "Financing clarity",
        r"\bno\s+bank\s+(?:needed|required|qualifying)\b",
        "Clarify that this is seller financing and that approval and terms are subject to review.",
    ),
    MetaPolicyRule(
        "Formatting",
        r"!{3,}|\?{3,}",
        "Reduce repeated punctuation so the listing does not look spammy.",
    ),
)


REQUIRED_MARKETPLACE_DISCLOSURES: tuple[str, ...] = (
    "Approval, terms, and availability are subject to review and verification.",
    "No payment is requested through Facebook.",
    "Equal Housing Opportunity.",
)


def _rule_messages(text: str, rules: tuple[MetaPolicyRule, ...]) -> list[str]:
    messages: list[str] = []
    for rule in rules:
        if re.search(rule.pattern, text, flags=re.IGNORECASE | re.DOTALL):
            messages.append(f"{rule.category}: {rule.message}")
    return sorted(set(messages))


def meta_marketplace_policy_errors(text: str) -> list[str]:
    baseline = review_shared_compliance(
        channel="marketplace",
        content=text,
        approval_required=False,
        publication_mode="Assisted Posting",
    )
    return sorted(set((*baseline.blockers, *_rule_messages(text, BLOCKING_RULES))))


def meta_marketplace_policy_warnings(text: str) -> list[str]:
    return _rule_messages(text, WARNING_RULES)


def marketplace_disclaimer() -> str:
    return " ".join(REQUIRED_MARKETPLACE_DISCLOSURES)

# Reviewed local safety profile, not a claim that provider policies never change.
META_CHANNEL_ASSETS = {
    "marketplace": ("profile", "marketplace"),
    "facebook_groups": ("profile", "group"),
    "facebook": ("profile", "page"),
    "messenger": ("profile", "page"),
    "meta_ads": ("profile", "page", "ad_account"),
    "instagram": ("instagram",),
}
META_HOUSING_SAFETY_PROFILE = {"special_ad_category": "HOUSING", "age_min": 18, "age_max": "65+", "gender": "ALL"}
META_BLOCKING_ERROR_CODES = frozenset({"2909037", "2909036", "2909035"})
META_HEALTH_MAX_AGE = timedelta(hours=24)
META_PUBLIC_LINK_PATTERN = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
META_INTERNAL_LINK_WARNING = "Internal attribution only â€” do not paste this tracking link into public Facebook Group copy."
# Owner-reported recovery hold. Changing this requires verified restoration and owner scope.
MARKETPLACE_PUBLISHING_HOLD = True

HealthState = Literal["WORKING", "MANUAL", "NEEDS_REVIEW", "ACCESS_BLOCKED_BY_META", "RESTRICTED", "UNKNOWN"]


class MetaSafetyContext(BaseModel):
    """Local reviewed evidence only; never inferred from credentials or a payload PASS."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    health: dict[str, HealthState] = Field(default_factory=dict)
    health_checked_at: datetime | None = None
    required_assets: tuple[Literal["profile", "page", "ad_account", "group", "marketplace", "instagram", "commerce", "pixel"], ...] = ()
    housing: dict[str, object] | None = None
    commerce_required: bool | None = None
    commerce_state: Literal["WORKING", "DEPRECATED", "STALE", "STALE_OFFSITE_CHECKOUT", "DISABLED", "UNKNOWN"] = "UNKNOWN"
    meta_error_codes: tuple[str, ...] = ()
    bypass_restriction: bool = False
    facts_verified: bool | None = None
    human_approved: bool = False


class MetaFinding(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: Literal["WARNING", "BLOCK"]
    code: str
    reason: str
    corrective_action: str


class MetaDecision(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: Literal["PASS", "WARNING", "BLOCK"]
    channel: str
    action: Literal["prepare", "publish", "message", "advertise"]
    policy_version: str = META_MARKETPLACE_POLICY_VERSION
    timestamp: datetime
    content_hash: str
    property_id: str | None = None
    findings: tuple[MetaFinding, ...]
    health: dict[str, HealthState]
    health_checked_at: datetime | None
    commerce_state: str
    meta_error_codes: tuple[str, ...]
    human_approval_required: bool = True
    external_action_started: bool = False


def review_meta_action(
    *, channel: str, content: str, action: Literal["prepare", "publish", "message", "advertise"] = "prepare",
    context: MetaSafetyContext | None = None, property_record: OwnerFinanceProperty | None = None,
    required_disclosures: tuple[str, ...] = (), checked_at: datetime | None = None,
) -> MetaDecision:
    """One Meta decision; preparation is never publication permission.

    Audit uses a content digest and canonical ID, not raw copy, provider responses,
    credentials or health-map keys supplied by a caller. Persist with existing records.
    """
    ctx = context or MetaSafetyContext()
    now = checked_at or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    findings: list[MetaFinding] = []
    live = action != "prepare"

    def add(code: str, reason: str, correction: str, *, missing: bool = False):
        findings.append(MetaFinding(status="WARNING" if missing and not live else "BLOCK",
                                    code=code, reason=reason, corrective_action=correction))

    baseline = review_shared_compliance(channel=channel, content=content, property_record=property_record,
        required_disclosures=required_disclosures, approval_required=False, publication_mode="Review", checked_at=now)
    if baseline.blockers:
        # Baseline messages may quote copy/amounts. Never include them in the audit log.
        add("meta.copy", "Public copy failed the existing content or fact checks.", "Review the existing copy validation findings and correct the source facts or copy.")
    for rule in BLOCKING_RULES:
        if re.search(rule.pattern, content, flags=re.IGNORECASE | re.DOTALL):
            add("meta.copy." + re.sub(r"[^a-z0-9]+", "_", rule.category.lower()), rule.message, rule.message)
    for reason in _rule_messages(content, WARNING_RULES):
        add("meta.copy_review", reason, "Review and correct the flagged copy.", missing=True)
    if channel not in META_CHANNEL_ASSETS:
        add("meta.channel", "Unsupported Meta channel.", "Use an explicitly supported channel.")
    if channel in {"marketplace", "facebook_groups"} and META_PUBLIC_LINK_PATTERN.search(content):
        add("meta.internal_link", "Public Facebook organic copy contains an external URL.", META_INTERNAL_LINK_WARNING)
    if ctx.bypass_restriction:
        add("meta.circumvention", "Using another account or profile to bypass a restriction is prohibited.", "Resolve the restriction on the existing asset; do not switch accounts to evade it.")
    if channel == "marketplace" and MARKETPLACE_PUBLISHING_HOLD:
        add("meta.marketplace_hold", "Marketplace publication is on hold pending verified access restoration.", "Prepare only; await restoration and owner review.", missing=not live)
    required = tuple(dict.fromkeys((*META_CHANNEL_ASSETS.get(channel, ()), *ctx.required_assets)))
    for asset in required:
        state = ctx.health.get(asset, "UNKNOWN")
        if state in {"RESTRICTED", "ACCESS_BLOCKED_BY_META"}:
            add("meta.health_restricted", f"Required Meta asset {asset} is restricted.", "Resolve the restriction without an account workaround.", missing=not live)
        elif state != "WORKING":
            add("meta.health_unknown", f"Required asset {asset} is unknown, manual-only, or needs review.", "Verify the required asset health before publication.", missing=True)
    observed = ctx.health_checked_at
    if observed is None or observed.tzinfo is None or not timedelta(0) <= now - observed <= META_HEALTH_MAX_AGE:
        add("meta.health_stale", "Current account-health evidence is missing or stale.", "Obtain current verified health evidence.", missing=True)
    if ctx.commerce_required is None:
        add("meta.commerce_requirement", "Whether this action requires Commerce is unknown.", "Determine whether Commerce is required; do not create a Shop unnecessarily.", missing=True)
    elif ctx.commerce_required and ctx.commerce_state != "WORKING":
        add("meta.commerce", "Required Commerce configuration is unsafe, stale, disabled, or unknown.",
            "Correct and verify the required Commerce asset, including Offsite Checkout.", missing=ctx.commerce_state == "UNKNOWN")
    codes = tuple(sorted(set(str(code) for code in ctx.meta_error_codes if str(code).isdigit())))
    if ctx.meta_error_codes:
        add("meta.provider_error", "Meta returned an unresolved policy/configuration error.", "Correct and verify the provider error before publication.")
    for code in codes:
        if code in META_BLOCKING_ERROR_CODES:
            add("meta.error." + code, "Meta Housing configuration error remains unresolved.", "Correct Housing category and audience settings, then verify the error is resolved.")
    if channel == "meta_ads":
        if ctx.housing is None:
            add("meta.housing_missing", "Housing audience configuration is missing.", "Supply the reviewed Housing safety configuration.", missing=True)
        else:
            for key, expected in META_HOUSING_SAFETY_PROFILE.items():
                if ctx.housing.get(key) != expected:
                    add("meta.housing." + key, "Housing audience does not match the conservative safety profile.", "Use Housing, ages 18 through 65+, and All genders.")
            # No unreviewed detailed targeting, exclusions, lookalikes or opaque audience fields.
            for key, value in ctx.housing.items():
                if key not in META_HOUSING_SAFETY_PROFILE and (key != "detailed_targeting" or value not in ([], ())):
                    add("meta.housing.targeting", "Unreviewed or prohibited Housing audience targeting is present.", "Remove detailed/protected-class targeting and unreviewed audience settings.")
    if ctx.facts_verified is not True:
        add("meta.facts", "Current property facts and availability have not been verified.", "Verify facts, lifecycle, and freshness through existing property controls.", missing=True)
    if live and property_record is not None and property_record.status not in MARKETABLE_PROPERTY_STATUSES:
        add("meta.property_status", "The property is not in a marketable lifecycle state.", "Preserve sold/pending/unavailable protections; review canonical availability.")
    if live and not ctx.human_approved:
        add("meta.approval", "Required human approval is missing.", "Obtain the applicable owner/channel approval; a policy PASS does not authorize spending.")
    decision = MetaDecision(status="BLOCK" if any(f.status == "BLOCK" for f in findings) else "WARNING" if findings else "PASS",
        channel=channel if channel in META_CHANNEL_ASSETS else "unsupported", action=action, timestamp=now,
        content_hash=baseline.content_hash, property_id=str(property_record.property_id) if property_record else None,
        findings=tuple(findings), health={key: ctx.health.get(key, "UNKNOWN") for key in required},
        health_checked_at=observed, commerce_state=ctx.commerce_state, meta_error_codes=codes)
    META_AUDIT_LOGGER.info("meta_compliance_decision %s", decision.model_dump_json())
    return decision


def review_meta_package(*, channel: str, content: str, property_record: OwnerFinanceProperty,
                        required_disclosures: tuple[str, ...], context: MetaSafetyContext | None = None) -> ComplianceResult:
    baseline = review_shared_compliance(channel=channel, content=content, property_record=property_record,
        required_disclosures=required_disclosures, approval_required=True, publication_mode="Approval Required")
    decision = review_meta_action(channel=channel, content=content, property_record=property_record,
        required_disclosures=required_disclosures, context=context)
    return baseline.model_copy(update={
        "policy_version": META_MARKETPLACE_POLICY_VERSION, "meta_decision": decision.model_dump(mode="json"),
        "result": ComplianceResultState.BLOCKED if decision.status == "BLOCK" else baseline.result,
        "blockers": tuple(sorted(set((*baseline.blockers, *(f.reason for f in decision.findings if f.status == "BLOCK"))))),
        "warnings": tuple(sorted(set((*baseline.warnings, *(f.reason for f in decision.findings if f.status == "WARNING"))))),
    })
