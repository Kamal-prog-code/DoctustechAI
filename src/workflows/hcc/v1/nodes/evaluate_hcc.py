from __future__ import annotations

import logging
from typing import Callable

from workflows.hcc.v1.nodes.hcc_evaluation import HccEvaluator
from workflows.hcc.v1.types import PipelineState


logger = logging.getLogger(__name__)


def build_evaluate_hcc_node(evaluator: HccEvaluator) -> Callable[[PipelineState], dict]:
    def evaluate_hcc_node(state: PipelineState) -> dict:
        errors = list(state.get("errors", []))
        try:
            conditions = evaluator.evaluate(state.get("conditions", []))
        except Exception as exc:
            logger.exception("HCC evaluation failed: %s", exc)
            errors.append("hcc_evaluation_failed")
            conditions = state.get("conditions", [])
        return {"conditions": conditions, "errors": errors}

    return evaluate_hcc_node
