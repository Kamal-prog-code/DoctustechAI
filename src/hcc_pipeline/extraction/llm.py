from __future__ import annotations

import ast
import json
import logging
import os
import re
import warnings
from pathlib import Path
from typing import Any, List, Optional, Tuple

from google.oauth2 import service_account
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential
import vertexai
from vertexai.preview.generative_models import GenerationConfig, GenerativeModel

from hcc_pipeline.config import VertexAIConfig
from hcc_pipeline.extraction.prompt import PROMPT_TEMPLATE
from hcc_pipeline.models import Condition


logger = logging.getLogger(__name__)

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "conditions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "condition": {"type": "string"},
                    "icd10_code": {"type": "string"},
                    "icd10_description": {"type": "string"},
                    "clinical_status": {"type": "string"},
                    "severity": {"type": "string"},
                    "confidence": {"type": "string"},
                },
                "required": ["condition"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["conditions"],
    "additionalProperties": False,
}

REPAIR_PROMPT_TEMPLATE = """You repair malformed JSON into valid JSON.
Return ONLY a JSON object matching this schema:
{{
  "conditions": [
    {{
      "condition": "string",
      "icd10_code": "string or null",
      "icd10_description": "string or null",
      "clinical_status": "string or null",
      "severity": "string or null",
      "confidence": "high|medium|low"
    }}
  ]
}}

If you cannot repair, return {{"conditions": []}}.

Raw response:
\"\"\"{raw}\"\"\"
"""


class LLMConditionPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    condition: Optional[str] = None
    icd10_code: Optional[str] = None
    icd10_description: Optional[str] = None
    clinical_status: Optional[str] = None
    severity: Optional[str] = None
    confidence: Optional[str] = None


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    conditions: List[LLMConditionPayload] = Field(default_factory=list)


class VertexGeminiClient:
    def __init__(self, config: VertexAIConfig) -> None:
        _suppress_vertex_warnings()
        credentials = service_account.Credentials.from_service_account_file(
            str(config.credentials_path)
        )
        vertexai.init(
            project=config.project_id,
            location=config.location,
            credentials=credentials,
        )
        self._model = GenerativeModel(config.model_name)
        self._generation_config = _build_generation_config(config)

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
    def generate(self, prompt: str) -> str:
        response = self._model.generate_content(
            prompt, generation_config=self._generation_config
        )
        return getattr(response, "text", "") or ""


class LLMConditionExtractor:
    def __init__(
        self,
        client: VertexGeminiClient,
        fallback: Optional[Any] = None,
        max_chars: int = 6000,
    ) -> None:
        self._client = client
        self._fallback = fallback
        self._max_chars = max_chars
        self._debug_dir = os.getenv("LLM_DEBUG_DIR")
        self._repair_invalid_json = _parse_bool_env(
            os.getenv("LLM_ENABLE_REPAIR", "true")
        )
        self._repair_max_chars = int(os.getenv("LLM_REPAIR_MAX_CHARS", "6000"))
        self._log_verbose = _parse_bool_env(os.getenv("LLM_LOG_VERBOSE", "false"))

    def extract(self, assessment_text: str, note_id: str | None = None) -> List[Condition]:
        if not assessment_text.strip():
            return []

        prompt_text = assessment_text.strip()
        if len(prompt_text) > self._max_chars:
            prompt_text = prompt_text[: self._max_chars]
            logger.warning("Truncated assessment/plan for note %s", note_id or "")

        prompt = PROMPT_TEMPLATE.format(assessment_plan=prompt_text)

        try:
            raw = self._client.generate(prompt)
            parsed, parse_error = _parse_llm_json(raw)
            conditions = _conditions_from_payload(parsed)
            if parse_error and not conditions and self._repair_invalid_json:
                repaired_conditions = self._attempt_json_repair(raw, note_id)
                if repaired_conditions:
                    return repaired_conditions

            if parse_error and not conditions and self._fallback:
                self._log_issue(
                    "LLM returned invalid JSON for %s, using fallback.", note_id
                )
                self._write_debug_output(note_id, raw, suffix="invalid_json")
                return self._fallback.extract(assessment_text, note_id=note_id)
            if parse_error:
                logger.debug("LLM response required JSON salvage for %s.", note_id)
                self._write_debug_output(note_id, raw, suffix="salvaged_json")
            if not conditions and self._fallback:
                self._log_issue(
                    "LLM returned empty conditions for %s, using fallback.", note_id
                )
                self._write_debug_output(note_id, raw, suffix="empty_conditions")
                return self._fallback.extract(assessment_text, note_id=note_id)
            return conditions
        except Exception as exc:
            logger.exception("LLM extraction failed for %s: %s", note_id, exc)
            if self._fallback:
                return self._fallback.extract(assessment_text, note_id=note_id)
            return []

    def _write_debug_output(self, note_id: str | None, raw: str, suffix: str) -> None:
        if not self._debug_dir:
            return
        safe_note_id = _safe_note_id(note_id)
        debug_dir = _ensure_debug_dir(self._debug_dir)
        filename = _debug_filename(safe_note_id, suffix)
        _write_text(debug_dir / filename, raw)

    def _attempt_json_repair(
        self, raw: str, note_id: str | None
    ) -> List[Condition]:
        trimmed_raw = raw.strip()
        if not trimmed_raw:
            return []
        if len(trimmed_raw) > self._repair_max_chars:
            trimmed_raw = trimmed_raw[: self._repair_max_chars]
        prompt = REPAIR_PROMPT_TEMPLATE.format(raw=trimmed_raw)
        try:
            repaired = self._client.generate(prompt)
        except Exception as exc:
            logger.info("LLM repair failed for %s: %s", note_id, exc)
            return []

        parsed, parse_error = _parse_llm_json(repaired)
        conditions = _conditions_from_payload(parsed)
        if parse_error:
            logger.debug("LLM repair response required JSON salvage for %s.", note_id)
        if conditions:
            self._write_debug_output(note_id, repaired, suffix="repaired_json")
        return conditions

    def _log_issue(self, message: str, note_id: str | None) -> None:
        if self._log_verbose:
            logger.warning(message, note_id)
        else:
            logger.debug(message, note_id)


