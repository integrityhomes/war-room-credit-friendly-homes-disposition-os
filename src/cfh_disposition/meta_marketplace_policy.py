from __future__ import annotations

import re
from dataclasses import dataclass

from .listing_compliance import review_shared_compliance

META_MARKETPLACE_POLICY_VERSION = "2026-08-03"


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
        r"\bno\s+credit\s+check\b|\bcredit\s+(?:doesn['’]?t|does\s+not)\s+matter\b|\bregardless\s+of\s+credit\b",
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
        r"\b(?:act\s+now|today\s+only|won['’]?t\s+last|hurry|first\s+come\s+first\s+served)\b",
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
