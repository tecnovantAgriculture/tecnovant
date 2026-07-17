"""Puntos finales para gestionar activos multimedia."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import numpy as np
from flask import current_app, jsonify, request, url_for
from PIL import Image
from sqlalchemy.orm import selectinload

from app.core.controller import api_login_required, check_permission
from app.extensions import db

from . import media_api as api
from .controller import MediaController
from .helpers import (
    PreprocessConfig,
    _media_root,
    friendly_preprocess_error,
    generate_nd_index_rgba,
    preprocess_rgb_once,
)
from .models import Asset, StorageLocation
from .storage import ensure_local_file
from .tasks import _resolve_cache_dir, enqueue_preprocess_asset


@api.route("/ping", methods=["GET"])
def ping():
    """Responder con un mensaje de salud para comprobar la API de media."""

    return jsonify(message="pong from media API")


@api.route("/assets/<uuid>/reprocess", methods=["POST"])
@api_login_required
@check_permission(required_roles=["administrator", "reseller"])
def reprocess_asset(uuid: str):
    """Encolar reprocesamiento de un asset en background thread."""
    asset = Asset.query.filter_by(uuid=uuid).first_or_404()
    app = current_app._get_current_object()

    # Limpiar cache existente para forzar reprocesamiento limpio
    cache_dir = _resolve_cache_dir(app, asset.uuid)
    try:
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
    except Exception:
        pass

    # Encolar en background — el worker escribe .processing y .status.json
    try:
        enqueue_preprocess_asset(asset.id)
    except Exception as e:
        current_app.logger.exception("media: failed to enqueue reprocess for %s", uuid)
        return (
            jsonify({"success": False, "message": f"No se pudo encolar la tarea: {e}"}),
            500,
        )

    return (
        jsonify(
            {
                "success": True,
                "message": f"Reprocesamiento de {asset.original_name} encolado",
                "asset_uuid": asset.uuid,
            }
        ),
        202,
    )


@api.route("/assets/<uuid>/preprocess-status", methods=["GET"])
@api_login_required
def get_preprocess_status(uuid: str):
    """Obtener estado detallado del preprocesamiento de un asset."""
    asset = Asset.query.filter_by(uuid=uuid).first_or_404()

    cache_dir = _resolve_cache_dir(current_app._get_current_object(), asset.uuid)
    processing_flag = cache_dir / ".processing"
    status_file = cache_dir / ".status.json"
    error_flag = cache_dir / ".error"

    response = {
        "asset_uuid": asset.uuid,
        "is_processing": processing_flag.exists(),
        "has_error": error_flag.exists(),
    }

    # Read error if exists
    if error_flag.exists():
        try:
            with open(error_flag, "r", encoding="utf-8") as fh:
                response["error"] = friendly_preprocess_error(fh.read().strip())
        except Exception:
            response["error"] = "No se pudo leer el error"

    # Read detailed status if available
    if status_file.exists():
        try:
            with open(status_file, "r", encoding="utf-8") as fh:
                response["status"] = json.load(fh)
            if response["status"] and response["status"].get("error"):
                response["status"]["error"] = friendly_preprocess_error(
                    response["status"]["error"]
                )
        except Exception:
            response["status"] = None

    rel_cache_dir = os.path.join("cache", uuid)
    artifact_patterns = [
        ("npy", f"{uuid}__rgb_preproc_linear.npy", False),
        ("wb", f"{uuid}.wb.json", False),
        ("rgb_preview", f"{uuid}__rgb_preproc_preview.png", True),
        ("vi_gray", f"{uuid}__vi_gr_ratio.png", True),
        ("vi_heat", f"{uuid}__vi_gr_heat.png", True),
        ("heatmap", f"{uuid}__vi_heatmap.png", True),
        ("nd_index_rgba", f"{uuid}__nd_index_rgba.png", True),
    ]
    artifacts = {}
    previews = {}
    for key, pattern, is_image in artifact_patterns:
        exists = (cache_dir / pattern).exists()
        artifacts[key] = exists
        if is_image and exists:
            previews[key] = url_for(
                "media.serve_file", key=os.path.join(rel_cache_dir, pattern)
            )

    response["artifacts"] = artifacts
    response["previews"] = previews

    return jsonify(response)


@api.route("/assets", methods=["GET"])
@api_login_required
def list_assets():
    """Listar los metadatos de los activos registrados ordenados por fecha."""

    items = (
        Asset.query.options(selectinload(Asset.variants))
        .order_by(Asset.created_at.desc())
        .all()
    )

    def to_dict(asset: Asset):
        """Transformar un ``Asset`` en un diccionario serializable para la API."""

        return {
            "id": asset.id,
            "uuid": asset.uuid,
            "original_name": asset.original_name,
            "ext": asset.ext,
            "mime": asset.mime,
            "asset_type": asset.asset_type,
            "storage": asset.storage,
            "storage_key": asset.storage_key,
            "size_bytes": asset.size_bytes,
            "width": asset.width,
            "height": asset.height,
            "is_geo": asset.is_geo,
            "created_at": asset.created_at.isoformat(),
            "variants": [
                {
                    "kind": variant.kind,
                    "storage": variant.storage,
                    "storage_key": variant.storage_key,
                    "width": variant.width,
                    "height": variant.height,
                }
                for variant in asset.variants
            ],
        }

    return jsonify([to_dict(x) for x in items]), 200


@api.route("/upload", methods=["POST"])
@api_login_required
@check_permission()
def upload_local_api():
    """Almacenar un archivo recibido mediante la clave `file` del formulario.

    Devuelve los metadatos completos del asset para soportar el modo picker,
    permitiendo que el archivo subido sea seleccionado inmediatamente después
    de la subida sin necesidad de recargar la biblioteca.
    """

    if "file" not in request.files:
        return jsonify({"message": "No file part"}), 400
    file = request.files["file"]
    try:
        ctrl = MediaController()
        asset, created = ctrl.save_local_upload(file)
        enqueue_preprocess_asset(asset.id)
        status = 201 if created else 200
        return (
            jsonify(
                {
                    "message": "Uploaded" if created else "Asset already existed",
                    "asset_id": asset.id,
                    "uuid": asset.uuid,
                    "storage_key": asset.storage_key,
                    "created": created,
                    "asset": {
                        "id": asset.id,
                        "uuid": asset.uuid,
                        "storage_key": asset.storage_key,
                        "original_name": asset.original_name,
                        "mime": asset.mime,
                        "asset_type": asset.asset_type,
                        "width": asset.width,
                        "height": asset.height,
                        "size_bytes": asset.size_bytes,
                        "serve_url": url_for("media.serve_file", key=asset.storage_key),
                        "download_url": url_for(
                            "media.download_file", key=asset.storage_key
                        ),
                    },
                }
            ),
            status,
        )
    except ValueError as e:
        return jsonify({"message": str(e)}), 400
    except Exception as e:
        current_app.logger.exception("media upload failed")
        db.session.rollback()
        return jsonify({"message": "Upload failed"}), 500


@api.route("/assets/<int:asset_id>", methods=["DELETE"])
@api_login_required
@check_permission(required_roles=["administrator", "reseller"])
def delete_asset(asset_id: int):
    """Eliminar un activo existente identificado por su ID numérico."""

    try:
        ctrl = MediaController()
        ok = ctrl.delete_asset(asset_id)
        if not ok:
            return jsonify({"message": "Asset not found"}), 404
        return jsonify({"message": "Deleted"}), 200
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Delete failed"}), 500


@api.route("/assets/<int:asset_id>/display-info", methods=["GET"])
@api_login_required
def asset_display_info(asset_id: int):
    """Return only what's needed to place the image on the Leaflet map immediately.

    Reads from DB + existing display artefacts on disk — no rasterio, no PIL,
    no numpy computation. The heavy agrovista-meta endpoint is called lazily
    by the frontend after the image is already visible.

    Args:
        asset_id: Numeric primary key of the Asset record.

    Returns:
        JSON with display PNG dimensions, URL, and stub meta fields compatible
        with ``applyMeta``. HTTP 202 when the display PNG is not yet ready.

    Raises:
        400: If the asset is not stored locally.
        404: If the asset record does not exist.
    """
    import json as _json

    from app.modules.agrovista.services.display_assets import _resolve_display_dir

    asset = Asset.query.get_or_404(asset_id)
    if asset.storage not in {StorageLocation.LOCAL.value, StorageLocation.GCS.value}:
        return jsonify({"message": "Almacenamiento de asset no soportado."}), 400

    # Resolve display PNG path — no computation, just path resolution.
    display_dir = _resolve_display_dir(asset.uuid)
    display_png = display_dir / "display.png"
    metadata_json = display_dir / "metadata.json"

    # Check processing status.
    app = current_app._get_current_object()
    cache_dir = _resolve_cache_dir(app, asset.uuid)
    processing_flag = cache_dir / ".processing"

    if not display_png.exists():
        if processing_flag.exists():
            return (
                jsonify({"message": "El asset aún está siendo procesado."}),
                202,
            )
        # Enqueue if nothing is happening.
        try:
            enqueue_preprocess_asset(asset.id)
        except Exception:
            pass
        return (
            jsonify({"message": "Procesamiento encolado. Intenta en unos momentos."}),
            202,
        )

    # Read display dimensions from metadata.json — no Pillow, no rasterio.
    display_w: int | None = asset.width
    display_h: int | None = asset.height
    if metadata_json.exists():
        try:
            with metadata_json.open("r", encoding="utf-8") as fh:
                meta_data = _json.load(fh)
            png_size = meta_data.get("display_png_size", {})
            display_w = png_size.get("width") or display_w
            display_h = png_size.get("height") or display_h
        except Exception:
            pass

    display_key = os.path.join("display", asset.uuid, "display.png")
    display_url = url_for("media.serve_file", key=display_key)

    return (
        jsonify(
            {
                "id": asset.uuid,
                "uuid": asset.uuid,
                "asset_id": asset.id,
                "width": display_w,
                "height": display_h,
                "width_preview": display_w,
                "height_preview": display_h,
                "width_full": asset.width,
                "height_full": asset.height,
                "mppX": asset.mpp,
                "mppY": asset.mpp,
                "display_ready": True,
                "processed": False,
                "preview_only": True,
                "method": "ndvi_approx",
                "visible_method": "combined",
                "has_nir": False,
                "source": "media",
                "preview_url": display_url,
                "previews": {"rgb": display_url},
                "variables": {
                    "vi": None,
                    "vari": None,
                    "gli": None,
                    "ngrdi": None,
                    "exg": None,
                },
                "ndvi_stamp": (
                    int(asset.created_at.timestamp()) if asset.created_at else None
                ),
                "cache_npy_key": None,
                "cache_wb_key": None,
            }
        ),
        200,
    )


@api.route("/assets/<int:asset_id>/agrovista-meta", methods=["GET"])
@api_login_required
def asset_agrovista_meta(asset_id: int):
    """Entregar metadata y rutas de caché listas para Agrovista sin re-subir archivos.

    Devuelve:
    - Dimensiones y mpp.
    - Flags de procesamiento (siempre `ndvi_approx` visible en esta ruta).
    - URL de preview (cache PNG) servida por el módulo media.
    - Clave de caché (NPZ) para que Agrovista calcule NDVI aprox y estadísticas.
    """

    asset = Asset.query.get_or_404(asset_id)
    if asset.storage not in {StorageLocation.LOCAL.value, StorageLocation.GCS.value}:
        return (
            jsonify({"message": "Almacenamiento de asset no soportado en este flujo."}),
            400,
        )

    try:
        source_path = ensure_local_file(asset.storage_key) if asset.storage == StorageLocation.GCS.value else Path(_media_root()) / asset.storage_key
    except Exception:
        return (
            jsonify({"message": "No se pudo resolver el almacenamiento de media."}),
            500,
        )
    if not source_path.exists():
        return jsonify({"message": "Archivo origen no encontrado."}), 404

    app = current_app._get_current_object()
    cache_dir = _resolve_cache_dir(app, asset.uuid)
    cfg = PreprocessConfig(
        cache_dir=cache_dir,
        preview_max_dim=int(app.config.get("MEDIA_PREVIEW_MAX_DIM", 2048)),
    )

    in_key = source_path.stem
    wb_path = cache_dir / f"{in_key}.wb.json"
    preview_path = cache_dir / f"{in_key}__rgb_preproc_preview.png"

    if not wb_path.exists():
        # Sidecar WB aún no existe — preprocessing pendiente o en curso.
        processing_flag = cache_dir / ".processing"
        if processing_flag.exists():
            return (
                jsonify(
                    {
                        "message": "El asset aún está siendo procesado. Intenta en unos momentos."
                    }
                ),
                202,
            )
        # No existe ni está procesando: encolar
        try:
            enqueue_preprocess_asset(asset.id)
        except Exception:
            pass
        return (
            jsonify({"message": "Procesamiento encolado. Intenta en unos momentos."}),
            202,
        )

    # Regenerar previews faltantes si el sidecar existe pero faltan PNGs.
    vi_gray_path = cache_dir / f"{in_key}__vi_gr_ratio.png"
    vi_heat_path = cache_dir / f"{in_key}__vi_gr_heat.png"
    vi_heatmap_path = cache_dir / f"{in_key}__vi_heatmap.png"
    missing_previews = [
        name
        for name, path in [
            ("rgb", preview_path),
            ("vi_gray", vi_gray_path),
            ("vi_heat", vi_heat_path),
            ("vi_heatmap", vi_heatmap_path),
        ]
        if not path.exists()
    ]
    if missing_previews:
        try:
            preprocess_rgb_once(source_path, cfg)
        except Exception:
            current_app.logger.exception(
                "media: failed to generate missing previews for asset %s", asset.uuid
            )

    rel_cache_dir = os.path.join("cache", asset.uuid)
    preview_width = preview_height = None
    if preview_path and preview_path.exists():
        try:
            with Image.open(preview_path) as img:
                preview_width, preview_height = img.size
        except Exception:
            preview_width = preview_height = None

    width_full = asset.width or None
    height_full = asset.height or None

    def _url(path: Path | None):
        if not path or not path.exists():
            return None
        key = os.path.join(rel_cache_dir, path.name)
        return url_for("media.serve_file", key=key)

    preview_url = _url(preview_path)
    npy_path = cache_dir / f"{in_key}__rgb_preproc_linear.npy"
    npy_key = os.path.join(rel_cache_dir, npy_path.name) if npy_path.exists() else None
    wb_key = os.path.join(rel_cache_dir, wb_path.name) if wb_path.exists() else None
    # Generate nd_index_rgba on-demand if not yet cached
    nd_index_path = cache_dir / f"{asset.uuid}__nd_index_rgba.png"
    if not nd_index_path.exists():
        try:
            generate_nd_index_rgba(
                source_path=source_path,
                cache_dir=cache_dir,
                asset_uuid=asset.uuid,
            )
        except Exception:
            current_app.logger.exception(
                "media: on-demand nd_index_rgba generation failed for %s", asset.uuid
            )

    preview_variants = {
        "rgb": preview_url,
        "vi_heat": _url(cache_dir / f"{asset.uuid}__vi_gr_heat.png"),
        "vi_ratio": _url(cache_dir / f"{asset.uuid}__vi_gr_ratio.png"),
        "vi_heatmap": _url(cache_dir / f"{asset.uuid}__vi_heatmap.png"),
        "nd_index_rgba": _url(cache_dir / f"{asset.uuid}__nd_index_rgba.png"),
    }

    width = preview_width or width_full
    height = preview_height or height_full
    scale_x = scale_y = None
    if width and height and width_full and height_full and width > 0 and height > 0:
        try:
            scale_x = float(width_full) / float(width)
            scale_y = float(height_full) / float(height)
        except Exception:
            scale_x = scale_y = None

    mppX = asset.mpp
    mppY = asset.mpp

    meta = {
        "id": asset.uuid,
        "asset_id": asset.id,
        "uuid": asset.uuid,
        "width": width,
        "height": height,
        "width_preview": preview_width,
        "height_preview": preview_height,
        "width_full": width_full,
        "height_full": height_full,
        "scale_x": scale_x,
        "scale_y": scale_y,
        "mppX": mppX,
        "mppY": mppY,
        "processed": False,
        "preview_only": True,
        "method": "ndvi_approx",
        "visible_method": "combined",
        "has_nir": False,
        "previews": preview_variants,
        "variables": {
            "vi": None,
            "vari": None,
            "gli": None,
            "ngrdi": None,
            "exg": None,
        },
        "ndvi_stamp": int(asset.created_at.timestamp()) if asset.created_at else None,
        "preview_url": preview_url,
        "cache_npy_key": npy_key,
        "cache_wb_key": wb_key,
        "cache_dir": rel_cache_dir,
        "source": "media",
    }
    return jsonify(meta), 200


@api.route("/cleanup/orphaned-processing", methods=["POST"])
@api_login_required
@check_permission(required_roles=["administrator", "reseller"])
def cleanup_orphaned_processing():
    """Clean up orphaned .processing flags from cache directories.

    Restricted to administrator/reseller: this is a global, destructive
    maintenance sweep over the whole preprocess cache, not a tenant-scoped
    operation.
    """
    import json
    import time
    from pathlib import Path

    app = current_app._get_current_object()

    # Get cache root directory
    root_cfg = app.config.get("MEDIA_PREPROCESS_CACHE_DIR")
    if root_cfg:
        cache_root = Path(root_cfg)
    else:
        from .helpers import _media_root

        cache_root = Path(_media_root()) / "cache"

    if not cache_root.exists():
        return (
            jsonify(
                {"success": True, "message": "Cache root does not exist", "cleaned": 0}
            ),
            200,
        )

    cleaned = 0
    errors = []

    # Look for orphaned .processing flags
    for cache_dir in cache_root.iterdir():
        if not cache_dir.is_dir():
            continue

        processing_flag = cache_dir / ".processing"
        status_file = cache_dir / ".status.json"

        if processing_flag.exists():
            try:
                # Check if processing is actually stuck
                # If status file exists and is old (> 30 minutes), clean it
                should_clean = False

                if status_file.exists():
                    try:
                        status_data = json.loads(status_file.read_text())
                        updated_at_str = status_data.get("updated_at", "")
                        if updated_at_str:
                            # Parse timestamp
                            from datetime import datetime

                            updated_at = datetime.fromisoformat(
                                updated_at_str.replace("Z", "+00:00")
                            )
                            now = datetime.utcnow()
                            age_minutes = (now - updated_at).total_seconds() / 60

                            if age_minutes > 30:  # 30 minutes old
                                should_clean = True
                    except Exception:
                        # If can't parse status, check file age
                        file_age = time.time() - status_file.stat().st_mtime
                        if file_age > 1800:  # 30 minutes in seconds
                            should_clean = True
                else:
                    # No status file, check .processing file age
                    file_age = time.time() - processing_flag.stat().st_mtime
                    if file_age > 1800:  # 30 minutes in seconds
                        should_clean = True

                if should_clean:
                    processing_flag.unlink()
                    if status_file.exists():
                        status_file.unlink()
                    cleaned += 1

            except PermissionError as e:
                errors.append(f"Permission error cleaning {cache_dir.name}: {e}")
            except Exception as e:
                errors.append(f"Error cleaning {cache_dir.name}: {e}")

    response = {
        "success": True,
        "message": f"Cleaned {cleaned} orphaned processing flags",
        "cleaned": cleaned,
    }

    if errors:
        response["errors"] = errors[:10]  # Limit errors in response

    return jsonify(response), 200


@api.route("/cleanup/asset/<uuid>", methods=["POST"])
@api_login_required
@check_permission(required_roles=["administrator", "reseller"])
def cleanup_asset_cache(uuid: str):
    """Clean up cache for a specific asset."""
    import shutil

    app = current_app._get_current_object()

    # Resolve cache directory
    from .tasks import _resolve_cache_dir

    cache_dir = _resolve_cache_dir(app, uuid)

    try:
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            return (
                jsonify(
                    {"success": True, "message": f"Cache cleaned for asset {uuid}"}
                ),
                200,
            )
        else:
            return (
                jsonify(
                    {"success": True, "message": f"No cache found for asset {uuid}"}
                ),
                200,
            )
    except PermissionError as e:
        return (
            jsonify(
                {
                    "success": False,
                    "message": f"Permission error cleaning cache for {uuid}",
                    "error": str(e),
                }
            ),
            403,
        )
    except Exception as e:
        return (
            jsonify(
                {
                    "success": False,
                    "message": f"Error cleaning cache for {uuid}",
                    "error": str(e),
                }
            ),
            500,
        )
