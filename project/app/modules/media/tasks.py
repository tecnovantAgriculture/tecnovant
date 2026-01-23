from __future__ import annotations

"""Background tasks for media preprocessing workflows."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import current_app

from .helpers import PreprocessConfig, _media_root, preprocess_rgb_once
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
    """Worker entry point that performs the preprocessing with app context."""
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
        error_flag = cache_dir / ".error"
        try:
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

        try:
            preprocess_rgb_once(source_path, cfg)
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
        except Exception as exc:
            app.logger.exception("media: preprocessing failed for asset %s", asset.uuid)
            try:
                error_flag.write_text(
                    f"{datetime.utcnow().isoformat()}Z :: {exc}"
                )
            except Exception:
                pass
        finally:
            try:
                processing_flag.unlink()
            except Exception:
                pass

        if asset.asset_type == AssetType.GEOTIFF.value:
            try:
                generate_display_assets(
                    image_id=asset.uuid,
                    tiff_uri=str(source_path),
                    mode=app.config.get("MEDIA_DISPLAY_MODE", "auto"),
                    max_display_px=int(app.config.get("MEDIA_DISPLAY_MAX_DIM", 4096)),
                    force=False,
                )
            except Exception:
                app.logger.exception("media: display asset generation failed for %s", asset.uuid)


def enqueue_preprocess_asset(asset_id: int) -> None:
    """Schedule preprocessing for the given asset ID in the background."""
    app = current_app._get_current_object()
    executor = _get_executor()
    executor.submit(_run_preprocess, app, asset_id)
