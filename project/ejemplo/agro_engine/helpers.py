"""Agro Engine helper utilities consolidating agrovista and media functionality.

This module prioritizes agrovista's NDVI analysis, cache handling, and processing
while integrating media's asset management capabilities.
"""

from __future__ import annotations

import hashlib
import math
import mimetypes
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from matplotlib import cm, colors
import matplotlib
from PIL import Image
import rasterio
from rasterio.errors import RasterioIOError
from rasterio.io import DatasetReader
from rasterio.transform import Affine
from rasterio.windows import Window
from werkzeug.utils import secure_filename

from flask import current_app

matplotlib.use("Agg")

try:
    from scipy.ndimage import median_filter as _median_filter
except Exception:
    _median_filter = None

# Data directory (prioritizing agrovista's structure)
DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTS = {".tif", ".tiff", ".jp2", ".png", ".jpg", ".jpeg"}

# Cache directory (agrovista's cache system)
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

VISIBLE_INDEX_KEYS = ("vari", "gli", "ngrdi", "exg")
META_SUFFIX = ".json"


# ==================== Media Storage Helpers ====================

def _media_root() -> str:
    """Return absolute path for local media storage root."""
    base = current_app.config.get("MEDIA_STORAGE_DIR") if current_app else None
    if not base:
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        base = str(project_root / "storage" / "media")
    os.makedirs(base, exist_ok=True)
    return base


def allowed_file(filename: str) -> bool:
    """Return True when the provided filename uses a supported extension."""
    return Path(filename).suffix.lower() in ALLOWED_EXTS


def allowed_extension(filename: str) -> bool:
    """Return True when ``filename`` ends with a supported raster/image extension."""
    allowed = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}
    _, ext = os.path.splitext(filename.lower())
    return ext in allowed


def guess_mime(filepath: str) -> str:
    """Infer MIME type for ``filepath`` and fall back to ``application/octet-stream``."""
    return mimetypes.guess_type(filepath)[0] or "application/octet-stream"


def sha256_of_file(fileobj) -> str:
    """Compute the SHA-256 hex digest of a file-like object without consuming it."""
    fileobj.seek(0)
    h = hashlib.sha256()
    for chunk in iter(lambda: fileobj.read(8192), b""):
        h.update(chunk)
    fileobj.seek(0)
    return h.hexdigest()


