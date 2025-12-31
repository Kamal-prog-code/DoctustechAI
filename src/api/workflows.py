from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List

from workflows.hcc.v1.runner import run_note_text


@dataclass(frozen=True)
class WorkflowInputSpec:
    name: str
    description: str
    type: str
    required: bool
    multiple: bool


@dataclass(frozen=True)
class WorkflowDefinition:
    id: str
    name: str
    description: str
    inputs: List[WorkflowInputSpec]


WORKFLOWS: List[WorkflowDefinition] = [
    WorkflowDefinition(
        id="hcc_v1",
        name="HCC Extraction v1",
        description="Extract conditions and HCC-relevant ICD-10 codes from progress notes.",
        inputs=[
            WorkflowInputSpec(
                name="progress_notes",
                description="Clinical progress notes (text or .txt/.md file).",
                type="text",
                required=True,
                multiple=True,
            )
        ],
    )
]

WORKFLOW_RUNNERS: Dict[str, Callable[[str, str, str], object]] = {
    "hcc_v1": run_note_text,
}


def list_workflows() -> List[WorkflowDefinition]:
    return WORKFLOWS


def get_workflow(workflow_id: str) -> WorkflowDefinition:
    for workflow in WORKFLOWS:
        if workflow.id == workflow_id:
            return workflow
    raise KeyError(f"Unknown workflow: {workflow_id}")


def get_runner(workflow_id: str) -> Callable[[str, str, str], object]:
    if workflow_id not in WORKFLOW_RUNNERS:
        raise KeyError(f"No runner for workflow: {workflow_id}")
    return WORKFLOW_RUNNERS[workflow_id]
