from __future__ import annotations

from workflows.hcc.v1.types import PipelineState
from hcc_pipeline.utils.text import extract_assessment_plan


def extract_assessment_node(state: PipelineState) -> dict:
    assessment_plan = extract_assessment_plan(state.get("note_text", ""))
    errors = list(state.get("errors", []))
    if not assessment_plan:
        errors.append("assessment_plan_not_found")
    return {"assessment_plan": assessment_plan, "errors": errors}