def _parse_llm_json(text: str) -> Tuple[LLMResponse, bool]:
    text = _strip_code_fence(text.strip())
    cleaned_text = _sanitize_json_text(text)
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


def _extract_json_payload(text: str) -> dict[str, Any]:
    text = _strip_code_fence(text.strip())
    if not text:
        return {"conditions": []}

    payload = _parse_json_like(text)
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list):
        return {"conditions": payload}

    best: dict[str, Any] | None = None
    for candidate in _iter_json_candidates(text):
        payload = _parse_json_like(candidate)
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


def _conditions_from_payload(payload: LLMResponse) -> List[Condition]:
    conditions: List[Condition] = []
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


def _nullify(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _sanitize_json_text(text: str) -> str:
    text = text.replace("\u201c", "\"").replace("\u201d", "\"")
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = re.sub(r"\bNULL\b", "null", text, flags=re.IGNORECASE)
    text = re.sub(r"\bNONE\b", "null", text, flags=re.IGNORECASE)
    text = re.sub(r"\bN/A\b", "null", text, flags=re.IGNORECASE)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    text = re.sub(
        r'([{\[,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:',
        r'\1"\2":',
        text,
    )
    return text


def _parse_json_like(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        pass
    cleaned = _sanitize_json_text(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    try:
        return ast.literal_eval(cleaned)
    except (ValueError, SyntaxError):
        return None


def _parse_bool_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _suppress_vertex_warnings() -> None:
    if not _parse_bool_env(os.getenv("SUPPRESS_VERTEXAI_WARNINGS", "true")):
        return
    warnings.filterwarnings(
        "ignore",
        message=r"This feature is deprecated as of June 24, 2025.*",
        category=UserWarning,
        module=r"vertexai\..*",
    )


def _build_generation_config(config: VertexAIConfig) -> GenerationConfig:
    use_schema = _parse_bool_env(os.getenv("LLM_USE_RESPONSE_SCHEMA", "true"))
    if use_schema:
        try:
            return GenerationConfig(
                temperature=config.temperature,
                max_output_tokens=config.max_output_tokens,
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
            )
        except TypeError:
            pass

    try:
        return GenerationConfig(
            temperature=config.temperature,
            max_output_tokens=config.max_output_tokens,
            response_mime_type="application/json",
        )
    except TypeError:
        return GenerationConfig(
            temperature=config.temperature,
            max_output_tokens=config.max_output_tokens,
        )


def _strip_code_fence(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


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


def _iter_json_candidates(text: str) -> List[str]:
    candidates: list[str] = []
    for open_char, close_char in (("{", "}"), ("[", "]")):
        depth = 0
        start = None
        for idx, char in enumerate(text):
            if char == open_char:
                if depth == 0:
                    start = idx
                depth += 1
            elif char == close_char and depth:
                depth -= 1
                if depth == 0 and start is not None:
                    candidates.append(text[start : idx + 1])
                    start = None
    return candidates


def _coerce_llm_response(payload: Any) -> LLMResponse:
    normalized = _normalize_payload(payload)
    items = []
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


def _canonical_key(key: Any) -> Optional[str]:
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


def _safe_note_id(note_id: str | None) -> str:
    if not note_id:
        return "unknown_note"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", note_id)


def _ensure_debug_dir(path: str) -> Path:
    debug_dir = Path(path)
    debug_dir.mkdir(parents=True, exist_ok=True)
    return debug_dir


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _timestamp() -> str:
    return f"{int(os.times().elapsed)}"


def _debug_filename(note_id: str, suffix: str) -> str:
    return f"{note_id}.{suffix}.{_timestamp()}.txt"
