from __future__ import annotations

"""Background tasks for media preprocessing workflows."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import current_app

from .helpers import PreprocessConfig, _media_root, preprocess_rgb_once, generate_nd_index_rgba
from .models import Asset, AssetType, StorageLocation
from app.modules.agrovista.services import generate_display_assets

_executor: Optional[ThreadPoolExecutor] = None


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
            app.logger.warning("media: asset %s disappeared before preprocessing", asset_id)
            return
        if asset.storage != StorageLocation.LOCAL.value:
            app.logger.info("media: skipping preprocessing for non-local asset %s", asset.uuid)
            return

        try:
            source_path = Path(_media_root()) / asset.storage_key
        except RuntimeError:
            app.logger.exception("media: unable to resolve media root for asset %s", asset.uuid)
            return

        if not source_path.exists():
            app.logger.warning("media: source file missing for asset %s (%s)", asset.uuid, source_path)
            return

        cache_dir = _resolve_cache_dir(app, asset.uuid)
        processing_flag = cache_dir / ".processing"
        status_file = cache_dir / ".status.json"
        error_flag = cache_dir / ".error"

        def update_status(state: str, progress: float = 0.0, artifact: str = ""):
            try:
                status_data = {
                    "state": state,
                    "progress": progress,
                    "current_artifact": artifact,
                    "started_at": datetime.utcnow().isoformat() + "Z",
                    "updated_at": datetime.utcnow().isoformat() + "Z",
                    "asset_uuid": asset.uuid,
                }
                status_file.write_text(json.dumps(status_data, indent=2))
            except Exception:
                pass

        try:
            update_status("starting", 0.0, "")
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

        _had_error = False
        try:
            update_status("loading", 0.1, "Cargando imagen desde disco")
            preprocess_rgb_once(source_path, cfg)
            update_status("generating_previews", 0.85, "Generando visualizaciones")
            app.logger.info("media: preprocessing finished for asset %s -> %s", asset.uuid, cache_dir)
            try:
                if error_flag.exists():
                    error_flag.unlink()
            except Exception:
                pass
        except MemoryError as exc:
            _had_error = True
            update_status("failed", 0.0, f"Error de memoria: {exc}")
            app.logger.exception("media: preprocessing OOM for asset %s", asset.uuid)
            try:
                error_flag.write_text(f"{datetime.utcnow().isoformat()}Z :: OOM: {exc}")
            except Exception:
                pass
        except Exception as exc:
            _had_error = True
            update_status("failed", 0.0, f"Error: {exc}")
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
                nd_path = generate_nd_index_rgba(
                    source_path=source_path,
                    cache_dir=cache_dir,
                    asset_uuid=asset.uuid,
                )
                if nd_path:
                    app.logger.info("media: nd_index_rgba generated for asset %s -> %s", asset.uuid, nd_path)
                else:
                    app.logger.warning("media: nd_index_rgba returned None for asset %s", asset.uuid)
            except Exception:
                app.logger.exception("media: nd_index_rgba generation failed for asset %s", asset.uuid)

            if asset.asset_type == AssetType.GEOTIFF.value:
                display_processing_flag = cache_dir / ".processing_display"
                display_error_flag = cache_dir / ".error_display"
                try:
                    display_processing_flag.write_text(f"{datetime.utcnow().isoformat()}Z")
                except Exception:
                    pass
                try:
                    if display_error_flag.exists():
                        display_error_flag.unlink()
                except Exception:
                    pass
                try:
                    generate_display_assets(
                        image_id=asset.uuid,
                        tiff_uri=str(source_path),
                        mode=app.config.get("MEDIA_DISPLAY_MODE", "auto"),
                        max_display_px=int(app.config.get("MEDIA_DISPLAY_MAX_DIM", 4096)),
                        force=False,
                    )
                except Exception as exc:
                    app.logger.exception("media: display asset generation failed for %s", asset.uuid)
                    try:
                        display_error_flag.write_text(f"{datetime.utcnow().isoformat()}Z :: {exc}")
                    except Exception:
                        pass
                finally:
                    try:
                        display_processing_flag.unlink(missing_ok=True)
                    except Exception:
                        pass


def enqueue_preprocess_asset(asset_id: int) -> None:
    """Schedule preprocessing for the given asset ID in the background."""
    app = current_app._get_current_object()
    executor = _get_executor()
    
    # Log para debug
    app.logger.info("media: enqueuing preprocessing for asset_id %s", asset_id)
    
    try:
        future = executor.submit(_run_preprocess, app, asset_id)
        app.logger.info("media: task submitted to executor for asset_id %s", asset_id)
        
        # Opcional: agregar callback para manejar excepciones
        def log_exception(f):
            try:
                f.result()  # Esto lanzará la excepción si la hay
            except Exception as e:
                app.logger.exception("media: background task failed for asset_id %s", asset_id)
        
        future.add_done_callback(log_exception)
        
    except Exception as e:
        app.logger.exception("media: failed to submit preprocessing task for asset_id %s", asset_id)
        raise
