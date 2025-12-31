from __future__ import annotations

import logging
from typing import Any

from api.store import ExecutionStore
from api.storage import InputStorage
from api.workflows import get_runner


logger = logging.getLogger(__name__)


def process_execution(
    execution_id: str,
    *,
    store: ExecutionStore,
    storage: InputStorage,
) -> dict[str, Any]:
    record = store.get_execution(execution_id)
    if not record:
        raise RuntimeError(f"Execution not found: {execution_id}")

    payload = record.payload
    workflow_id = payload.get("workflow_id")
    input_ref = payload.get("input_ref", {})
    input_uri = input_ref.get("uri")
    note_id = payload.get("note_id") or execution_id

    if not workflow_id or not input_uri:
        raise RuntimeError(f"Execution {execution_id} missing workflow/input data")

    store.update_execution(execution_id, {"status": "processing", "started_at": _server_timestamp_marker()})

    runner = get_runner(workflow_id)
    note_text = storage.load_text(input_uri)
    result = runner(note_text, note_id, input_ref.get("filename") or "uploaded_note")
    result_payload = result.model_dump(mode="json")

    store.update_execution(
        execution_id,
        {
            "status": "complete",
            "processed_at": _server_timestamp_marker(),
            "output": result_payload,
            "error": None,
        },
    )

    return result_payload


def mark_execution_failed(execution_id: str, *, store: ExecutionStore, error: str) -> None:
    store.update_execution(
        execution_id,
        {"status": "failed", "processed_at": _server_timestamp_marker(), "error": error},
    )


def _server_timestamp_marker() -> Any:
    from google.cloud import firestore

    return firestore.SERVER_TIMESTAMP
