"""Locked insurance controls ported from the approved Illinois CFD builder.

The Insurance Included = YES path leaves template wording unchanged. The
Buyer Responsible for Insurance path applies only the already owner-approved
NO-version clauses. This module does not invent or rewrite legal language.
"""

from __future__ import annotations

import re
from typing import Any

YES_VALUES = frozenset(
    {
        "yes",
        "y",
        "true",
        "included",
        "included in payment",
        "insurance included",
        "1",
    }
)
NO_VALUES = frozenset(
    {
        "no",
        "n",
        "false",
        "not included",
        "not included in payment",
        "insurance not included",
        "excluded",
        "0",
    }
)

INSURANCE_VERSION_INCLUDED = "Insurance Included"
INSURANCE_VERSION_BUYER_RESPONSIBLE = "Buyer Responsible for Insurance"

UNKNOWN_PRIOR_YEAR_INSURANCE_DISCLOSURE = (
    "The amount of the annual insurance payment for the year immediately prior "
    "to the sale is unknown and unavailable to Seller. Seller recently acquired "
    "the Premises and does not possess reliable records showing the prior "
    "owner’s annual insurance premium for that year. Seller has not represented "
    "that the prior-year insurance premium was zero."
)

APPROVED_BUYER_RESPONSIBLE_CLAUSE_MAP: tuple[dict[str, str], ...] = (
    {"clause_id": "monthly_payment", "template_location": "Paragraph 33", "approval": "owner approved"},
    {
        "clause_id": "prior_year_insurance",
        "template_location": "Paragraph 68",
        "approval": "owner approved; counsel review flag retained when unknown",
    },
    {
        "clause_id": "insurance_responsibility_and_tax",
        "template_location": "Paragraphs 73-80",
        "approval": "owner approved",
    },
    {"clause_id": "hazard_and_casualty", "template_location": "Paragraphs 88-96", "approval": "owner approved"},
    {"clause_id": "temporary_early_possession", "template_location": "Paragraph 179", "approval": "owner approved"},
)
EXPECTED_BUYER_RESPONSIBLE_CLAUSE_IDS = {
    "monthly_payment",
    "prior_year_insurance",
    "insurance_responsibility_and_tax",
    "hazard_and_casualty",
    "temporary_early_possession",
}


class InsuranceValueError(ValueError):
    """Raised when insurance responsibility is blank or unrecognized."""


def _normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def normalize_insurance_included(value: object) -> str:
    normalized = _normalize_text(value)
    if normalized in YES_VALUES:
        return "yes"
    if normalized in NO_VALUES:
        return "no"
    display_value = str(value or "").strip()
    if not display_value:
        raise InsuranceValueError(
            "Insurance responsibility is blank. Confirm whether insurance is included in the monthly payment before generating this contract."
        )
    raise InsuranceValueError(
        f'Insurance responsibility "{display_value}" is not recognized. Use a clear YES or NO value before generating this contract.'
    )


def insurance_version_label(status: str) -> str:
    return INSURANCE_VERSION_INCLUDED if normalize_insurance_included(status) == "yes" else INSURANCE_VERSION_BUYER_RESPONSIBLE


def insurance_amount_for_payment(monthly_insurance: float, status: str) -> float:
    return float(monthly_insurance) if normalize_insurance_included(status) == "yes" else 0.0


def buyer_responsible_version_ready() -> bool:
    return {item.get("clause_id", "") for item in APPROVED_BUYER_RESPONSIBLE_CLAUSE_MAP} == EXPECTED_BUYER_RESPONSIBLE_CLAUSE_IDS


def _iter_document_paragraphs(document: Any):
    for paragraph in getattr(document, "paragraphs", []) or []:
        yield paragraph

    def walk_table(table: Any):
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs
                for nested_table in cell.tables:
                    yield from walk_table(nested_table)

    for table in getattr(document, "tables", []) or []:
        yield from walk_table(table)


def _set_document_paragraph_text(paragraph: Any, text: str) -> None:
    runs = list(getattr(paragraph, "runs", []) or [])
    if runs:
        first_run = runs[0]
        first_run.text = text
        for extra_run in runs[1:]:
            element = getattr(extra_run, "_element", None)
            parent = element.getparent() if element is not None else None
            if parent is not None:
                parent.remove(element)
    else:
        paragraph.add_run(text)


def _find_paragraph(document: Any, prefix: str):
    for paragraph in _iter_document_paragraphs(document):
        if paragraph.text.strip().startswith(prefix):
            return paragraph
    raise RuntimeError(f"Insurance safety stop: expected contract paragraph was not found: {prefix}")


def _clear_paragraphs_by_prefix(document: Any, prefixes: tuple[str, ...]) -> None:
    for prefix in prefixes:
        _set_document_paragraph_text(_find_paragraph(document, prefix), "")


