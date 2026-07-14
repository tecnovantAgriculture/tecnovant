from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Optional

from flask import current_app

from .helpers import _media_root
from .models import StorageLocation


def storage_backend() -> str:
    return str(current_app.config.get("MEDIA_STORAGE_BACKEND") or "local").lower()


def gcs_enabled() -> bool:
    return storage_backend() == StorageLocation.GCS.value


def _gcs_bucket_name() -> str:
    bucket = current_app.config.get("MEDIA_GCS_BUCKET")
    if not bucket:
        raise RuntimeError("MEDIA_GCS_BUCKET no esta configurado")
    return str(bucket)


def _gcs_client():
    try:
        from google.cloud import storage as gcs_storage  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "google-cloud-storage no esta instalado. Agrega la dependencia y reconstruye el contenedor."
        ) from exc

    credentials_json = current_app.config.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if credentials_json:
        info = json.loads(str(credentials_json))
        credentials = service_account.Credentials.from_service_account_info(info)
        return gcs_storage.Client(
            credentials=credentials,
            project=info.get("project_id"),
        )

    credentials_path = current_app.config.get("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials_path:
        return gcs_storage.Client.from_service_account_json(str(credentials_path))
    return gcs_storage.Client()


def _gcs_bucket():
    return _gcs_client().bucket(_gcs_bucket_name())


def upload_file_to_gcs(local_path: str | os.PathLike[str], storage_key: str, content_type: Optional[str] = None) -> None:
    blob = _gcs_bucket().blob(storage_key.replace("\\", "/"))
    blob.upload_from_filename(str(local_path), content_type=content_type)


def delete_file_from_gcs(storage_key: str) -> None:
    try:
        _gcs_bucket().blob(storage_key.replace("\\", "/")).delete()
    except Exception:
        current_app.logger.exception("media: no se pudo eliminar %s de GCS", storage_key)


def ensure_local_file(storage_key: str) -> Path:
    """Return a local cached path for a media key, downloading from GCS if needed."""

    local_path = Path(_media_root()) / storage_key
    if local_path.exists():
        return local_path
    if not gcs_enabled():
        return local_path

    local_path.parent.mkdir(parents=True, exist_ok=True)
    blob = _gcs_bucket().blob(storage_key.replace("\\", "/"))
    blob.download_to_filename(str(local_path))
    return local_path


def public_or_signed_url(storage_key: str) -> str:
    blob = _gcs_bucket().blob(storage_key.replace("\\", "/"))
    if current_app.config.get("MEDIA_GCS_PUBLIC_BASE_URL"):
        base = str(current_app.config["MEDIA_GCS_PUBLIC_BASE_URL"]).rstrip("/")
        normalized_key = storage_key.replace("\\", "/")
        return f"{base}/{normalized_key}"
    expiration = int(current_app.config.get("MEDIA_GCS_SIGNED_URL_SECONDS", 3600))
    return blob.generate_signed_url(expiration=timedelta(seconds=expiration))



