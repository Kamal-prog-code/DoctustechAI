from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from workflows.hcc.v1.orchestrator import get_graph
from workflows.hcc.v1.schemas.domain import NoteResult


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _graph() -> Any:
    return get_graph()


def run_note_text(note_text: str, note_id: str, source_file: str) -> NoteResult:
    state = {
        "note_id": note_id,
        "note_text": note_text,
        "assessment_plan": "",
        "conditions": [],
        "errors": [],
    }
    try:
        result_state = _graph().invoke(state)
        return NoteResult(
            note_id=note_id,
            source_file=source_file,
            assessment_plan=result_state.get("assessment_plan", ""),
            conditions=result_state.get("conditions", []),
            errors=result_state.get("errors", []),
        )
    except Exception as exc:
        logger.exception("Failed processing %s: %s", note_id, exc)
        return NoteResult(
            note_id=note_id,
            source_file=source_file,
            assessment_plan="",
            conditions=[],
            errors=["note_processing_failed"],
        )