def _buyer_responsible_monthly_payment_text(context: dict[str, object]) -> str:
    return (
        "4. Buyer shall pay to Seller the total sum of "
        f"{context['SALES_PRICE']} (Purchase Price) in the following manner: "
        f"{context['DOWN_PAYMENT']} shall be immediately paid Seller as down "
        f"payment, with interest from {context['INTEREST_START_DATE']}, at "
        f"{context['INTEREST_RATE']} per annum on the unpaid principal balance "
        "from time to time, payable in installments of "
        f"{context['TOTAL_MONTHLY_PAYMENT']}, which includes "
        f"{context['MONTHLY_PRINCIPAL_INTEREST']} principal and interest and "
        f"{context['MONTHLY_TAXES']} for taxes. Insurance is not included in "
        "the Installment Payment and shall be obtained and paid separately by "
        "Buyer as provided in this Agreement. The first installment is due "
        f"{context['FIRST_PAYMENT_DATE']}, and successive installments are due "
        "on the 1st day of each month thereafter until all sums due Seller are "
        "paid. Each installment shall be first applied to Escrow charges, then "
        "to late charges against Buyer as provided in paragraph 8, then to "
        "unpaid accrued interest, and the balance to principal. Buyer may "
        "prepay any sums due hereunder. NO PARTIAL PRE-PAYMENTS UNLESS MUTUALLY "
        "AGREED UPON. ALL Monthly Payments are to be made out to "
        f"{context['PAYMENT_PAYEE']}, {context['PAYMENT_ADDRESS']} or through "
        f"{context['PAYMENT_SYSTEM']}."
    )


def _buyer_responsible_insurance_text() -> str:
    return (
        "12. A. Buyer shall be solely responsible for obtaining, maintaining, "
        "and paying for property/hazard and liability insurance on the Premises. "
        "Insurance is not included in Buyer’s monthly Installment Payment. Buyer "
        "may take possession of the Premises before obtaining the insurance "
        "required by this paragraph; however, Buyer shall obtain the required "
        "insurance and provide Seller with proof of active coverage within "
        "seventy-two (72) hours after Buyer takes possession of the Premises. "
        "The required insurance shall include property/hazard insurance in an "
        "amount not less than the Purchase Price stated in this Agreement and "
        "liability insurance with coverage of not less than Five Hundred "
        "Thousand Dollars ($500,000). Seller shall be listed as an additional "
        "insured on the policy. Proof of active coverage may include a "
        "declarations page, binder, certificate of insurance, or other "
        "satisfactory written evidence of coverage. After the required "
        "insurance is obtained, Buyer shall keep all required insurance "
        "continuously in force for the remainder of this Agreement and shall "
        "provide updated proof upon each renewal, replacement, material policy "
        "change, or Seller’s reasonable request. Failure to obtain the required "
        "insurance and provide proof within seventy-two (72) hours after taking "
        "possession, or failure thereafter to maintain, pay for, or provide "
        "updated proof of the required insurance, shall constitute a default "
        "under this Agreement, subject to all notice and cure rights required by "
        "applicable law."
    )


def _buyer_responsible_tax_text() -> str:
    return (
        "B. Seller shall be obligated to pay taxes when due and submit evidence "
        "of payment to Escrow Agent who shall add the same to contract balance "
        "as of the date submitted."
    )


def _buyer_responsible_tax_adjustment_text() -> str:
    return (
        "Upon written notice by Seller to Buyer and Escrow Agent, Installment "
        "Payment shall be increased by 1/12 of any increase in taxes over year "
        "of most recent such adjustment. Buyer agrees to pay said sums to "
        "Escrow Agent within sixty (60) days of notification of the same by "
        "Seller."
    )


def _buyer_responsible_hazard_casualty_text() -> str:
    return (
        "14. No later than seventy-two (72) hours after Buyer takes possession "
        "of the Premises, Buyer shall obtain property/hazard insurance in an "
        "amount not less than the Purchase Price stated in this Agreement, "
        "liability insurance with coverage of not less than Five Hundred "
        "Thousand Dollars ($500,000), and shall have Seller listed as an "
        "additional insured. After obtaining the required coverage, Buyer shall "
        "keep it continuously in force for the remainder of this Agreement. "
        "Buyer is also responsible for insuring Buyer’s personal property. If "
        "the Premises are damaged by casualty and insurance proceeds are payable "
        "as a result of damage to a dwelling structure, the proceeds shall be "
        "applied to repair the damage as required by applicable Illinois law. "
        "Buyer and Seller may make a fair and reasonable distribution of "
        "insurance proceeds by a signed written agreement made after the time "
        "required by law. If the terms of Seller’s mortgage require insurance "
        "proceeds to be applied to Seller’s mortgage balance, such proceeds may "
        "be so applied with a corresponding credit to Buyer as required by law. "
        "Buyer shall be responsible for any insurance deductible applicable to "
        "a covered loss unless otherwise agreed in writing by Buyer and Seller."
    )


