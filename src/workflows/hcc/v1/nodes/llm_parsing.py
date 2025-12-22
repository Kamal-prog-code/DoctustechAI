from __future__ import annotations

import json
import re
from typing import Any, Tuple

from pydantic import ValidationError

from framework.llm.json_utils import (
    iter_json_candidates,
    parse_json_like,
    sanitize_json_text,
    strip_code_fence,
)
from hcc_pipeline.models import Condition
from workflows.hcc.v1.schemas.llm import LLMConditionPayload, LLMResponse


def parse_llm_json(text: str) -> Tuple[LLMResponse, bool]:
    text = strip_code_fence(text.strip())
    cleaned_text = sanitize_json_text(text)
    for candidate in (text, cleaned_text):
        if not candidate:
            continue
        try:
            if candidate.lstrip().startswith("["):
                payload = json.loads(candidate)
                payload = _normalize_payload(payload)
                return _coerce_llm_response(payload), False
            return LLMResponse.model_validate_json(candidate), False
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError):
            pass
    try:
        return LLMResponse.model_validate_json(text), False
    except (ValidationError, ValueError, TypeError):
        pass

    parse_error = False
    payload = _parse_json_like(text)
    if payload is None:
        parse_error = True
        payload = _extract_json_payload(text)

    payload = _normalize_payload(payload)
    response = _coerce_llm_response(payload)
    if response.conditions:
        return response, parse_error
    parse_error = True
    return response, parse_error


def conditions_from_payload(payload: LLMResponse) -> list[Condition]:
    conditions: list[Condition] = []
    for item in payload.conditions:
        condition_name = (item.condition or "").strip()
        if not condition_name:
            condition_name = (item.icd10_description or "").strip()
        if not condition_name:
            condition_name = (item.icd10_code or "").strip()
        if not condition_name:
            continue
        conditions.append(
            Condition(
                condition=condition_name,
                icd10_code=_nullify(item.icd10_code),
                icd10_description=_nullify(item.icd10_description),
                clinical_status=_nullify(item.clinical_status),
                severity=_nullify(item.severity),
                confidence=_nullify(item.confidence),
            )
        )
    return conditions


def _nullify(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_json_like(text: str) -> Any:
    return parse_json_like(text)


def _extract_json_payload(text: str) -> dict[str, Any]:
    text = strip_code_fence(text.strip())
    if not text:
        return {"conditions": []}

    payload = parse_json_like(text)
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        return {"conditions": payload}

    best: dict[str, Any] | None = None
    for candidate in iter_json_candidates(text):
        payload = parse_json_like(candidate)
        if payload is None:
            continue
        payload = _normalize_payload(payload)
        if isinstance(payload, dict):
            if "conditions" in payload:
                return payload
            if best is None:
                best = payload
        elif isinstance(payload, list):
            if payload:
                return {"conditions": payload}
            if best is None:
                best = {"conditions": payload}

    if best is not None:
        return best
    return {"conditions": []}


def _normalize_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        if "conditions" in payload:
            return payload
        for key, value in payload.items():
            if isinstance(key, str) and key.lower() == "conditions":
                return {"conditions": value}
        for key, value in payload.items():
            if isinstance(key, str) and key.lower() in {"items", "results", "data"}:
                return {"conditions": value}
        if _looks_like_condition(payload):
            return {"conditions": [payload]}
        return payload
    if isinstance(payload, list):
        return {"conditions": payload}
    return payload


def _coerce_llm_response(payload: Any) -> LLMResponse:
    normalized = _normalize_payload(payload)
    if isinstance(normalized, dict):
        raw_items = normalized.get("conditions", [])
    elif isinstance(normalized, list):
        raw_items = normalized
    else:
        raw_items = []

    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    if not isinstance(raw_items, list):
        raw_items = []

    items: list[LLMConditionPayload] = []
    for item in raw_items:
        normalized_item = _normalize_condition_item(item)
        if not normalized_item:
            continue
        try:
            items.append(LLMConditionPayload.model_validate(normalized_item))
        except ValidationError:
            continue
    return LLMResponse(conditions=items)


def _normalize_condition_item(item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        return {"condition": item}
    if not isinstance(item, dict):
        return {}

    normalized: dict[str, Any] = {}
    for key, value in item.items():
        canonical = _canonical_key(key)
        if not canonical:
            continue
        if canonical == "icd10_code" and isinstance(value, dict):
            code_value = value.get("code") or value.get("value")
            desc_value = value.get("description") or value.get("desc")
            if code_value:
                normalized["icd10_code"] = code_value
            if desc_value and not normalized.get("icd10_description"):
                normalized["icd10_description"] = desc_value
            continue
        normalized[canonical] = value
    return normalized


def _canonical_key(key: Any) -> str | None:
    if not isinstance(key, str):
        return None
    cleaned = re.sub(r"[^A-Za-z0-9]", "", key).lower()
    return {
        "condition": "condition",
        "conditionname": "condition",
        "name": "condition",
        "diagnosis": "condition",
        "dx": "condition",
        "problem": "condition",
        "problemname": "condition",
        "icd10": "icd10_code",
        "icd10code": "icd10_code",
        "icd10cm": "icd10_code",
        "code": "icd10_code",
        "icd10description": "icd10_description",
        "icd10desc": "icd10_description",
        "description": "icd10_description",
        "desc": "icd10_description",
        "clinicalstatus": "clinical_status",
        "status": "clinical_status",
        "severity": "severity",
        "confidence": "confidence",
    }.get(cleaned)


def _looks_like_condition(payload: dict[str, Any]) -> bool:
    for key in payload.keys():
        if _canonical_key(key):
            return True
    return False
