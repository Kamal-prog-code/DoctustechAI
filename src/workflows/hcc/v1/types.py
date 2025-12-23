from __future__ import annotations

from typing import List

from typing_extensions import TypedDict

from workflows.hcc.v1.schemas.domain import Condition


class PipelineState(TypedDict):
    note_id: str
    note_text: str
    assessment_plan: str
    conditions: List[Condition]
    errors: List[str]