def _hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute a SHA1 hash of ``path`` using streaming reads (agrovista's method)."""
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def allocate_storage_path(ext: str) -> Tuple[str, str]:
    """Create a unique storage path and return (storage_key, abs_path)."""
    uid = str(uuid.uuid4())
    shard1, shard2 = uid[:2], uid[2:4]
    rel_dir = os.path.join("local", shard1, shard2)
    abs_dir = os.path.join(_media_root(), rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    filename = f"{uid}{ext}"
    storage_key = os.path.join(rel_dir, filename)
    abs_path = os.path.join(abs_dir, filename)
    return storage_key, abs_path


@dataclass
class ImageInfo:
    """Metadata snapshot extracted from an image file."""
    width: Optional[int] = None
    height: Optional[int] = None
    exif: Optional[dict] = None


def extract_image_info(filepath: str) -> ImageInfo:
    """Return basic width/height/EXIF information for an image file."""
    info = ImageInfo()
    try:
        from PIL import Image, ExifTags
        with Image.open(filepath) as im:
            info.width, info.height = im.size
            try:
                raw_exif = im._getexif() or {}
                exif = {}
                for tag_id, value in raw_exif.items():
                    tag = ExifTags.TAGS.get(tag_id, tag_id)
                    exif[str(tag)] = value
                info.exif = exif
            except Exception:
                info.exif = None
        return info
    except Exception:
        pass

    try:
        with rasterio.open(filepath) as src:
            info.width = int(src.width)
            info.height = int(src.height)
        return info
    except Exception:
        return info


@dataclass
class GeoInfo:
    """Geospatial metadata for raster files."""
    is_geo: bool = False
    crs: Optional[str] = None
    bounds: Optional[dict] = None
    transform: Optional[dict] = None


def extract_geo_info_if_tiff(filepath: str) -> GeoInfo:
    """Extract CRS, bounds, and transform from GeoTIFF files when available."""
    geo = GeoInfo()
    ext = os.path.splitext(filepath.lower())[1]
    if ext not in {".tif", ".tiff"}:
        return geo
    try:
        with rasterio.open(filepath) as src:
            geo.is_geo = True
            try:
                geo.crs = src.crs.to_string() if src.crs else None
            except Exception:
                geo.crs = None
            try:
                b = src.bounds
                geo.bounds = {"left": b.left, "bottom": b.bottom, "right": b.right, "top": b.top}
            except Exception:
                geo.bounds = None
            try:
                t = src.transform
                geo.transform = {
                    "a": t.a, "b": t.b, "c": t.c, "d": t.d, "e": t.e, "f": t.f,
                }
            except Exception:
                geo.transform = None
    except Exception:
        pass
    return geo


# ==================== Agrovista Cache Helpers (Priority) ====================

def _cache_dir(file_hash: str) -> Path:
    """Return the cache directory that corresponds to ``file_hash``."""
    return CACHE_DIR / file_hash


def _cache_meta_path(file_hash: str) -> Path:
    """Return the metadata path inside the cache for ``file_hash``."""
    return _cache_dir(file_hash) / "meta.json"


def _index_path(img_id: str, key: str) -> Path:
    """Return the file path where the cached index array should be stored."""
    key_lc = key.lower()
    return DATA_DIR / f"{img_id}_{key_lc}.npy"


def _meta_path(img_id: str) -> Path:
    """Return the metadata JSON path for the provided image id."""
    return DATA_DIR / f"{img_id}{META_SUFFIX}"


def _load_json(path: Path) -> Dict[str, object] | None:
    """Load a JSON file returning ``None`` on error."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            import json
            return json.load(fh)
    except Exception:
        return None


def _save_json(path: Path, data: Dict[str, object]) -> None:
    """Atomically save JSON to disk by writing to a temp file first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    import json
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _load_meta(img_id: str) -> Dict[str, object] | None:
    """Load on-disk metadata for a single NDVI image."""
    return _load_json(_meta_path(img_id))


def _save_meta(img_id: str, data: Dict[str, object]) -> None:
    """Persist metadata for ``img_id``."""
    _save_json(_meta_path(img_id), data)


def _load_cache_meta(file_hash: str) -> Dict[str, object] | None:
    """Load cached metadata associated with ``file_hash``."""
    return _load_json(_cache_meta_path(file_hash))


def _save_cache_meta(file_hash: str, data: Dict[str, object]) -> None:
    """Save cached metadata associated with ``file_hash``."""
    _save_json(_cache_meta_path(file_hash), data)


# ==================== Color & IO Utils ====================

def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    """Convert sRGB samples in the ``[0, 1]`` range into linear RGB."""
    a, thr = 0.055, 0.04045
    y = np.empty_like(x, dtype=np.float32)
    low = x <= thr
    y[low] = x[low] / 12.92
    y[~low] = ((x[~low] + a) / (1.0 + a)) ** 2.4
    return y


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    """Convert linear RGB to sRGB (gamma application)."""
    a, thr = 0.055, 0.0031308
    y = np.empty_like(x, dtype=np.float32)
    low = x <= thr
    y[low] = 12.92 * x[low]
    y[~low] = (1 + a) * (x[~low]) ** (1 / 2.4) - a
    return np.clip(y, 0.0, 1.0).astype(np.float32)


def gray_world_white_balance(img: np.ndarray) -> np.ndarray:
    """Apply gray-world white balance on linear RGB values."""
    means = img.reshape(-1, 3).mean(axis=0)
    scale = means.mean() / (means + 1e-8)
    return np.clip(img * scale, 0, 1)


def gray_world(img_lin: np.ndarray) -> np.ndarray:
    """Apply Gray-World white balance to linear RGB (alias for compatibility)."""
    if img_lin.shape[-1] != 3:
        raise ValueError("img_lin must have last dimension of size 3 (RGB).")
    means = img_lin.reshape(-1, 3).mean(axis=0)
    scale = means.mean() / (means + 1e-8)
    return np.clip(img_lin * scale, 0.0, 1.0).astype(np.float32)


def _band_max(dtype_str: str) -> float:
    """Return the maximum representable value for raster bands."""
    try:
        info = np.iinfo(np.dtype(dtype_str))
        return float(info.max)
    except Exception:
        return 1.0


def _dtype_max(dtype_str: str) -> float:
    """Return the maximum representable integer value for a raster dtype."""
    try:
        return float(np.iinfo(np.dtype(dtype_str)).max)
    except Exception:
        return 1.0


def read_rgb_from_any(path: Path) -> np.ndarray:
    """Return RGB data from common raster formats as linearized float arrays."""
    p = Path(path)
    try:
        with rasterio.open(p) as src:
            if src.count >= 3:
                r = src.read(1).astype(np.float32)
                g = src.read(2).astype(np.float32)
                b = src.read(3).astype(np.float32)
                maxv = _band_max(src.dtypes[0])
                if maxv > 1:
                    r /= maxv
                    g /= maxv
                    b /= maxv
                rgb = np.stack([r, g, b], axis=-1)
                if src.nodata is not None:
                    nod = src.nodata
                    mask = (r == nod) | (g == nod) | (b == nod)
                    rgb[mask] = np.nan
                return rgb
    except Exception:
        pass

    im = Image.open(p).convert("RGB")
    rgb = np.asarray(im, dtype=np.float32) / 255.0
    return rgb


def read_rgb(path: Path) -> np.ndarray:
    """Read an image and return sRGB float32 in [0, 1]."""
    if not Path(path).exists():
        raise FileNotFoundError(f"File not found: {path}")

    try:
        with rasterio.open(path) as src:
            if src.count < 3:
                raise ValueError("Raster has fewer than 3 bands.")
            r = src.read(1).astype(np.float32)
            g = src.read(2).astype(np.float32)
            b = src.read(3).astype(np.float32)
            maxv = _dtype_max(src.dtypes[0])
            if maxv > 1.0:
                r, g, b = r / maxv, g / maxv, b / maxv
            rgb = np.stack([r, g, b], axis=-1).astype(np.float32)
            if src.nodata is not None:
                nod = src.nodata
                mask = (r == nod) | (g == nod) | (b == nod)
                rgb[mask] = np.nan
            return rgb.astype(np.float32)
    except Exception:
        im = Image.open(path).convert("RGB")
        return (np.asarray(im, dtype=np.float32) / 255.0).astype(np.float32)


def read_red_nir(
    src: DatasetReader,
    red_band: int = 3,
    nir_band: int = 4,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return red and near-infrared bands ready for NDVI math."""
    red = src.read(red_band).astype(np.float32)
    nir = src.read(nir_band).astype(np.float32)
    maxv = _band_max(src.dtypes[0])
    if maxv > 1:
        red /= maxv
        nir /= maxv
    if src.nodata is not None:
        mask = (red == src.nodata) | (nir == src.nodata)
        red[mask] = np.nan
        nir[mask] = np.nan
    return red, nir


def save_quick_preview(
    src_path: Path,
    out_path: Path,
    max_size: int = 1024,
) -> Tuple[int, int]:
    """Generate a fast RGB preview PNG from the source image."""
    rgb = read_rgb_from_any(src_path)
    if rgb.ndim != 3:
        raise ValueError("preview requires RGB data")
    arr = np.nan_to_num(rgb, nan=0.0)
    arr = np.clip(arr, 0.0, 1.0)
    im = Image.fromarray((arr * 255).astype(np.uint8))
    w, h = im.size
    if max(w, h) > max_size:
        im.thumbnail((max_size, max_size))
    im.save(out_path)
    return im.size


# ==================== Visible Indices & Combination ====================

@dataclass(slots=True)
class VisibleConfig:
    """Toggles controlling the preprocessing pipeline for visible indices."""
    do_linearize: bool = True
    do_white_balance: bool = True
    shadow_mask: bool = True
    shadow_thr: float = 0.06
    median_size: int = 3


def compute_visible_indices(
    rgb: np.ndarray,
    cfg: VisibleConfig,
) -> Dict[str, np.ndarray]:
    """Compute VARI, NGRDI, GLI, and ExG indices from RGB imagery."""
    arr = rgb.copy().astype(np.float32)
    nan_mask = np.isnan(arr).any(axis=-1)
    arr[nan_mask] = 0.0

    if cfg.do_linearize:
        arr = srgb_to_linear(arr)
    if cfg.do_white_balance:
        arr = gray_world_white_balance(arr)

    R = arr[..., 0]
    G = arr[..., 1]
    B = arr[..., 2]
    eps = 1e-6

    with np.errstate(divide="ignore", invalid="ignore"):
        vari = (G - R) / (G + R - B + eps)
        ngrdi = (G - R) / (G + R + eps)
        gli = (2 * G - R - B) / (2 * G + R + B + eps)
        total = R + G + B
        rN = np.where(total > 0, R / (total + eps), 0.0)
        gN = np.where(total > 0, G / (total + eps), 0.0)
        bN = np.where(total > 0, B / (total + eps), 0.0)
        exg = 2.0 * gN - rN - bN

    dark = np.zeros_like(ngrdi, dtype=bool)
    if cfg.shadow_mask:
        dark = (R + G + B) < cfg.shadow_thr
        for arr_idx in (vari, ngrdi, gli, exg):
            arr_idx[dark] = np.nan

    out = {
        "VARI": np.clip(vari, -1, 1),
        "NGRDI": np.clip(ngrdi, -1, 1),
        "GLI": np.clip(gli, -1, 1),
        "ExG": np.clip(exg, -1, 1),
        "shadow_mask": dark,
        "preproc_nan": nan_mask,
    }

    if cfg.median_size and cfg.median_size > 1 and _median_filter is not None:
        for k in ("VARI", "NGRDI", "GLI", "ExG"):
            x = out[k]
            valid = np.isfinite(x)
            x_f = x.copy()
            x_f[~valid] = 0
            x_f = _median_filter(x_f, size=cfg.median_size)
            x_f[~valid] = np.nan
            out[k] = x_f

    for k in ("VARI", "NGRDI", "GLI", "ExG"):
        x = out[k]
        x[nan_mask] = np.nan
        out[k] = x

    return out


def visible_indices(rgb_lin: np.ndarray) -> Dict[str, np.ndarray]:
    """Compute visible-only vegetation indices from linear RGB."""
    if rgb_lin.shape[-1] != 3:
        raise ValueError("rgb_lin must have last dimension of size 3 (RGB).")
    r, g, b = rgb_lin[..., 0], rgb_lin[..., 1], rgb_lin[..., 2]
    eps = 1e-6
    with np.errstate(divide="ignore", invalid="ignore"):
        vari = (g - r) / (g + r - b + eps)
        ngrdi = (g - r) / (g + r + eps)
        gli = (2.0 * g - r - b) / (2.0 * g + r + b + eps)
        total = r + g + b
        r_n, g_n, b_n = r / (total + eps), g / (total + eps), b / (total + eps)
        exg = 2.0 * g_n - r_n - b_n
    return {
        "VARI": np.clip(vari, -1.0, 1.0).astype(np.float32),
        "NGRDI": np.clip(ngrdi, -1.0, 1.0).astype(np.float32),
        "GLI": np.clip(gli, -1.0, 1.0).astype(np.float32),
        "ExG": np.clip(exg, -1.0, 1.0).astype(np.float32),
    }


def combine_indices(
    indices: Dict[str, np.ndarray],
    method: str = "combined",
    weights: Tuple[float, float, float, float] = (0.4, 0.3, 0.2, 0.1),
) -> np.ndarray:
    """Return a pseudo-NDVI map synthesized from visible-band indices."""
    v = indices
    if method == "ngrdi":
        out = v["NGRDI"]
    elif method == "vari":
        out = v["VARI"]
    elif method == "gli":
        out = v["GLI"]
    elif method == "exg":
        out = v["ExG"]
    else:
        out = (
            weights[0] * v["NGRDI"]
            + weights[1] * v["VARI"]
            + weights[2] * v["GLI"]
            + weights[3] * v["ExG"]
        )
    return np.clip(out, -1, 1)


# ==================== True NDVI (with NIR) ====================

def compute_true_ndvi(
    src: DatasetReader,
    red_band: int = 3,
    nir_band: int = 4,
) -> np.ndarray:
    """Compute NDVI directly from red and near-infrared bands."""
    red, nir = read_red_nir(src, red_band=red_band, nir_band=nir_band)
    denom = nir + red
    ndvi = np.divide(
        nir - red,
        denom,
        out=np.full_like(red, np.nan, dtype=np.float32),
        where=denom != 0,
    )
    return ndvi.astype(np.float32)


def true_ndvi(
    src: DatasetReader,
    red_band: int = 3,
    nir_band: int = 4,
) -> np.ndarray:
    """Compute true NDVI from an open rasterio dataset (alias)."""
    return compute_true_ndvi(src, red_band=red_band, nir_band=nir_band)


# ==================== Pipeline Interface ====================

@dataclass(slots=True)
class PipelineResult:
    """Container returned by :func:`compute_ndvi` with extra metadata."""
    method: str
    has_nir: bool
    ndvi_or_approx: np.ndarray
    indices: Optional[Dict[str, np.ndarray]]
    meta: Dict[str, object]


def compute_ndvi(
    src_path: Path,
    *,
    red_band: int = 3,
    nir_band: int = 4,
    method: str = "combined",
    weights: Tuple[float, float, float, float] = (0.4, 0.3, 0.2, 0.1),
    visible_cfg: Optional[VisibleConfig] = None,
) -> PipelineResult:
    """Compute NDVI using NIR bands when available or a visible approximation."""
    visible_cfg = visible_cfg or VisibleConfig()
    path = Path(src_path)

    try:
        with rasterio.open(path) as src:
            has_nir = src.count >= max(red_band, nir_band)
            meta: Dict[str, object] = {
                "source": str(path),
                "bands": src.count,
                "dtype": tuple(src.dtypes),
                "crs": src.crs.to_string() if src.crs else None,
                "transform": tuple(src.transform),
                "nodata": src.nodata,
            }

            if has_nir:
                ndvi = compute_true_ndvi(src, red_band=red_band, nir_band=nir_band)
                indices: Optional[Dict[str, np.ndarray]] = None

                if src.count >= 3:
                    try:
                        r = src.read(1).astype(np.float32)
                        g = src.read(2).astype(np.float32)
                        b = src.read(3).astype(np.float32)
                        nod_mask = None
                        if src.nodata is not None:
                            nod = src.nodata
                            nod_mask = (r == nod) | (g == nod) | (b == nod)
                        maxv = _band_max(src.dtypes[0])
                        if maxv > 1:
                            r /= maxv
                            g /= maxv
                            b /= maxv
                        rgb = np.stack([r, g, b], axis=-1)
                        if nod_mask is not None:
                            rgb[nod_mask] = np.nan
                        indices = compute_visible_indices(rgb, visible_cfg)
                    except Exception:
                        indices = None

                meta.update({
                    "has_nir": True,
                    "method": "ndvi",
                    "visible_method": None,
                })
                return PipelineResult("ndvi", True, ndvi, indices, meta)

        # No NIR bands detected; fall back to visible indices.
        rgb = read_rgb_from_any(path)
        indices = compute_visible_indices(rgb, visible_cfg)
        ndvi_approx = combine_indices(indices, method=method, weights=weights)
        meta = {
            "source": str(path),
            "bands": rgb.shape[-1],
            "has_nir": False,
            "method": "ndvi_approx",
            "visible_method": method,
            "weights": weights if method == "combined" else None,
        }
        return PipelineResult("ndvi_approx", False, ndvi_approx, indices, meta)

    except RasterioIOError:
        rgb = read_rgb_from_any(path)
        if rgb.shape[-1] < 3:
            raise ValueError(
                "Input image must contain at least three channels for NDVI approximation"
            )
        indices = compute_visible_indices(rgb, visible_cfg)
        ndvi_approx = combine_indices(indices, method=method, weights=weights)
        meta = {
            "source": str(path),
            "bands": rgb.shape[-1],
            "has_nir": False,
            "method": "ndvi_approx",
            "visible_method": method,
            "weights": weights if method == "combined" else None,
        }
        return PipelineResult("ndvi_approx", False, ndvi_approx, indices, meta)


# ==================== PNG Utilities ====================

def save_png_float(
    arr: np.ndarray,
    out_path: Path,
    *,
    cmap_name: str = "RdYlGn",
    vmin: float = -1.0,
    vmax: float = 1.0,
    percentile_stretch: Tuple[float, float] | None = None,
    transparent_nodata: bool = True,
) -> None:
    """Save a float map as PNG (RGBA) with the given colormap."""
    arr = arr.astype(np.float32)
    valid = np.isfinite(arr)

    if percentile_stretch is not None and valid.any():
        p_lo, p_hi = percentile_stretch
        lo, hi = np.nanpercentile(arr, [p_lo, p_hi])
        if hi > lo:
            vmin, vmax = float(lo), float(hi)

    norm = colors.Normalize(vmin=vmin, vmax=vmax, clip=True)
    cmap = cm.get_cmap(cmap_name).copy()
    cmap.set_bad((0, 0, 0, 0))

    rgba = (cmap(norm(arr)) * 255).astype("uint8")
    if transparent_nodata:
        rgba[..., 3] = np.where(valid, 255, 0)
    Image.fromarray(rgba, mode="RGBA").save(out_path)


def save_png(ndvi: np.ndarray, out_path: Path) -> None:
    """Backward-compatible shorthand that delegates to ``save_png_float``."""
    save_png_float(ndvi, out_path, cmap_name="RdYlGn", vmin=-1, vmax=1)


# ==================== Protein Estimation ====================

DEFAULT_PROTEIN_TABLE: List[Tuple[float, float]] = [
    (0.10, 6.0),
    (0.40, 12.0),
    (0.70, 18.0),
]


def ndvi_to_protein(
    value: float,
    table: Sequence[Tuple[float, float]] | None = None,
) -> float:
    """Interpolate a single NDVI value into a protein estimate."""
    table = table or DEFAULT_PROTEIN_TABLE
    xs = np.array([x for x, _ in table], dtype=np.float32)
    ys = np.array([y for _, y in table], dtype=np.float32)
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    if not (xs[0] <= value <= xs[-1]):
        return float("nan")
    return float(np.interp(value, xs, ys))


def ndvi_to_protein_vec(
    values: np.ndarray,
    table: Sequence[Tuple[float, float]] | None = None,
) -> np.ndarray:
    """Vectorized variant of :func:`ndvi_to_protein` for entire rasters."""
    table = table or DEFAULT_PROTEIN_TABLE
    xs = np.array([x for x, _ in table], dtype=np.float32)
    ys = np.array([y for _, y in table], dtype=np.float32)
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    out = np.interp(values, xs, ys)
    out[(values < xs[0]) | (values > xs[-1]) | ~np.isfinite(values)] = np.nan
    return out.astype(np.float32)


def protein_to_nitrogen(value: float, factor: float = 6.25) -> float:
    """Convert protein percentage into nitrogen percentage."""
    if factor <= 0:
        return float("nan")
    if not np.isfinite(value):
        return float("nan")
    return float(value / factor)


def protein_to_nitrogen_vec(values: np.ndarray, factor: float = 6.25) -> np.ndarray:
    """Vectorized version of :func:`protein_to_nitrogen` for rasters."""
    out = np.full_like(values, np.nan, dtype=np.float32)
    if factor <= 0:
        return out
    mask = np.isfinite(values)
    out[mask] = (values[mask] / factor).astype(np.float32)
    return out


# ==================== Polygon Masking ====================

def polygon_mask(
    shape: Tuple[int, int],
    vertices: Iterable[Tuple[float, float]],
    transform: Optional[Affine] = None,
) -> np.ndarray:
    """Return a boolean mask describing the pixels contained in a polygon."""
    from matplotlib.path import Path as MplPath

    verts = np.asarray(list(vertices), dtype=np.float64)
    if transform is not None:
        inv = ~transform
        pts = np.array([inv * (x, y) for x, y in verts], dtype=np.float64)
    else:
        pts = verts

    y_idx, x_idx = np.meshgrid(np.arange(shape[0]), np.arange(shape[1]), indexing="ij")
    coords = np.column_stack((x_idx.ravel() + 0.5, y_idx.ravel() + 0.5))
    return MplPath(pts).contains_points(coords).reshape(shape)


def average_protein(
    ndvi_map: np.ndarray,
    mask: np.ndarray,
    table: Sequence[Tuple[float, float]] | None = None,
    min_count: int = 20,
    reducer: str = "mean",
) -> float:
    """Summarize protein estimates inside a polygon mask."""
    valid = mask & np.isfinite(ndvi_map)
    vals = ndvi_map[valid]
    if vals.size < min_count:
        return float("nan")
    prot = ndvi_to_protein_vec(vals, table=table)
    prot = prot[np.isfinite(prot)]
    if prot.size == 0:
        return float("nan")
    return float(np.median(prot) if reducer == "median" else np.mean(prot))


# ==================== Secondary Objective Estimations ====================

def _coerce_non_negative(value: float | int | None) -> float:
    """Cast inputs to ``float`` while ensuring non-negative results."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(v):
        return 0.0
    return max(v, 0.0)


def _dummy_rule_factory(
    factor: float,
    *,
    bias: float = 0.0,
    min_nitrogen: float = 0.05,
) -> Callable[[float, float], float]:
    """Return simplistic rules that map protein/nitrogen to nutrient targets."""
    def _rule(protein: float, nitrogen: float) -> float:
        prot = _coerce_non_negative(protein)
        nit = _coerce_non_negative(nitrogen)
        if nit < min_nitrogen:
            nit = min_nitrogen
        return bias + prot * nit * factor
    return _rule


DEFAULT_SECONDARY_RULE = _dummy_rule_factory(1.0)

NUTRIENT_DUMMY_RULES: Dict[str, Callable[[float, float], float]] = {
    "n": _dummy_rule_factory(8.4, bias=0.12),
    "nitrogeno": _dummy_rule_factory(8.4, bias=0.12),
    "p": _dummy_rule_factory(3.6, bias=0.05),
    "fosforo": _dummy_rule_factory(3.6, bias=0.05),
    "k": _dummy_rule_factory(4.8, bias=0.08),
    "potasio": _dummy_rule_factory(4.8, bias=0.08),
    "ca": _dummy_rule_factory(1.9, bias=0.04),
    "calcio": _dummy_rule_factory(1.9, bias=0.04),
    "mg": _dummy_rule_factory(1.5, bias=0.03),
    "magnesio": _dummy_rule_factory(1.5, bias=0.03),
    "s": _dummy_rule_factory(1.15, bias=0.02),
    "azufre": _dummy_rule_factory(1.15, bias=0.02),
    "cu": _dummy_rule_factory(0.045, bias=0.001, min_nitrogen=0.01),
    "cobre": _dummy_rule_factory(0.045, bias=0.001, min_nitrogen=0.01),
    "zn": _dummy_rule_factory(0.062, bias=0.001, min_nitrogen=0.01),
    "zinc": _dummy_rule_factory(0.062, bias=0.001, min_nitrogen=0.01),
    "mn": _dummy_rule_factory(0.081, bias=0.001, min_nitrogen=0.01),
    "manganeso": _dummy_rule_factory(0.081, bias=0.001, min_nitrogen=0.01),
    "b": _dummy_rule_factory(0.024, bias=0.0005, min_nitrogen=0.01),
    "boro": _dummy_rule_factory(0.024, bias=0.0005, min_nitrogen=0.01),
    "mo": _dummy_rule_factory(0.0009, bias=0.0001, min_nitrogen=0.01),
    "molibdeno": _dummy_rule_factory(0.0009, bias=0.0001, min_nitrogen=0.01),
    "fe": _dummy_rule_factory(0.27, bias=0.002, min_nitrogen=0.02),
    "hierro": _dummy_rule_factory(0.27, bias=0.002, min_nitrogen=0.02),
    "si": _dummy_rule_factory(0.18, bias=0.001, min_nitrogen=0.02),
    "silicio": _dummy_rule_factory(0.18, bias=0.001, min_nitrogen=0.02),
}


def compute_secondary_objective_targets(
    protein_average: float,
    nitrogen_estimated: float,
    nutrients: Sequence[object],
    *,
    digits: int | None = 3,
) -> List[Dict[str, object]]:
    """Return dummy nutrient targets for a given protein/nitrogen pair."""
    def _resolve_rule(symbol: str | None, name: str | None) -> Callable[[float, float], float]:
        for key in filter(None, [symbol, name]):
            key_l = key.lower()
            if key_l in NUTRIENT_DUMMY_RULES:
                return NUTRIENT_DUMMY_RULES[key_l]
        return DEFAULT_SECONDARY_RULE

    out: List[Dict[str, object]] = []
    for nutrient in nutrients:
        symbol = getattr(nutrient, "symbol", None)
        name = getattr(nutrient, "name", None)
        unit = getattr(nutrient, "unit", None)
        nutrient_id = getattr(nutrient, "id", None)
        func = _resolve_rule(symbol, name)
        value = func(protein_average, nitrogen_estimated)
        if digits is not None and math.isfinite(value):
            value = round(value, digits)
        out.append({
            "nutrient_id": nutrient_id,
            "nutrient_name": name,
            "nutrient_symbol": symbol,
            "nutrient_unit": unit,
            "target_value": value,
        })
    return out


def secondary_target_map(
    protein_average: float,
    nitrogen_estimated: float,
    nutrients: Sequence[object],
    *,
    digits: int | None = 3,
) -> Dict[int, float]:
    """Return a mapping from nutrient identifiers to target values."""
    mapping: Dict[int, float] = {}
    for payload in compute_secondary_objective_targets(
        protein_average,
        nitrogen_estimated,
        nutrients,
        digits=digits,
    ):
        nutrient_id = payload.get("nutrient_id")
        target_value = payload.get("target_value")
        if nutrient_id is None:
            continue
        try:
            mapping[int(nutrient_id)] = float(target_value)
        except (TypeError, ValueError):
            continue
    return mapping

