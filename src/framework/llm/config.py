from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class VertexAIConfig:
    project_id: str
    location: str
    credentials_path: Path
    model_name: str
    temperature: float
    max_output_tokens: int

    @classmethod
    def from_env(cls) -> "VertexAIConfig":
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("VERTEX_PROJECT_ID")
        location = (
            os.getenv("GOOGLE_CLOUD_LOCATION")
            or os.getenv("VERTEX_LOCATION")
            or "us-central1"
        )
        credentials_path_str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        model_name = os.getenv("VERTEX_MODEL_NAME", "gemini-2.5-flash")

        if not project_id:
            raise ValueError(
                "GOOGLE_CLOUD_PROJECT (or VERTEX_PROJECT_ID) must be set."
            )
        if not credentials_path_str:
            raise ValueError("GOOGLE_APPLICATION_CREDENTIALS must be set.")

        credentials_path = Path(credentials_path_str)
        if not credentials_path.exists():
            raise FileNotFoundError(
                f"GOOGLE_APPLICATION_CREDENTIALS not found: {credentials_path}"
            )

        temperature = float(os.getenv("VERTEX_TEMPERATURE", "0.0"))
        max_output_tokens = int(os.getenv("VERTEX_MAX_OUTPUT_TOKENS", "1024"))

        return cls(
            project_id=project_id,
            location=location,
            credentials_path=credentials_path,
            model_name=model_name,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
