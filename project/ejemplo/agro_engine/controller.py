"""Consolidated controller prioritizing agrovista's cache handling and NDVI processing."""

import json
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import rasterio
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from flask import current_app
from app.extensions import db

from .helpers import (
    DATA_DIR,
    CACHE_DIR,
    VISIBLE_INDEX_KEYS,
    META_SUFFIX,
    allowed_file,
    allowed_extension,
    allocate_storage_path,
    compute_ndvi,
    extract_geo_info_if_tiff,
    extract_image_info,
    guess_mime,
    save_png,
    save_quick_preview,
    sha256_of_file,
    _hash_file,
    _cache_dir,
    _cache_meta_path,
    _index_path,
    _meta_path,
    _load_json,
    _save_json,
    _load_meta,
    _save_meta,
    _load_cache_meta,
    _save_cache_meta,
)
from .models import (
    Asset,
    AssetType,
    AssetVariant,
    NDVIImage,
    StorageLocation,
)


# ==================== Agrovista Cache Functions (Priority) ====================

def _nanmean(arr: np.ndarray) -> float | None:
    """Return the mean of ``arr`` ignoring NaN values, or ``None`` when empty."""
    if arr.size == 0:
        return None
    finite = np.isfinite(arr)
    if not finite.any():
        return None
    mean = float(np.nanmean(arr[finite]))
    return round(mean, 4)


def _compute_stats_from_indices(ndvi: np.ndarray, indices: Dict[str, np.ndarray]) -> Dict[str, float | None]:
    """Derive summary statistics from NDVI and visible indices."""
    stats = {"vi": _nanmean(ndvi)}
    for key, name in (("VARI", "vari"), ("GLI", "gli"), ("NGRDI", "ngrdi"), ("ExG", "exg")):
        arr = indices.get(key)
        if arr is None:
            stats[name] = None
        else:
            stats[name] = _nanmean(np.asarray(arr, dtype=np.float32))
    return stats


def _clone_cache(file_hash: str, img_id: str) -> Dict[str, object] | None:
    """Copy cached NDVI assets into the working directory if available."""
    meta = _load_cache_meta(file_hash)
    if not meta:
        return None
    cache_dir = _cache_dir(file_hash)
    if not cache_dir.exists():
        return None

    # TODO: remover este override cuando se aproveche verdaderamente el NIR.
    meta = {
        **meta,
        "method": "ndvi_approx",
        "visible_method": meta.get("visible_method") or "combined",
        "has_nir": False,
    }

    ndvi_src = cache_dir / "ndvi.npy"
    png_src = cache_dir / "ndvi.png"
    if not ndvi_src.exists() or not png_src.exists():
        return None

    ndvi_dst = DATA_DIR / f"{img_id}.npy"
    png_dst = DATA_DIR / f"{img_id}.png"
    shutil.copy2(ndvi_src, ndvi_dst)
    shutil.copy2(png_src, png_dst)

    indices_paths: Dict[str, str] = {}
    for key in VISIBLE_INDEX_KEYS:
        src = cache_dir / f"{key}.npy"
        if src.exists():
            dst = _index_path(img_id, key)
            shutil.copy2(src, dst)
            indices_paths[key] = str(dst)

    cloned = {
        "stats": meta.get("stats", {}),
        "visible_method": meta.get("visible_method"),
        "method": meta.get("method"),
        "has_nir": meta.get("has_nir"),
        "width": meta.get("width"),
        "height": meta.get("height"),
        "npy_path": str(ndvi_dst),
        "png_path": str(png_dst),
        "indices_paths": indices_paths,
        "processed": True,
        "stamp": meta.get("stamp", int(time.time())),
        "hash": file_hash,
    }
    return cloned


def _update_cache(meta: Dict[str, object]) -> None:
    """Refresh the shared cache with paths referenced by ``meta``."""
    file_hash = meta.get("hash")
    if not file_hash:
        return
    cache_dir = _cache_dir(str(file_hash))
    cache_dir.mkdir(parents=True, exist_ok=True)
    for name, src_str in (
        ("ndvi.npy", meta.get("npy_path")),
        ("ndvi.png", meta.get("png_path")),
    ):
        if not src_str:
            continue
        src = Path(str(src_str))
        if src.exists():
            shutil.copy2(src, cache_dir / name)
    for key in VISIBLE_INDEX_KEYS:
        src_str = meta.get("indices_paths", {}).get(key)
        if not src_str:
            continue
        src = Path(src_str)
        if src.exists():
            shutil.copy2(src, cache_dir / f"{key}.npy")
    cache_meta = {
        "stats": meta.get("stats"),
        "visible_method": meta.get("visible_method"),
        "method": meta.get("method"),
        "has_nir": meta.get("has_nir"),
        "width": meta.get("width"),
        "height": meta.get("height"),
        "stamp": meta.get("stamp"),
    }
    _save_cache_meta(str(file_hash), cache_meta)


