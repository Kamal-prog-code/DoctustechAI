from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from fastapi import HTTPException, Request, status

from api.config import AppConfig, load_config


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthenticatedUser:
    uid: str
    email: Optional[str]
    name: Optional[str]


_config = load_config()
_firebase_init_lock = threading.Lock()


def _init_firebase(config: AppConfig) -> None:
    if firebase_admin._apps:
        return

    with _firebase_init_lock:
        if firebase_admin._apps:
            return

        if config.firebase_service_account:
            cred = credentials.Certificate(config.firebase_service_account)
        else:
            cred = credentials.ApplicationDefault()

        firebase_admin.initialize_app(
            cred,
            {"projectId": config.firebase_project_id or config.project_id or None},
        )


def _get_bearer_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth_header:
        return None
    if not auth_header.lower().startswith("bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip()


def get_current_user(request: Request) -> AuthenticatedUser:
    if _config.auth_disabled:
        return AuthenticatedUser(uid="local-dev", email=None, name="Local Dev")

    token = _get_bearer_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing auth token")

    try:
        _init_firebase(_config)
        decoded = firebase_auth.verify_id_token(token)
    except Exception as exc:
        logger.warning("Auth token verification failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid auth token") from exc

    return AuthenticatedUser(
        uid=decoded.get("uid"),
        email=decoded.get("email"),
        name=decoded.get("name"),
    )
