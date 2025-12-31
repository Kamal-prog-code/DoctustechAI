from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional


def _get_env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class AppConfig:
    project_id: str
    firebase_project_id: Optional[str]
    firebase_service_account: Optional[str]
    firestore_collection: str
    input_bucket: Optional[str]
    tasks_location: Optional[str]
    tasks_queue: Optional[str]
    tasks_service_url: Optional[str]
    tasks_service_account_email: Optional[str]
    tasks_auth_secret: Optional[str]
    use_cloud_tasks: bool
    auth_disabled: bool
    cors_origins: List[str]


def load_config() -> AppConfig:
    project_id = (
        os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCP_PROJECT")
        or os.getenv("PROJECT_ID")
        or os.getenv("FIREBASE_PROJECT_ID")
        or ""
    )

    return AppConfig(
        project_id=project_id,
        firebase_project_id=os.getenv("FIREBASE_PROJECT_ID"),
        firebase_service_account=os.getenv("FIREBASE_SERVICE_ACCOUNT"),
        firestore_collection=os.getenv("FIRESTORE_COLLECTION", "workflow_executions"),
        input_bucket=os.getenv("INPUT_BUCKET"),
        tasks_location=os.getenv("TASKS_LOCATION"),
        tasks_queue=os.getenv("TASKS_QUEUE"),
        tasks_service_url=os.getenv("TASKS_SERVICE_URL"),
        tasks_service_account_email=os.getenv("TASKS_SERVICE_ACCOUNT_EMAIL"),
        tasks_auth_secret=os.getenv("TASKS_AUTH_SECRET"),
        use_cloud_tasks=_get_env_bool("USE_CLOUD_TASKS", default=False),
        auth_disabled=_get_env_bool("AUTH_DISABLED", default=False),
        cors_origins=_split_csv(os.getenv("CORS_ORIGINS", "*")),
    )
