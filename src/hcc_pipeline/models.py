from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field


class HccMatch(BaseModel):
    code: str
    description: str
    tags: Optional[str] = None


class Condition(BaseModel):
    condition: str
    icd10_code: Optional[str] = None
    icd10_description: Optional[str] = None
    clinical_status: Optional[str] = None
    severity: Optional[str] = None
    confidence: Optional[str] = None
    hcc_relevant: Optional[bool] = None
    hcc_match: Optional[HccMatch] = None
    match_method: Optional[str] = None


class NoteResult(BaseModel):
    note_id: str
    source_file: str
    assessment_plan: str
    conditions: List[Condition]
    errors: List[str] = Field(default_factory=list)
    created_at: str = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc).isoformat()
    )