def load_indices(img_id: str) -> Dict[str, np.ndarray]:
    """Load every stored visible index array for ``img_id``."""
    ensure_processed(img_id)
    out: Dict[str, np.ndarray] = {}
    for key in VISIBLE_INDEX_KEYS:
        path = _index_path(img_id, key)
        if not path.exists():
            continue
        try:
            arr = np.load(path, allow_pickle=False).astype(np.float32, copy=False)
            out[key.upper()] = arr
        except Exception:
            continue
    return out


def process_upload(file_storage) -> dict:
    """Take an uploaded raster, persist it, and enqueue NDVI processing (agrovista priority)."""
    if not file_storage or not allowed_file(file_storage.filename):
        raise ValueError("invalid file format")
    safe = secure_filename(file_storage.filename)
    tmp_path = DATA_DIR / f"raw_{uuid.uuid4().hex}_{safe}"
    file_storage.save(tmp_path)
    try:
        file_hash = _hash_file(tmp_path)
        img_id = uuid.uuid4().hex
        ext = Path(safe).suffix.lower() or ".tif"
        raw_path = DATA_DIR / f"{img_id}_raw{ext}"
        shutil.move(tmp_path, raw_path)

        npy_path = DATA_DIR / f"{img_id}.npy"
        ndvi_png_path = DATA_DIR / f"{img_id}.png"
        preview_path = DATA_DIR / f"{img_id}_preview.png"

        cached = _clone_cache(file_hash, img_id)

        processed = False
        method = "ndvi_approx"
        visible_method = "combined"
        has_nir: bool | None = False
        indices_paths: Dict[str, str] = {}
        stats: Dict[str, float | None] = {k: None for k in ("vi", "vari", "gli", "ngrdi", "exg")}
        width = height = 0
        stamp = int(time.time())

        if cached:
            processed = True
            method = cached.get("method") or method
            visible_method = cached.get("visible_method") or visible_method
            has_nir = cached.get("has_nir") if cached.get("has_nir") is not None else has_nir
            stats.update({k: cached.get("stats", {}).get(k) for k in stats})
            indices_paths = cached.get("indices_paths", {})
            stamp = cached.get("stamp", stamp)
            width = cached.get("width") or width
            height = cached.get("height") or height
            if not width or not height:
                try:
                    arr = np.load(npy_path, mmap_mode="r")
                    height, width = arr.shape
                except Exception:
                    width = width or 0
                    height = height or 0
        else:
            try:
                with rasterio.open(raw_path) as src:
                    width = src.width
                    height = src.height
            except Exception:
                width = height = 0
            preview_size = save_quick_preview(raw_path, preview_path)
            if not width or not height:
                width, height = preview_size

        record_png_path = ndvi_png_path if processed else preview_path

        record = NDVIImage(
            id=img_id,
            filename=safe,
            png_path=str(record_png_path),
            npy_path=str(npy_path),
            width=width,
            height=height,
            upload_date=datetime.utcnow(),
        )
        db.session.add(record)
        db.session.commit()

        meta = {
            "id": img_id,
            "filename": safe,
            "raw_path": str(raw_path),
            "npy_path": str(npy_path),
            "png_path": str(ndvi_png_path),
            "preview_path": str(preview_path),
            "hash": file_hash,
            "processed": processed,
            "method": method,
            "visible_method": visible_method,
            "has_nir": has_nir,
            "indices_paths": indices_paths,
            "stats": stats,
            "stamp": stamp,
            "width": width,
            "height": height,
        }
        _save_meta(img_id, meta)

        if processed:
            _update_cache(meta)

        response = {
            "id": record.id,
            "width": record.width,
            "height": record.height,
            "processed": processed,
            "method": method,
            "has_nir": has_nir,
            "visible_method": visible_method,
            "variables": stats,
            "ndvi_stamp": stamp,
            "preview_only": not processed,
            "hash": file_hash,
        }
        for key, value in stats.items():
            response[key] = value

        return response
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def ensure_processed(img_id: str) -> Dict[str, object]:
    """Run the NDVI pipeline for ``img_id`` if it has not been processed yet."""
    meta = _load_meta(img_id)
    if meta is None:
        raise FileNotFoundError("metadata not found")
    if meta.get("processed"):
        return meta

    raw_path = Path(str(meta.get("raw_path")))
    if not raw_path.exists():
        raise FileNotFoundError("raw image not found")

    result = compute_ndvi(raw_path)
    ndvi = result.ndvi_or_approx.astype(np.float32, copy=False)

    npy_path = Path(str(meta.get("npy_path")))
    npy_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(npy_path, ndvi)

    ndvi_png_path = Path(str(meta.get("png_path")))
    save_png(ndvi, ndvi_png_path)

    method = "ndvi_approx"
    visible_method = (result.meta or {}).get("visible_method") if isinstance(result.meta, dict) else None
    if not visible_method:
        visible_method = "combined"
    has_nir = False

    indices_paths: Dict[str, str] = {}
    indices = result.indices or {}
    upper_map = {k.upper(): v for k, v in indices.items()}
    for key in VISIBLE_INDEX_KEYS:
        arr = upper_map.get(key.upper())
        if arr is None:
            continue
        path = _index_path(img_id, key)
        np.save(path, np.asarray(arr, dtype=np.float32))
        indices_paths[key] = str(path)

    stats = _compute_stats_from_indices(ndvi, upper_map)
    stamp = int(time.time())

    record = db.session.get(NDVIImage, img_id)
    if record:
        record.png_path = str(ndvi_png_path)
        record.npy_path = str(npy_path)
        record.width = int(ndvi.shape[1])
        record.height = int(ndvi.shape[0])
        db.session.commit()

    meta.update({
        "processed": True,
        "method": method,
        "visible_method": visible_method,
        "has_nir": has_nir,
        "indices_paths": indices_paths,
        "stats": stats,
        "stamp": stamp,
        "width": int(ndvi.shape[1]),
        "height": int(ndvi.shape[0]),
        "png_path": str(ndvi_png_path),
        "npy_path": str(npy_path),
    })
    _save_meta(img_id, meta)
    _update_cache(meta)

    return meta


