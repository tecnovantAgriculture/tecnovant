"""Migra archivos de media local a Google Cloud Storage.

Uso dentro del contenedor:
    python scripts/migrate_media_to_gcs.py

Requiere:
    MEDIA_STORAGE_BACKEND=gcs
    MEDIA_GCS_BUCKET=<bucket>
    GOOGLE_APPLICATION_CREDENTIALS=/app/secrets/<service-account>.json
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from app import create_app
from app.extensions import db
from app.modules.media.helpers import _media_root
from app.modules.media.models import Asset, AssetVariant, StorageLocation
from app.modules.media.storage import gcs_enabled, upload_file_to_gcs


def _upload_row(row, media_root: Path, *, dry_run: bool = False) -> tuple[bool, str]:
    if row.storage == StorageLocation.GCS.value:
        return False, "ya estaba en gcs"
    if row.storage != StorageLocation.LOCAL.value:
        return False, f"storage no soportado: {row.storage}"

    local_path = media_root / row.storage_key
    if not local_path.exists():
        return False, f"no existe en local: {local_path}"

    content_type = mimetypes.guess_type(str(local_path))[0]
    if dry_run:
        return True, f"dry-run subiria {row.storage_key}"

    upload_file_to_gcs(local_path, row.storage_key, content_type)
    row.storage = StorageLocation.GCS.value
    return True, f"subido {row.storage_key}"


def main() -> None:
    app = create_app()
    with app.app_context():
        if not gcs_enabled():
            raise SystemExit("MEDIA_STORAGE_BACKEND debe ser gcs para migrar.")

        media_root = Path(_media_root())
        total = 0
        uploaded = 0

        for asset in Asset.query.order_by(Asset.id.asc()).yield_per(50):
            total += 1
            ok, message = _upload_row(asset, media_root)
            print(f"asset {asset.id}: {message}")
            if ok:
                uploaded += 1

        for variant in AssetVariant.query.order_by(AssetVariant.id.asc()).yield_per(100):
            total += 1
            ok, message = _upload_row(variant, media_root)
            print(f"variant {variant.id}: {message}")
            if ok:
                uploaded += 1

        db.session.commit()
        print(f"Listo. Subidos: {uploaded}. Revisados: {total}.")


if __name__ == "__main__":
    main()
