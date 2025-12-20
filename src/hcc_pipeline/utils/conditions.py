from __future__ import annotations

import re
from typing import List, Optional, Tuple

from hcc_pipeline.models import Condition
from hcc_pipeline.utils.text import normalize_description, normalize_icd10_code


ICD10_PATTERN = r"[A-TV-Z][0-9]{2}(?:\.[0-9A-TV-Z]{1,4}|[0-9A-TV-Z]{1,4})?"
ICD10_RE = re.compile(rf"\b{ICD10_PATTERN}\b", re.IGNORECASE)
CODE_DESC_RE = re.compile(
    rf"^\s*(?P<code>{ICD10_PATTERN})\s*[:\-]\s*(?P<desc>.+)$",
    re.IGNORECASE,
)
ICD10_NORMALIZED_RE = re.compile(r"^[A-TV-Z][0-9]{2}[0-9A-TV-Z]{0,4}$", re.IGNORECASE)

ABBREVIATION_MAP = {
    "cad": "Coronary artery disease",
    "chf": "Congestive heart failure",
    "ckd": "Chronic kidney disease",
    "copd": "Chronic obstructive pulmonary disease",
    "dm": "Diabetes mellitus",
    "gerd": "Gastroesophageal reflux disease",
    "hld": "Hyperlipidemia",
    "htn": "Hypertension",
    "ibd": "Inflammatory bowel disease",
    "mdd": "Major depressive disorder",
    "sud": "Substance use disorder",
    "t1dm": "Type 1 diabetes mellitus",
    "t2dm": "Type 2 diabetes mellitus",
}


def extract_icd10_codes(text: str) -> List[str]:
    codes: List[str] = []
    seen: set[str] = set()
    for match in ICD10_RE.finditer(text):
        raw = match.group(0)
        normalized = normalize_icd10_code(raw)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        codes.append(raw)
    return codes


def format_icd10_code(code: str | None) -> Optional[str]:
    if not code:
        return None
    normalized = normalize_icd10_code(code)
    if not normalized:
        return None
    if len(normalized) <= 3:
        return normalized
    return f"{normalized[:3]}.{normalized[3:]}"


