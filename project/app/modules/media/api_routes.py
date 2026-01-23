"""Puntos finales para gestionar activos multimedia."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image
from flask import current_app, jsonify, request, url_for
from sqlalchemy.orm import selectinload

from app.core.controller import login_required
from app.extensions import db

from . import media_api as api
from .controller import MediaController
from .helpers import PreprocessConfig, _media_root, preprocess_rgb_once
from .models import Asset, StorageLocation
from .tasks import enqueue_preprocess_asset, _resolve_cache_dir


@api.route("/ping", methods=["GET"])
def ping():
    """Responder con un mensaje de salud para comprobar la API de media."""

    return jsonify(message="pong from media API")


@api.route("/assets", methods=["GET"])
@login_required
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
@login_required
def upload_local_api():
    """Almacenar un archivo recibido mediante la clave `file` del formulario."""

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
@login_required
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


@api.route("/assets/<int:asset_id>/agrovista-meta", methods=["GET"])
@login_required
def asset_agrovista_meta(asset_id: int):
    """Entregar metadata y rutas de caché listas para Agrovista sin re-subir archivos.

    Devuelve:
    - Dimensiones y mpp.
    - Flags de procesamiento (siempre `ndvi_approx` visible en esta ruta).
    - URL de preview (cache PNG) servida por el módulo media.
    - Clave de caché (NPZ) para que Agrovista calcule NDVI aprox y estadísticas.
    """

    asset = Asset.query.get_or_404(asset_id)
    if asset.storage != StorageLocation.LOCAL.value:
        return jsonify({"message": "Solo se soportan assets locales en este flujo."}), 400

    try:
        media_root = Path(_media_root())
    except Exception:
        return jsonify({"message": "No se pudo resolver el almacenamiento de media."}), 500

    source_path = media_root / asset.storage_key
    if not source_path.exists():
        return jsonify({"message": "Archivo origen no encontrado."}), 404

    app = current_app._get_current_object()
    cache_dir = _resolve_cache_dir(app, asset.uuid)
    cfg = PreprocessConfig(
        cache_dir=cache_dir,
        preview_max_dim=int(app.config.get("MEDIA_PREVIEW_MAX_DIM", 2048)),
    )

    try:
        _, preview_path, npz_path, *_ = preprocess_rgb_once(source_path, cfg)
    except Exception:
        current_app.logger.exception("media: agrovista-meta preprocessing failed for %s", asset.uuid)
        return jsonify({"message": "No se pudo preparar la caché para el asset."}), 500

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
    if (width_full is None or height_full is None) and npz_path and npz_path.exists():
        try:
            arr = np.load(npz_path, mmap_mode="r")["rgb"]
            height_full, width_full = int(arr.shape[0]), int(arr.shape[1])
        except Exception:
            width_full = width_full or None
            height_full = height_full or None

    def _url(path: Path | None):
        if not path or not path.exists():
            return None
        key = os.path.join(rel_cache_dir, path.name)
        return url_for("media.serve_file", key=key)

    preview_url = _url(preview_path)
    npz_key = os.path.join(rel_cache_dir, npz_path.name) if npz_path and npz_path.exists() else None
    preview_variants = {
        "rgb": preview_url,
        "vi_heat": _url(cache_dir / f"{asset.uuid}__vi_gr_heat.png"),
        "vi_ratio": _url(cache_dir / f"{asset.uuid}__vi_gr_ratio.png"),
        "vi_heatmap": _url(cache_dir / f"{asset.uuid}__vi_heatmap.png"),
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
        "cache_npz_key": npz_key,
        "cache_dir": rel_cache_dir,
        "source": "media",
    }
    return jsonify(meta), 200
