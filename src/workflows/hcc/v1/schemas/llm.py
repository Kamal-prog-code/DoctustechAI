from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "conditions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "condition": {"type": "string"},
                    "icd10_code": {"type": "string"},
                    "icd10_description": {"type": "string"},
                    "clinical_status": {"type": "string"},
                    "severity": {"type": "string"},
                    "confidence": {"type": "string"},
                },
                "required": ["condition"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["conditions"],
    "additionalProperties": False,
}


class LLMConditionPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    condition: Optional[str] = None
    icd10_code: Optional[str] = None
    icd10_description: Optional[str] = None
    clinical_status: Optional[str] = None
    severity: Optional[str] = None
    confidence: Optional[str] = None


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    conditions: List[LLMConditionPayload] = Field(default_factory=list)
