from __future__ import annotations

from framework.llm.client import VertexGeminiClient as _VertexGeminiClient
from framework.llm.config import VertexAIConfig
from workflows.hcc.v1.nodes.extract_conditions_llm import LLMConditionExtractor
from workflows.hcc.v1.schemas.llm import RESPONSE_SCHEMA


class VertexGeminiClient(_VertexGeminiClient):
    def __init__(
        self,
        config: VertexAIConfig,
        response_schema: dict | None = RESPONSE_SCHEMA,
        response_mime_type: str | None = "application/json",
    ) -> None:
        super().__init__(
            config,
            response_schema=response_schema,
            response_mime_type=response_mime_type,
        )


__all__ = ["LLMConditionExtractor", "VertexGeminiClient"]
