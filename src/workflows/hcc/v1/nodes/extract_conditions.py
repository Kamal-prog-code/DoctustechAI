from __future__ import annotations

import logging
from typing import Any, Callable

from workflows.hcc.v1.nodes.conditions_utils import post_process_conditions
from workflows.hcc.v1.types import PipelineState


logger = logging.getLogger(__name__)


def build_extract_conditions_node(extractor: Any) -> Callable[[PipelineState], dict]:
    def extract_conditions_node(state: PipelineState) -> dict:
        errors = list(state.get("errors", []))
        note_id = state.get("note_id")
        try:
            conditions = extractor.extract(state.get("assessment_plan", ""), note_id=note_id)
            conditions, warnings = post_process_conditions(conditions)
            for warning in warnings:
                if warning not in errors:
                    errors.append(warning)
        except Exception as exc:
            logger.exception("Condition extraction failed for %s: %s", note_id, exc)
            errors.append("condition_extraction_failed")
            conditions = []
        return {"conditions": conditions, "errors": errors}

    return extract_conditions_node