def _buyer_responsible_early_possession_text(context: dict[str, object]) -> str:
    return (
        "If the proposed transaction is canceled or the Contract is not fully "
        f"executed on {context['EARLIEST_EXECUTION_DATE']}, Buyer shall promptly "
        "vacate and surrender possession and all keys. Seller may use only "
        "lawful remedies to recover possession. Buyer shall not make alterations "
        "or repairs without Seller’s prior written consent. Buyer may take "
        "possession before obtaining the property/hazard and liability insurance "
        "required by this Agreement; however, Buyer shall obtain the required "
        "insurance and provide Seller with proof of active coverage within "
        "seventy-two (72) hours after Buyer takes possession of the Premises. "
        "Buyer remains responsible for Buyer’s personal property during early "
        "possession."
    )


def apply_buyer_responsible_insurance_to_document(document: Any, context: dict[str, object]) -> list[str]:
    """Apply only the owner-approved NO-version clauses to a rendered DOCX."""
    if str(context.get("_INSURANCE_STATUS", "")).strip().lower() != "no":
        return []
    if not buyer_responsible_version_ready():
        raise RuntimeError("Insurance safety stop: the Buyer Responsible clause map is not fully approved and locked.")

    changed: list[str] = []
    _set_document_paragraph_text(
        _find_paragraph(document, "4. Buyer shall pay to Seller the total sum of"),
        _buyer_responsible_monthly_payment_text(context),
    )
    changed.append("monthly_payment")

    prior_year_paragraph = _find_paragraph(document, "The last hazard insurance bill for the premises was")
    if not bool(context.get("_PRIOR_YEAR_INSURANCE_KNOWN", False)):
        _set_document_paragraph_text(prior_year_paragraph, UNKNOWN_PRIOR_YEAR_INSURANCE_DISCLOSURE)
    changed.append("prior_year_insurance")

    _set_document_paragraph_text(
        _find_paragraph(document, "12. A. Buyer shall pay insurance when due"),
        _buyer_responsible_insurance_text(),
    )
    _set_document_paragraph_text(
        _find_paragraph(document, "B. Seller shall be obligated to pay taxes and insurance when due"),
        _buyer_responsible_tax_text(),
    )
    _clear_paragraphs_by_prefix(document, ("payment to Escrow Agent who shall add the same",))
    _set_document_paragraph_text(
        _find_paragraph(document, "(Upon written notice by Seller to Buyer and Escrow Agent"),
        _buyer_responsible_tax_adjustment_text(),
    )
    _clear_paragraphs_by_prefix(
        document,
        (
            "increased by 1/12 of any increase in taxes and insurance",
            "adjustment.) (Buyer agrees to pay said sums to Escrow Agent",
            "notification of the same by Seller.)",
        ),
    )
    changed.append("insurance_responsibility_and_tax")

    _set_document_paragraph_text(
        _find_paragraph(document, "14. For the Duration of this Agreement, Seller shall keep all improvements insured"),
        _buyer_responsible_hazard_casualty_text(),
    )
    _clear_paragraphs_by_prefix(
        document,
        (
            "shall insure all of Buyer’s Items of personal property",
            "damaged by casualty, Buyer shall promptly cause all improvements",
            "Buyer shall fail to cause such repairs or rebuilding",
            "insurance proceeds shall be instead paid to Escrow Agent",
            "balance of any mortgage on Premises",
            "balance, if any, shall then be paid to the Buyer.",
            "The Buyer agrees to pay any insurance deductible",
        ),
    )
    changed.append("hazard_and_casualty")

    _set_document_paragraph_text(
        _find_paragraph(document, "If the proposed transaction is canceled or the Contract is not fully executed on"),
        _buyer_responsible_early_possession_text(context),
    )
    changed.append("temporary_early_possession")

    combined_text = "\n".join(paragraph.text for paragraph in _iter_document_paragraphs(document))
    for phrase in (
        "Seller shall be obligated to pay taxes and insurance when due",
        "Seller shall keep all improvements insured",
        "increased by 1/12 of any increase in taxes and insurance",
    ):
        if phrase in combined_text:
            raise RuntimeError(
                "Insurance safety stop: contradictory Seller-provided insurance language remains in the NO-version document: "
                f"{phrase}"
            )
    for phrase in (
        "additional insured",
        "Five Hundred Thousand Dollars ($500,000)",
        "not less than the Purchase Price stated in this Agreement",
        "seventy-two (72) hours after Buyer takes possession",
        "Insurance is not included in the Installment Payment",
    ):
        if phrase not in combined_text:
            raise RuntimeError(
                "Insurance safety stop: required Buyer-responsible language is missing from the NO-version document: "
                f"{phrase}"
            )
    if set(changed) != EXPECTED_BUYER_RESPONSIBLE_CLAUSE_IDS:
        raise RuntimeError("Insurance safety stop: not every approved NO-version clause was applied to the document.")
    return changed
