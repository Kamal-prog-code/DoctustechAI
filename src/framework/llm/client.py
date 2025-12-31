from __future__ import annotations

import os
import warnings
from typing import Any, Protocol

from google.oauth2 import service_account
from tenacity import retry, stop_after_attempt, wait_exponential
import vertexai
from vertexai.preview.generative_models import GenerationConfig, GenerativeModel

from framework.llm.config import VertexAIConfig
from framework.utils.env import parse_bool_env


class LLMClient(Protocol):
    def generate(self, prompt: str) -> str:  # pragma: no cover - interface only
        ...


def suppress_vertex_warnings() -> None:
    if not parse_bool_env(os.getenv("SUPPRESS_VERTEXAI_WARNINGS", "true")):
        return
    warnings.filterwarnings(
        "ignore",
        message=r"This feature is deprecated as of June 24, 2025.*",
        category=UserWarning,
        module=r"vertexai\..*",
    )


def build_generation_config(
    config: VertexAIConfig,
    response_schema: dict[str, Any] | None = None,
    response_mime_type: str | None = "application/json",
) -> GenerationConfig:
    use_schema = parse_bool_env(os.getenv("LLM_USE_RESPONSE_SCHEMA", "true"))
    if response_schema and response_mime_type and use_schema:
        try:
            return GenerationConfig(
                temperature=config.temperature,
                max_output_tokens=config.max_output_tokens,
                response_mime_type=response_mime_type,
                response_schema=response_schema,
            )
        except TypeError:
            pass

    if response_mime_type:
        try:
            return GenerationConfig(
                temperature=config.temperature,
                max_output_tokens=config.max_output_tokens,
                response_mime_type=response_mime_type,
            )
        except TypeError:
            pass

    return GenerationConfig(
        temperature=config.temperature,
        max_output_tokens=config.max_output_tokens,
    )


class VertexGeminiClient:
    def __init__(
        self,
        config: VertexAIConfig,
        response_schema: dict[str, Any] | None = None,
        response_mime_type: str | None = "application/json",
    ) -> None:
        suppress_vertex_warnings()
        credentials = None
        if config.credentials_path:
            credentials = service_account.Credentials.from_service_account_file(
                str(config.credentials_path)
            )
        vertexai.init(
            project=config.project_id,
            location=config.location,
            credentials=credentials,
        )
        self._model = GenerativeModel(config.model_name)
        self._generation_config = build_generation_config(
            config,
            response_schema=response_schema,
            response_mime_type=response_mime_type,
        )

    @retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(3))
    def generate(self, prompt: str) -> str:
        response = self._model.generate_content(
            prompt, generation_config=self._generation_config
        )
        return getattr(response, "text", "") or ""
