from __future__ import annotations

import logging
import uuid
from typing import List, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from api.auth import AuthenticatedUser, get_current_user
from api.config import load_config
from api.processing import mark_execution_failed, process_execution
from api.schemas import (
    ExecutionCreateResponse,
    ExecutionDetailSchema,
    ExecutionSummarySchema,
    HealthResponse,
    TaskRequest,
    WorkflowSchema,
)
from api.store import ExecutionRecord, ExecutionStore, normalize_timestamps, parse_iso_date
from api.storage import InputStorage
from api.tasks import dispatch_execution_task, verify_task_secret
from api.workflows import WorkflowDefinition, get_workflow, list_workflows


logger = logging.getLogger(__name__)

config = load_config()
store = ExecutionStore(config.project_id, config.firestore_collection)
input_storage = InputStorage(config)

app = FastAPI(title="HCC Workflow API", version="2.0")


def _configure_cors() -> None:
    origins = config.cors_origins
    if origins == ["*"]:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    elif origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )


_configure_cors()


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/api/workflows", response_model=List[WorkflowSchema])
def workflows(user: AuthenticatedUser = Depends(get_current_user)) -> List[WorkflowSchema]:
    return [_workflow_to_schema(workflow) for workflow in list_workflows()]


@app.post("/api/executions", response_model=ExecutionCreateResponse)
async def create_executions(
    background_tasks: BackgroundTasks,
    workflow_id: str = Form(...),
    notes: List[UploadFile] = File(...),
    user: AuthenticatedUser = Depends(get_current_user),
) -> ExecutionCreateResponse:
    # Create one execution per uploaded note, then processing.
    try:
        workflow = get_workflow(workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if not notes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No inputs uploaded.")

    created: List[ExecutionSummarySchema] = []
    for upload in notes:
        execution_id = uuid.uuid4().hex
        input_ref = input_storage.save_upload(upload, execution_id)
        payload = {
            "workflow_id": workflow.id,
            "workflow_name": workflow.name,
            "note_id": upload.filename or execution_id,
            "user_id": user.uid,
            "input_ref": input_ref.__dict__,
            "status": "submitted",
        }
        store.create_execution(execution_id, payload)

        if config.use_cloud_tasks:
            dispatch_execution_task(execution_id, config=config)
        else:
            background_tasks.add_task(_process_execution_safe, execution_id)

        created.append(
            ExecutionSummarySchema(
                id=execution_id,
                workflow_id=workflow.id,
                workflow_name=workflow.name,
                note_id=payload["note_id"],
                status="submitted",
                input_ref=input_ref.__dict__,
            )
        )

    return ExecutionCreateResponse(executions=created)


@app.get("/api/executions", response_model=List[ExecutionSummarySchema])
def list_executions(
    workflow_id: Optional[str] = None,
    processed_from: Optional[str] = None,
    processed_to: Optional[str] = None,
    limit: int = 50,
    user: AuthenticatedUser = Depends(get_current_user),
) -> List[ExecutionSummarySchema]:
    # Users only see their own executions and filtering happens in Firestore.
    if limit > 200:
        limit = 200
    try:
        parsed_from = parse_iso_date(processed_from)
        parsed_to = parse_iso_date(processed_to)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    records = store.list_executions(
        user_id=user.uid,
        workflow_id=workflow_id,
        processed_from=parsed_from,
        processed_to=parsed_to,
        limit=limit,
    )
    return [_record_to_summary(record) for record in records]


@app.get("/api/executions/{execution_id}", response_model=ExecutionDetailSchema)
def get_execution(
    execution_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> ExecutionDetailSchema:
    # Return details for a single execution, scoped to the authenticated user.
    record = store.get_execution(execution_id)
    if not record or record.payload.get("user_id") != user.uid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found.")
    return _record_to_detail(record)


@app.post("/tasks/process")
def task_process(
    payload: TaskRequest,
    x_task_secret: Optional[str] = Header(None),
) -> dict[str, str]:
    # Cloud Tasks hits this endpoint to process queued executions.
    if not verify_task_secret(config, x_task_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid task secret.")

    try:
        process_execution(payload.execution_id, store=store, storage=input_storage)
    except Exception as exc:
        logger.exception("Execution failed for %s: %s", payload.execution_id, exc)
        mark_execution_failed(payload.execution_id, store=store, error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Execution failed.") from exc
    return {"status": "ok"}


def _process_execution_safe(execution_id: str) -> None:
    try:
        process_execution(execution_id, store=store, storage=input_storage)
    except Exception as exc:
        logger.exception("Execution failed for %s: %s", execution_id, exc)
        mark_execution_failed(execution_id, store=store, error=str(exc))


def _workflow_to_schema(workflow: WorkflowDefinition) -> WorkflowSchema:
    return WorkflowSchema(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        inputs=[
            {
                "name": spec.name,
                "description": spec.description,
                "type": spec.type,
                "required": spec.required,
                "multiple": spec.multiple,
            }
            for spec in workflow.inputs
        ],
    )


def _record_to_summary(record: ExecutionRecord) -> ExecutionSummarySchema:
    payload = normalize_timestamps(record.payload)
    return ExecutionSummarySchema(
        id=record.id,
        workflow_id=payload.get("workflow_id", ""),
        workflow_name=payload.get("workflow_name", ""),
        note_id=payload.get("note_id", record.id),
        status=payload.get("status", "unknown"),
        input_ref=payload.get("input_ref"),
        submitted_at=payload.get("submitted_at"),
        processed_at=payload.get("processed_at"),
        error=payload.get("error"),
    )


def _record_to_detail(record: ExecutionRecord) -> ExecutionDetailSchema:
    payload = normalize_timestamps(record.payload)
    return ExecutionDetailSchema(
        id=record.id,
        workflow_id=payload.get("workflow_id", ""),
        workflow_name=payload.get("workflow_name", ""),
        note_id=payload.get("note_id", record.id),
        status=payload.get("status", "unknown"),
        input_ref=payload.get("input_ref"),
        submitted_at=payload.get("submitted_at"),
        processed_at=payload.get("processed_at"),
        error=payload.get("error"),
        output=payload.get("output"),
    )
