from __future__ import annotations

import json
import logging
from typing import Optional

from google.cloud import tasks_v2

from api.config import AppConfig


logger = logging.getLogger(__name__)


def dispatch_execution_task(
    execution_id: str,
    *,
    config: AppConfig,
) -> None:
    if not config.use_cloud_tasks:
        raise RuntimeError("Cloud Tasks dispatch requested but USE_CLOUD_TASKS is false.")
    if not (config.project_id and config.tasks_location and config.tasks_queue and config.tasks_service_url):
        raise RuntimeError("Cloud Tasks configuration is incomplete.")

    client = tasks_v2.CloudTasksClient()
    queue_path = client.queue_path(
        config.project_id,
        config.tasks_location,
        config.tasks_queue,
    )
    url = f"{config.tasks_service_url.rstrip('/')}/tasks/process"

    payload = json.dumps({"execution_id": execution_id}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if config.tasks_auth_secret:
        headers["X-Task-Secret"] = config.tasks_auth_secret

    http_request = tasks_v2.HttpRequest(
        http_method=tasks_v2.HttpMethod.POST,
        url=url,
        headers=headers,
        body=payload,
    )

    if config.tasks_service_account_email:
        http_request.oidc_token = tasks_v2.OidcToken(
            service_account_email=config.tasks_service_account_email,
            audience=config.tasks_service_url,
        )

    task = tasks_v2.Task(http_request=http_request)
    response = client.create_task(parent=queue_path, task=task)
    logger.info("Queued Cloud Task %s for execution %s", response.name, execution_id)


def verify_task_secret(config: AppConfig, provided: Optional[str]) -> bool:
    if not config.tasks_auth_secret:
        return True
    return provided == config.tasks_auth_secret
