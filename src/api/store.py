from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from google.cloud import firestore
from google.api_core import exceptions as gcloud_exceptions


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionRecord:
    id: str
    payload: dict[str, Any]


class ExecutionStore:
    def __init__(self, project_id: str, collection: str) -> None:
        if not project_id:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is required for Firestore.")
        self._client = firestore.Client(project=project_id)
        self._collection = self._client.collection(collection)

    def create_execution(self, execution_id: str, data: dict[str, Any]) -> None:
        doc_ref = self._collection.document(execution_id)
        payload = dict(data)
        payload.setdefault("submitted_at", firestore.SERVER_TIMESTAMP)
        payload.setdefault("status", "submitted")
        doc_ref.set(payload)

    def update_execution(self, execution_id: str, data: dict[str, Any]) -> None:
        payload = dict(data)
        payload["updated_at"] = firestore.SERVER_TIMESTAMP
        self._collection.document(execution_id).update(payload)

    def get_execution(self, execution_id: str) -> Optional[ExecutionRecord]:
        doc = self._collection.document(execution_id).get()
        if not doc.exists:
            return None
        return ExecutionRecord(id=doc.id, payload=doc.to_dict() or {})

    def list_executions(
        self,
        *,
        user_id: str,
        workflow_id: Optional[str],
        processed_from: Optional[datetime],
        processed_to: Optional[datetime],
        limit: int,
    ) -> list[ExecutionRecord]:
        query = self._collection.where("user_id", "==", user_id)
        if workflow_id:
            query = query.where("workflow_id", "==", workflow_id)
        if processed_from:
            query = query.where("processed_at", ">=", processed_from)
        if processed_to:
            query = query.where("processed_at", "<=", processed_to)
        if processed_from or processed_to:
            query = query.order_by("processed_at", direction=firestore.Query.DESCENDING)
        else:
            query = query.order_by("submitted_at", direction=firestore.Query.DESCENDING)
        query = query.limit(limit)
        try:
            docs = list(query.stream())
            return [ExecutionRecord(id=doc.id, payload=doc.to_dict() or {}) for doc in docs]
        except gcloud_exceptions.FailedPrecondition as exc:
            logger.warning("Firestore index missing; falling back to in-memory filtering: %s", exc)
            return _fallback_filter_executions(
                self._collection,
                user_id=user_id,
                workflow_id=workflow_id,
                processed_from=processed_from,
                processed_to=processed_to,
                limit=limit,
            )


def parse_iso_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Invalid date format. Use ISO-8601.") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def normalize_timestamps(data: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in data.items():
        if hasattr(value, "isoformat"):
            normalized[key] = value.isoformat()
        else:
            normalized[key] = value
    return normalized


def _fallback_filter_executions(
    collection: firestore.CollectionReference,
    *,
    user_id: str,
    workflow_id: Optional[str],
    processed_from: Optional[datetime],
    processed_to: Optional[datetime],
    limit: int,
) -> list[ExecutionRecord]:
    fallback_limit = max(limit, 200)
    query = (
        collection.where("user_id", "==", user_id)
        .order_by("submitted_at", direction=firestore.Query.DESCENDING)
        .limit(fallback_limit)
    )
    records = [ExecutionRecord(id=doc.id, payload=doc.to_dict() or {}) for doc in query.stream()]
    filtered = []
    for record in records:
        payload = record.payload
        if workflow_id and payload.get("workflow_id") != workflow_id:
            continue
        processed_at = _coerce_datetime(payload.get("processed_at"))
        if processed_from and (processed_at is None or processed_at < processed_from):
            continue
        if processed_to and (processed_at is None or processed_at > processed_to):
            continue
        filtered.append(record)
        if len(filtered) >= limit:
            break
    return filtered


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return None
