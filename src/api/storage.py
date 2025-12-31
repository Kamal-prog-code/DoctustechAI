from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import UploadFile
from google.cloud import storage

from api.config import AppConfig


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InputReference:
    uri: str
    filename: str
    content_type: str
    size_bytes: int


class InputStorage:
    def __init__(self, config: AppConfig) -> None:
        self._bucket_name = config.input_bucket
        self._local_root = Path("output") / "inputs"
        self._client = storage.Client(project=config.project_id) if self._bucket_name else None

    def save_upload(self, upload: UploadFile, execution_id: str) -> InputReference:
        filename = Path(upload.filename or "note.txt").name
        content_type = upload.content_type or "text/plain"
        upload.file.seek(0)
        if self._bucket_name:
            bucket = self._client.bucket(self._bucket_name)
            blob_path = f"inputs/{execution_id}/{filename}"
            blob = bucket.blob(blob_path)
            blob.upload_from_file(upload.file, content_type=content_type)
            size_bytes = blob.size or 0
            uri = f"gs://{self._bucket_name}/{blob_path}"
            return InputReference(uri=uri, filename=filename, content_type=content_type, size_bytes=size_bytes)

        self._local_root.mkdir(parents=True, exist_ok=True)
        target_dir = self._local_root / execution_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename
        with target_path.open("wb") as handle:
            data = upload.file.read()
            handle.write(data)
        size_bytes = target_path.stat().st_size
        return InputReference(
            uri=str(target_path),
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
        )

    def load_text(self, uri: str) -> str:
        if uri.startswith("gs://"):
            if not self._client:
                raise RuntimeError("GCS client not configured")
            bucket_name, blob_path = _split_gcs_uri(uri)
            blob = self._client.bucket(bucket_name).blob(blob_path)
            data = blob.download_as_bytes()
            return _decode_bytes(data)

        path = Path(uri)
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {uri}")
        data = path.read_bytes()
        return _decode_bytes(data)


def _split_gcs_uri(uri: str) -> tuple[str, str]:
    _, remainder = uri.split("gs://", 1)
    bucket, blob_path = remainder.split("/", 1)
    return bucket, blob_path


def _decode_bytes(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("Falling back to latin-1 for input content")
        return data.decode("latin-1")
