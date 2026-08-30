from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader


class ContractReaderError(RuntimeError):
    """Raised when a contract cannot be safely read."""


@dataclass(frozen=True, slots=True)
class ContractFact:
    key: str
    label: str
    expected_value: str


@dataclass(frozen=True, slots=True)
class ContractFinding:
    key: str
    label: str
    expected_value: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class ContractReview:
    extracted_text: str
    findings: tuple[ContractFinding, ...]
    extraction_status: str


def _normalize(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def extract_pdf_text(content: bytes) -> str:
    if not content:
        raise ContractReaderError("The PDF is empty.")
    try:
        reader = PdfReader(BytesIO(content))
    except Exception as exc:
        raise ContractReaderError("The PDF could not be opened.") from exc

    text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    if not text:
        raise ContractReaderError(
            "No readable text was found in this PDF. It may be a scanned/image-only contract and needs OCR before review."
        )
    return text


def extract_docx_text(content: bytes) -> str:
    if not content:
        raise ContractReaderError("The DOCX file is empty.")
    try:
        with ZipFile(BytesIO(content)) as archive:
            xml_bytes = archive.read("word/document.xml")
    except (BadZipFile, KeyError) as exc:
        raise ContractReaderError("The DOCX file could not be opened.") from exc

    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError as exc:
        raise ContractReaderError("The DOCX document text could not be parsed.") from exc

    text_nodes = [node.text or "" for node in root.iter() if node.tag.endswith("}t")]
    text = " ".join(part for part in text_nodes if part).strip()
    if not text:
        raise ContractReaderError("No readable text was found in this DOCX file.")
    return text


def extract_contract_text(file_name: str, content: bytes) -> str:
    suffix = Path(file_name).suffix.casefold()
    if suffix == ".pdf":
        return extract_pdf_text(content)
    if suffix == ".docx":
        return extract_docx_text(content)
    raise ContractReaderError("Contract review currently supports PDF and DOCX files only.")


def compare_contract_facts(text: str, facts: Iterable[ContractFact]) -> tuple[ContractFinding, ...]:
    normalized_text = _normalize(text)
    findings: list[ContractFinding] = []
    for fact in facts:
        expected = str(fact.expected_value or "").strip()
        if not expected:
            findings.append(
                ContractFinding(
                    key=fact.key,
                    label=fact.label,
                    expected_value="",
                    status="missing_deal_fact",
                    detail="CommandCore does not have a verified value for this Deal fact yet.",
                )
            )
            continue

        present = _normalize(expected) in normalized_text
        findings.append(
            ContractFinding(
                key=fact.key,
                label=fact.label,
                expected_value=expected,
                status="found" if present else "needs_review",
                detail=(
                    "The verified Deal value appears in the contract text."
                    if present
                    else "The verified Deal value was not found exactly in the contract text. Review this item before approval."
                ),
            )
        )
    return tuple(findings)


def review_contract(file_name: str, content: bytes, facts: Iterable[ContractFact]) -> ContractReview:
    text = extract_contract_text(file_name, content)
    return ContractReview(
        extracted_text=text,
        findings=compare_contract_facts(text, facts),
        extraction_status="readable_text_extracted",
    )