def load_ndvi(img_id: str) -> np.ndarray:
    """Load the processed NDVI array, ensuring preprocessing ran beforehand."""
    meta = ensure_processed(img_id)
    path = Path(meta["npy_path"])
    if not path.exists():
        raise FileNotFoundError("ndvi not found")
    return np.load(path, allow_pickle=False)


# ==================== Media Controller ====================

class MediaController:
    """Orquesta la ingestión, inspección y eliminación de activos multimedia."""

    def save_local_upload(self, file: FileStorage) -> Tuple[Asset, bool]:
        """Guardar un archivo recibido vía formulario dentro del almacenamiento local."""
        if not file or not getattr(file, "filename", None):
            raise ValueError("No file provided")

        filename = file.filename
        _, ext = os.path.splitext(filename)
        ext = ext.lower()
        if not allowed_extension(filename):
            raise ValueError("Unsupported file type")

        size_bytes = 0
        try:
            stream = file.stream
            digest = sha256_of_file(stream)
            stream.seek(0, os.SEEK_END)
            size_bytes = stream.tell()
            stream.seek(0)
        except Exception:
            digest = sha256_of_file(file.stream)

        existing_asset = (
            Asset.query.filter_by(sha256=digest, size_bytes=size_bytes)
            .order_by(Asset.id.desc())
            .first()
        )
        if existing_asset:
            return existing_asset, False

        storage_key, abs_path = allocate_storage_path(ext)
        file.save(abs_path)

        if not size_bytes:
            try:
                size_bytes = os.path.getsize(abs_path)
            except OSError:
                size_bytes = 0

        mime = guess_mime(abs_path)
        img = extract_image_info(abs_path)
        geo = extract_geo_info_if_tiff(abs_path)

        asset_type = (
            AssetType.GEOTIFF.value if ext in {".tif", ".tiff"} else AssetType.IMAGE.value
        )

        asset = Asset(
            uuid=os.path.splitext(os.path.basename(abs_path))[0],
            original_name=filename,
            ext=ext.lstrip("."),
            mime=mime,
            asset_type=asset_type,
            storage=StorageLocation.LOCAL.value,
            storage_key=storage_key,
            sha256=digest,
            size_bytes=size_bytes,
            width=img.width,
            height=img.height,
            is_geo=geo.is_geo,
            crs=geo.crs,
            bounds=geo.bounds,
            transform=geo.transform,
            exif=img.exif,
        )

        db.session.add(asset)
        db.session.commit()
        return asset, True

    def delete_asset(self, asset_id: int) -> bool:
        """Retirar un activo de la base de datos y su archivo físico asociado."""
        asset = Asset.query.get(asset_id)
        if not asset:
            return False
        from .helpers import _media_root
        base = _media_root()
        abs_path = os.path.join(base, asset.storage_key)
        try:
            if os.path.isfile(abs_path):
                os.remove(abs_path)
        except Exception:
            pass
        db.session.delete(asset)
        db.session.commit()
        return True

