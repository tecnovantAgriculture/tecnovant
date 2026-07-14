from __future__ import annotations

"""Background tasks for media preprocessing workflows."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import current_app

from app.extensions import db

from .helpers import (
    PreprocessConfig,
    _media_root,
    extract_geo_info_if_tiff,
    extract_image_info,
    generate_nd_index_rgba,
    generate_webp_thumbnails,
    preprocess_rgb_once,
)
from .models import Asset, AssetType, AssetVariant, StorageLocation
from .storage import ensure_local_file, gcs_enabled, upload_file_to_gcs

_executor: Optional[ThreadPoolExecutor] = None



def _derive_mpp_from_transform(geo) -> Optional[float]:
    if not geo or not geo.transform:
        return None
    t = geo.transform
    a = abs(t.get("a", 0) or 0)
    e = abs(t.get("e", 0) or 0)
    if not a or not e:
        return None
    crs_str = (geo.crs or "").upper()
    is_degrees = "EPSG:4326" in crs_str or "GEOGCRS" in crs_str or "DEGREE" in crs_str
    factor = 111320.0 if is_degrees else 1.0
    return max(a, e) * factor


def _get_executor() -> ThreadPoolExecutor:
    """Return a module-level executor configured from the Flask app."""
    global _executor
    if _executor is None:
        app = current_app._get_current_object()
        max_workers = app.config.get("MEDIA_PREPROCESS_MAX_WORKERS", 2)
        _executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="media-preproc",
        )
    return _executor


def _resolve_cache_dir(app, asset_uuid: str) -> Path:
    """Compute the cache directory for an asset and ensure it exists."""
    root_cfg = app.config.get("MEDIA_PREPROCESS_CACHE_DIR")
    if root_cfg:
        root = Path(root_cfg)
    else:
        root = Path(_media_root()) / "cache"
    root.mkdir(parents=True, exist_ok=True)
    cache_dir = root / asset_uuid
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _run_preprocess(app, asset_id: int) -> None:
    """Worker entry point que ejecuta el preprocesamiento completo en un thread de fondo."""
    with app.app_context():
        asset = Asset.query.get(asset_id)
        if asset is None:
            app.logger.warning(
                "media: asset %s disappeared before preprocessing", asset_id
            )
            return
        try:
            if asset.storage == StorageLocation.GCS.value:
                source_path = ensure_local_file(asset.storage_key)
            elif asset.storage == StorageLocation.LOCAL.value:
                source_path = Path(_media_root()) / asset.storage_key
            else:
                app.logger.info(
                    "media: skipping preprocessing for unsupported asset storage %s", asset.uuid
                )
                return
        except RuntimeError:
            app.logger.exception(
                "media: unable to resolve media root for asset %s", asset.uuid
            )
            return

        if not source_path.exists():
            app.logger.warning(
                "media: source file missing for asset %s (%s)", asset.uuid, source_path
            )
            return

        if asset.width is None or asset.height is None or (
            asset.asset_type == AssetType.GEOTIFF.value and asset.transform is None
        ):
            try:
                img = extract_image_info(str(source_path))
                geo = extract_geo_info_if_tiff(str(source_path))
                if img.width is not None:
                    asset.width = img.width
                if img.height is not None:
                    asset.height = img.height
                if asset.asset_type == AssetType.GEOTIFF.value:
                    asset.is_geo = geo.is_geo
                    asset.crs = geo.crs
                    asset.bounds = geo.bounds
                    asset.transform = geo.transform
                    asset.mpp = _derive_mpp_from_transform(geo)
                elif img.exif is not None:
                    asset.exif = img.exif
                db.session.add(asset)
                db.session.commit()
            except Exception:
                db.session.rollback()
                app.logger.exception(
                    "media: deferred metadata extraction failed for asset %s",
                    asset.uuid,
                )
        cache_dir = _resolve_cache_dir(app, asset.uuid)
        processing_flag = cache_dir / ".processing"
        status_file = cache_dir / ".status.json"
        error_flag = cache_dir / ".error"
        started_ts = time.monotonic()

        app.logger.info(
            "media: worker_started asset_id=%s asset_uuid=%s cache_dir=%s",
            asset_id,
            asset.uuid,
            cache_dir,
        )

        def update_status(
            state: str,
            progress: float = 0.0,
            artifact: str = "",
            error_message: str = "",
        ):
            try:
                status_data = {
                    "state": state,
                    "progress": progress,
                    "current_artifact": artifact,
                    "started_at": datetime.utcnow().isoformat() + "Z",
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                    "asset_uuid": asset.uuid,
                }
                if error_message:
                    status_data["error"] = error_message
                status_file.write_text(json.dumps(status_data, indent=2))
            except Exception:
                pass

        try:
            update_status("running", 0.0, "worker_started")
            processing_flag.write_text(f"{datetime.utcnow().isoformat()}Z")
        except Exception:
            try:
                processing_flag.touch(exist_ok=True)
            except Exception:
                pass

        try:
            if error_flag.exists():
                error_flag.unlink()
        except Exception:
            pass

        cfg = PreprocessConfig(
            cache_dir=cache_dir,
            preview_max_dim=int(app.config.get("MEDIA_PREVIEW_MAX_DIM", 2048)),
        )

        def progress_hook(state: str, progress: float, message: str) -> None:
            update_status(state, progress, message)

        _had_error = False
        try:
            t_stage = time.monotonic()
            app.logger.info(
                "media: preprocess_started asset_uuid=%s source=%s size=%sx%s",
                asset.uuid,
                source_path,
                asset.width,
                asset.height,
            )

            # Generate WebP thumbnails in background so the HTTP upload response
            # is not blocked by Pillow loading the full raster into RAM.
            update_status("thumbnails", 0.05, "Generando miniaturas")
            try:
                from app.extensions import db as _db

                thumb_results = generate_webp_thumbnails(str(source_path), asset.uuid)
                if thumb_results:
                    existing_kinds = {v.kind for v in asset.variants}
                    added = False
                    for thumb in thumb_results:
                        if thumb.kind in existing_kinds:
                            continue
                        variant_storage = StorageLocation.GCS.value if gcs_enabled() else StorageLocation.LOCAL.value
                        if variant_storage == StorageLocation.GCS.value:
                            upload_file_to_gcs(Path(_media_root()) / thumb.storage_key, thumb.storage_key, "image/webp")
                        asset.variants.append(
                            AssetVariant(
                                kind=thumb.kind,
                                storage=variant_storage,
                                storage_key=thumb.storage_key,
                                width=thumb.width,
                                height=thumb.height,
                            )
                        )
                        existing_kinds.add(thumb.kind)
                        added = True
                    if added:
                        _db.session.add(asset)
                        _db.session.commit()
                    app.logger.info(
                        "media: thumbnails_done asset_uuid=%s count=%d",
                        asset.uuid,
                        len(thumb_results),
                    )
            except Exception:
                app.logger.exception(
                    "media: thumbnail generation failed for asset %s (non-fatal)",
                    asset.uuid,
                )

            update_status("loading", 0.1, "Cargando imagen desde disco")
            preprocess_rgb_once(source_path, cfg, progress_cb=progress_hook)
            app.logger.info(
                "media: preprocess_done asset_uuid=%s elapsed_sec=%.3f",
                asset.uuid,
                time.monotonic() - t_stage,
            )
            update_status("generating_previews", 0.90, "Generando visualizaciones")
            app.logger.info(
                "media: preprocessing finished for asset %s -> %s",
                asset.uuid,
                cache_dir,
            )
            try:
                if error_flag.exists():
                    error_flag.unlink()
            except Exception:
                pass
        except MemoryError as exc:
            _had_error = True
            update_status("failed", 0.0, "preprocess", f"Error de memoria: {exc}")
            app.logger.exception("media: preprocessing OOM for asset %s", asset.uuid)
            try:
                error_flag.write_text(f"{datetime.utcnow().isoformat()}Z :: OOM: {exc}")
            except Exception:
                pass
        except Exception as exc:
            _had_error = True
            update_status("failed", 0.0, "preprocess", f"Error: {exc}")
            app.logger.exception("media: preprocessing failed for asset %s", asset.uuid)
            try:
                error_flag.write_text(f"{datetime.utcnow().isoformat()}Z :: {exc}")
            except Exception:
                pass
        finally:
            if not _had_error:
                update_status("completed", 1.0, "Listo")
            try:
                processing_flag.unlink()
            except Exception:
                pass

            # nd_index_rgba independiente — su fallo no bloquea otros artefactos
            try:
                t_nd = time.monotonic()
                app.logger.info("media: nd_index_started asset_uuid=%s", asset.uuid)
                nd_path = generate_nd_index_rgba(
                    source_path=source_path,
                    cache_dir=cache_dir,
                    asset_uuid=asset.uuid,
                )
                if nd_path:
                    app.logger.info(
                        "media: nd_index_done asset_uuid=%s path=%s elapsed_sec=%.3f",
                        asset.uuid,
                        nd_path,
                        time.monotonic() - t_nd,
                    )
                else:
                    app.logger.warning(
                        "media: nd_index_rgba returned None for asset %s", asset.uuid
                    )
            except Exception:
                app.logger.exception(
                    "media: nd_index_rgba generation failed for asset %s", asset.uuid
                )

            if asset.asset_type == AssetType.GEOTIFF.value:
                display_processing_flag = cache_dir / ".processing_display"
                display_error_flag = cache_dir / ".error_display"
                try:
                    display_processing_flag.write_text(
                        f"{datetime.utcnow().isoformat()}Z"
                    )
                except Exception:
                    pass
                try:
                    if display_error_flag.exists():
                        display_error_flag.unlink()
                except Exception:
                    pass
                try:
                    app.logger.info("media: display_started asset_uuid=%s", asset.uuid)
                    t_display = time.monotonic()
                    # Import local para evitar import circular al cargar módulos
                    from app.modules.agrovista.services import generate_display_assets

                    generate_display_assets(
                        image_id=asset.uuid,
                        tiff_uri=str(source_path),
                        mode=app.config.get("MEDIA_DISPLAY_MODE", "auto"),
                        max_display_px=int(
                            app.config.get("MEDIA_DISPLAY_MAX_DIM", 4096)
                        ),
                        force=False,
                    )
                    app.logger.info(
                        "media: display_done asset_uuid=%s elapsed_sec=%.3f",
                        asset.uuid,
                        time.monotonic() - t_display,
                    )
                except Exception as exc:
                    app.logger.exception(
                        "media: display asset generation failed for %s", asset.uuid
                    )
                    try:
                        display_error_flag.write_text(
                            f"{datetime.utcnow().isoformat()}Z :: {exc}"
                        )
                    except Exception:
                        pass
                finally:
                    try:
                        display_processing_flag.unlink(missing_ok=True)
                    except Exception:
                        pass

            app.logger.info(
                "media: worker_finished asset_id=%s asset_uuid=%s had_error=%s total_elapsed_sec=%.3f",
                asset_id,
                asset.uuid,
                _had_error,
                time.monotonic() - started_ts,
            )


def enqueue_preprocess_asset(asset_id: int) -> None:
    """Schedule preprocessing for the given asset ID in the background."""
    app = current_app._get_current_object()
    executor = _get_executor()

    # Log para debug
    app.logger.info("media: enqueuing preprocessing for asset_id %s", asset_id)

    asset = Asset.query.get(asset_id)
    if asset is not None:
        cache_dir = _resolve_cache_dir(app, asset.uuid)
        status_file = cache_dir / ".status.json"
        processing_flag = cache_dir / ".processing"
        try:
            status_data = {
                "state": "queued",
                "progress": 0.0,
                "current_artifact": "queued",
                "started_at": datetime.utcnow().isoformat() + "Z",
                "updated_at": datetime.utcnow().isoformat() + "Z",
                "asset_uuid": asset.uuid,
            }
            status_file.write_text(json.dumps(status_data, indent=2))
            processing_flag.touch(exist_ok=True)
        except Exception:
            pass

    try:
        future = executor.submit(_run_preprocess, app, asset_id)
        app.logger.info("media: task submitted to executor for asset_id %s", asset_id)

        # Opcional: agregar callback para manejar excepciones
        def log_exception(f):
            try:
                f.result()  # Esto lanzará la excepción si la hay
            except Exception:
                app.logger.exception(
                    "media: background task failed for asset_id %s", asset_id
                )

        future.add_done_callback(log_exception)

    except Exception as e:
        app.logger.exception(
            "media: failed to submit preprocessing task for asset_id %s", asset_id
        )
        raise
