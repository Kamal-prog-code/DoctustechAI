from __future__ import annotations

import logging
import os
from typing import Any

from langgraph.graph import END, StateGraph

from framework.llm.client import VertexGeminiClient
from framework.llm.config import VertexAIConfig
from workflows.hcc.v1.config import PipelineConfig
from workflows.hcc.v1.nodes.evaluate_hcc import build_evaluate_hcc_node
from workflows.hcc.v1.nodes.extract_assessment import extract_assessment_node
from workflows.hcc.v1.nodes.extract_conditions import build_extract_conditions_node
from workflows.hcc.v1.nodes.extract_conditions_llm import LLMConditionExtractor
from workflows.hcc.v1.nodes.extract_conditions_rule_based import RuleBasedConditionExtractor
from workflows.hcc.v1.nodes.hcc_evaluation import HccCodeLookup, HccEvaluator
from workflows.hcc.v1.schemas.llm import RESPONSE_SCHEMA
from workflows.hcc.v1.types import PipelineState


logger = logging.getLogger(__name__)


def build_graph(extractor: Any, evaluator: HccEvaluator) -> Any:
    graph = StateGraph(PipelineState)

    graph.add_node("extract_assessment", extract_assessment_node)
    graph.add_node("extract_conditions", build_extract_conditions_node(extractor))
    graph.add_node("evaluate_hcc", build_evaluate_hcc_node(evaluator))

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
        client = VertexGeminiClient(vertex_config, response_schema=RESPONSE_SCHEMA)
        extractor = LLMConditionExtractor(
            client, fallback=RuleBasedConditionExtractor()
        )
    else:
        extractor = RuleBasedConditionExtractor()

    return build_graph(extractor, evaluator)