def find_description_for_code(text: str, code: str) -> Optional[str]:
    if not text or not code:
        return None
    match = re.search(
        rf"{re.escape(code)}\s*[:\-]\s*(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return _clean_text(match.group(1))


def split_code_description(text: str | None) -> Tuple[Optional[str], Optional[str]]:
    if not text:
        return None, None
    match = CODE_DESC_RE.match(text.strip())
    if not match:
        return None, None
    return match.group("code"), _clean_text(match.group("desc"))


def strip_first_code(text: str) -> Tuple[str, Optional[str]]:
    match = ICD10_RE.search(text)
    if not match:
        return text, None
    code = match.group(0)
    stripped = (text[: match.start()] + " " + text[match.end() :]).strip()
    stripped = re.sub(r"\(\s*\)", "", stripped)
    stripped = re.sub(r"\s+", " ", stripped)
    stripped = stripped.strip(" -:;")
    return stripped, code


def normalize_condition_fields(condition: Condition) -> tuple[Condition, list[str]]:
    warnings: list[str] = []
    condition_text = condition.condition or ""
    icd10_code = condition.icd10_code
    icd10_description = condition.icd10_description
    clinical_status = _clean_text(condition.clinical_status)
    severity = _clean_text(condition.severity)
    confidence = _normalize_confidence(condition.confidence)

    code_from_condition, condition_desc = split_code_description(condition_text)
    if code_from_condition:
        if not icd10_code:
            icd10_code = code_from_condition
        if not icd10_description and condition_desc:
            icd10_description = condition_desc
        condition_text = condition_desc or condition_text

    code_from_desc, cleaned_desc = split_code_description(icd10_description)
    if code_from_desc:
        if not icd10_code:
            icd10_code = code_from_desc
        icd10_description = cleaned_desc

    if not icd10_code:
        stripped_condition, code_from_condition = strip_first_code(condition_text)
        if code_from_condition:
            icd10_code = code_from_condition
            if stripped_condition:
                condition_text = stripped_condition

    if not icd10_code and icd10_description:
        codes = extract_icd10_codes(icd10_description)
        if codes:
            icd10_code = codes[0]

    if icd10_code and not _is_valid_icd10_code(icd10_code):
        warnings.append(f"invalid_icd10_code:{icd10_code}")
        icd10_code = None

    if icd10_code and _clean_text(condition_text):
        if normalize_icd10_code(condition_text) == normalize_icd10_code(icd10_code):
            condition_text = icd10_description or condition_text

    condition_text = _expand_abbreviation(condition_text)
    cleaned_condition = _clean_text(condition_text)
    cleaned_description = _clean_text(icd10_description)
    if not cleaned_condition:
        cleaned_condition = cleaned_description or _clean_text(icd10_code) or condition.condition

    if not cleaned_condition and not icd10_code and not cleaned_description:
        warnings.append("condition_missing_name")

    return (
        Condition(
            condition=cleaned_condition or "",
            icd10_code=format_icd10_code(icd10_code),
            icd10_description=cleaned_description,
            clinical_status=clinical_status,
            severity=severity,
            confidence=confidence,
            hcc_relevant=condition.hcc_relevant,
            hcc_match=condition.hcc_match,
            match_method=condition.match_method,
        ),
        warnings,
    )


def post_process_conditions(conditions: List[Condition]) -> tuple[List[Condition], List[str]]:
    normalized: list[Condition] = []
    warnings: list[str] = []

    for condition in conditions:
        normalized_condition, condition_warnings = normalize_condition_fields(condition)
        warnings.extend(condition_warnings)
        if _is_empty_condition(normalized_condition):
            warnings.append("condition_empty")
            continue
        normalized.append(normalized_condition)

    return _dedupe_conditions(normalized), warnings


def _condition_key(condition: Condition) -> tuple[str, str]:
    code_key = normalize_icd10_code(condition.icd10_code)
    if code_key:
        return ("code", code_key)
    desc_key = normalize_description(condition.icd10_description)
    if desc_key:
        return ("desc", desc_key)
    return ("cond", normalize_description(condition.condition))


def _dedupe_conditions(conditions: List[Condition]) -> List[Condition]:
    merged: List[Condition] = []
    index_by_key: dict[tuple[str, str], int] = {}

    for condition in conditions:
        key = _condition_key(condition)
        if key in index_by_key:
            idx = index_by_key[key]
            merged[idx] = _merge_conditions(merged[idx], condition)
            continue
        index_by_key[key] = len(merged)
        merged.append(condition)

    return merged


def _merge_conditions(left: Condition, right: Condition) -> Condition:
    return Condition(
        condition=_prefer_longer(left.condition, right.condition),
        icd10_code=left.icd10_code or right.icd10_code,
        icd10_description=_prefer_longer(
            left.icd10_description, right.icd10_description
        ),
        clinical_status=_prefer_longer(left.clinical_status, right.clinical_status),
        severity=_prefer_longer(left.severity, right.severity),
        confidence=_merge_confidence(left.confidence, right.confidence),
        hcc_relevant=_merge_bool(left.hcc_relevant, right.hcc_relevant),
        hcc_match=left.hcc_match or right.hcc_match,
        match_method=_merge_match_method(left.match_method, right.match_method),
    )


def _merge_bool(left: Optional[bool], right: Optional[bool]) -> Optional[bool]:
    if left is True or right is True:
        return True
    if left is False or right is False:
        return False
    return None


def _merge_match_method(left: Optional[str], right: Optional[str]) -> Optional[str]:
    if not left:
        return right
    if not right:
        return left
    priority = {
        "code": 3,
        "description_exact": 2,
        "description_partial": 1,
        "description_fuzzy": 0,
        "code_prefix_fuzzy": 0,
    }
    return left if priority.get(left, 0) >= priority.get(right, 0) else right


def _prefer_longer(left: Optional[str], right: Optional[str]) -> Optional[str]:
    if not left:
        return right
    if not right:
        return left
    return right if len(right) > len(left) else left


def _clean_text(text: str | None) -> Optional[str]:
    if not text:
        return None
    cleaned = " ".join(text.split())
    cleaned = cleaned.strip(" -:;")
    return cleaned or None


def _expand_abbreviation(text: str) -> str:
    key = re.sub(r"[^A-Za-z0-9]", "", text).lower()
    if not key:
        return text
    return ABBREVIATION_MAP.get(key, text)


def _is_valid_icd10_code(code: str | None) -> bool:
    if not code:
        return False
    normalized = normalize_icd10_code(code)
    return bool(normalized and ICD10_NORMALIZED_RE.match(normalized))


def _normalize_confidence(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = value.strip().lower()
    if cleaned in {"high", "medium", "low"}:
        return cleaned
    return None


def _merge_confidence(left: Optional[str], right: Optional[str]) -> Optional[str]:
    if not left:
        return right
    if not right:
        return left
    priority = {"high": 3, "medium": 2, "low": 1}
    return left if priority.get(left, 0) >= priority.get(right, 0) else right


def _is_empty_condition(condition: Condition) -> bool:
    return not (
        _clean_text(condition.condition)
        or _clean_text(condition.icd10_description)
        or _clean_text(condition.icd10_code)
    )
