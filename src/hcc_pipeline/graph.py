from __future__ import annotations

import logging
import os
from typing import Any, List

from typing_extensions import TypedDict

from langgraph.graph import END, StateGraph

from hcc_pipeline.config import PipelineConfig, VertexAIConfig
from hcc_pipeline.evaluation.hcc import HccCodeLookup, HccEvaluator
from hcc_pipeline.extraction.llm import LLMConditionExtractor, VertexGeminiClient
from hcc_pipeline.extraction.rule_based import RuleBasedConditionExtractor
from hcc_pipeline.models import Condition
from hcc_pipeline.utils.conditions import post_process_conditions
from hcc_pipeline.utils.text import extract_assessment_plan


logger = logging.getLogger(__name__)


class PipelineState(TypedDict):
    note_id: str
    note_text: str
    assessment_plan: str
    conditions: List[Condition]
    errors: List[str]


def build_graph(extractor, evaluator) -> Any:
    graph = StateGraph(PipelineState)

    def extract_assessment_node(state: PipelineState) -> dict:
        assessment_plan = extract_assessment_plan(state.get("note_text", ""))
        errors = list(state.get("errors", []))
        if not assessment_plan:
            errors.append("assessment_plan_not_found")
        return {"assessment_plan": assessment_plan, "errors": errors}

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

    def evaluate_hcc_node(state: PipelineState) -> dict:
        errors = list(state.get("errors", []))
        try:
            conditions = evaluator.evaluate(state.get("conditions", []))
        except Exception as exc:
            logger.exception("HCC evaluation failed: %s", exc)
            errors.append("hcc_evaluation_failed")
            conditions = state.get("conditions", [])
        return {"conditions": conditions, "errors": errors}

    graph.add_node("extract_assessment", extract_assessment_node)
    graph.add_node("extract_conditions", extract_conditions_node)
    graph.add_node("evaluate_hcc", evaluate_hcc_node)

    graph.set_entry_point("extract_assessment")
    graph.add_edge("extract_assessment", "extract_conditions")
    graph.add_edge("extract_conditions", "evaluate_hcc")
    graph.add_edge("evaluate_hcc", END)

    return graph.compile()


def get_graph() -> Any:
    pipeline_config = PipelineConfig.from_env()
    lookup = HccCodeLookup.from_csv(pipeline_config.hcc_csv_path)
    evaluator = HccEvaluator(
        lookup,
        enable_fuzzy_match=pipeline_config.enable_fuzzy_match,
        fuzzy_threshold=pipeline_config.fuzzy_match_threshold,
    )

    use_llm = os.getenv("USE_LLM", "true").lower() not in {"0", "false", "no"}
    if use_llm:
        vertex_config = VertexAIConfig.from_env()
        client = VertexGeminiClient(vertex_config)
        extractor = LLMConditionExtractor(
            client, fallback=RuleBasedConditionExtractor()
        )
    else:
        extractor = RuleBasedConditionExtractor()

    return build_graph(extractor, evaluator)
