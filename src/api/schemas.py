from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class WorkflowInputSpecSchema(BaseModel):
    name: str
    description: str
    type: str
    required: bool
    multiple: bool


class WorkflowSchema(BaseModel):
    id: str
    name: str
    description: str
    inputs: List[WorkflowInputSpecSchema]


class InputReferenceSchema(BaseModel):
    uri: str
    filename: str
    content_type: str
    size_bytes: int


class ExecutionSummarySchema(BaseModel):
    id: str
    workflow_id: str
    workflow_name: str
    note_id: str
    status: str
    input_ref: Optional[InputReferenceSchema] = None
    submitted_at: Optional[str] = None
    processed_at: Optional[str] = None
    error: Optional[str] = None


class ExecutionDetailSchema(ExecutionSummarySchema):
    output: Optional[dict[str, Any]] = None


class ExecutionCreateResponse(BaseModel):
    executions: List[ExecutionSummarySchema]


class TaskRequest(BaseModel):
    execution_id: str


class HealthResponse(BaseModel):
    status: str = "ok"
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
