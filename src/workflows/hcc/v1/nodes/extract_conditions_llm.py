from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from framework.llm.client import LLMClient
from framework.utils.env import parse_bool_env
from hcc_pipeline.models import Condition
from workflows.hcc.v1.nodes.llm_parsing import conditions_from_payload, parse_llm_json
from workflows.hcc.v1.prompt_templates.conditions_extraction import PROMPT_TEMPLATE
from workflows.hcc.v1.prompt_templates.json_repair import REPAIR_PROMPT_TEMPLATE


logger = logging.getLogger(__name__)


class LLMConditionExtractor:
    def __init__(
        self,
        client: LLMClient,
        fallback: Optional[Any] = None,
        max_chars: int = 6000,
    ) -> None:
        self._client = client
        self._fallback = fallback
        self._max_chars = max_chars
        self._debug_dir = os.getenv("LLM_DEBUG_DIR")
        self._repair_invalid_json = parse_bool_env(
            os.getenv("LLM_ENABLE_REPAIR", "true")
        )
        self._repair_max_chars = int(os.getenv("LLM_REPAIR_MAX_CHARS", "6000"))
        self._log_verbose = parse_bool_env(os.getenv("LLM_LOG_VERBOSE", "false"))

    def extract(self, assessment_text: str, note_id: str | None = None) -> list[Condition]:
        if not assessment_text.strip():
            return []

        prompt_text = assessment_text.strip()
        if len(prompt_text) > self._max_chars:
            prompt_text = prompt_text[: self._max_chars]
            logger.warning("Truncated assessment/plan for note %s", note_id or "")

        prompt = PROMPT_TEMPLATE.format(assessment_plan=prompt_text)

        try:
            raw = self._client.generate(prompt)
            parsed, parse_error = parse_llm_json(raw)
            conditions = conditions_from_payload(parsed)
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

    def _attempt_json_repair(self, raw: str, note_id: str | None) -> list[Condition]:
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

        parsed, parse_error = parse_llm_json(repaired)
        conditions = conditions_from_payload(parsed)
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


def _safe_note_id(note_id: str | None) -> str:
    if not note_id:
        return "unknown_note"
    return "".join(char if char.isalnum() or char in "_.-" else "_" for char in note_id)


def _ensure_debug_dir(path: str) -> Path:
    debug_dir = Path(path)
    debug_dir.mkdir(parents=True, exist_ok=True)
    return debug_dir


def _debug_filename(note_id: str, suffix: str) -> str:
    return f"{note_id}_{suffix}.txt"


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
