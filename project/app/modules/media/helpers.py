from __future__ import annotations

"""
Image preprocessing and vegetation indices utilities.

This module provides:
- Color space transforms (sRGB <-> linear).
- Simple gray-world white balance.
- Robust RGB reading from PNG/JPG/TIFF (8/16-bit, with NoData).
- NDVI computation when NIR is available, and visible-only indices
  (VARI, NGRDI/GRVI, GLI, ExG) when it is not.
- One-shot preprocessing with on-disk caching (PNG preview + NPZ exact floats).
- Minimal orchestration that chooses the NDVI path (with NIR) or the
  visible-only approximation path (without NIR).

Design goals:
- Numerical safety: float32 pipelines, NaN propagation, and guarded divisions.
- IO robustness: handle NoData, 8/16-bit scaling, and common image formats.
- Reproducibility: cache of exact linear RGB in NPZ and a UI-friendly PNG.
- Downstream integration: write float32 GeoTIFFs (tiled, compressed) to
  interoperate with GIS pipelines without excessive memory.

Notes:
- Inputs and outputs use float32 by default to limit memory footprint.
- NDVI ∈ [-1, 1]. Visible-only indices are returned clipped to [-1, 1].
- PNG previews are quicklooks; scientific consumers should prefer GeoTIFF/NPZ.
"""

import hashlib
import json
import math
import mimetypes
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import rasterio
from flask import current_app
from numpy.typing import NDArray
from PIL import Image
from rasterio.enums import Resampling
from rasterio.io import DatasetReader
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window
from werkzeug.datastructures import FileStorage


def _media_root() -> str:
    """Return absolute path for local media storage root.

    Defaults to `<project-root>/storage/media` if MEDIA_STORAGE_DIR is not set.
    """
    base = current_app.config.get("MEDIA_STORAGE_DIR")
    if not base:
        # Project root is two levels above app/__init__.py
        project_root = os.path.abspath(os.path.join(current_app.root_path, os.pardir))
        base = os.path.join(project_root, "storage", "media")
    os.makedirs(base, exist_ok=True)
    return base


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


@dataclass
class UploadCapture:
    """Temporary persisted upload metadata before final storage."""

    temp_path: str
    size_bytes: int
    sha256: str

    def discard(self) -> None:
        """Remove the temporary file if it still exists."""

        try:
            os.remove(self.temp_path)
        except FileNotFoundError:
            return
        except Exception:
            current_app.logger.debug(
                "media: unable to discard temp upload %s", self.temp_path
            )

    def move_to(self, destination: str) -> None:
        """Move the temporary file to ``destination`` replacing existing files."""

        os.makedirs(os.path.dirname(destination), exist_ok=True)
        os.replace(self.temp_path, destination)


def capture_upload_to_temp(
    file: FileStorage, *, chunk_size: int | None = None
) -> UploadCapture:
    """Stream ``file`` into a temporary location while hashing and measuring size."""

    cfg_chunk = (
        chunk_size
        or current_app.config.get("MEDIA_UPLOAD_CHUNK_SIZE")
        or (16 * 1024 * 1024)
    )
    chunk_len = max(int(cfg_chunk), 1024 * 1024)
    tmp_dir = current_app.config.get("MEDIA_UPLOAD_TMP_DIR")
    if not tmp_dir:
        tmp_dir = os.path.join(_media_root(), "tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    stream = file.stream
    try:
        stream.seek(0)
    except Exception:
        pass

    digest = hashlib.sha256()
    size = 0
    suffix = Path(file.filename or "").suffix or ".upload"
    tmp_path = None

    with tempfile.NamedTemporaryFile(
        prefix="media-upload-", suffix=suffix, dir=tmp_dir, delete=False
    ) as tmp:
        while True:
            chunk = stream.read(chunk_len)
            if not chunk:
                break
            tmp.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        try:
            tmp.flush()
            if os.getenv("MEDIA_UPLOAD_FSYNC", "false").lower() == "true":
                os.fsync(tmp.fileno())
        except Exception:
            pass
        tmp_path = tmp.name

    try:
        stream.seek(0)
    except Exception:
        pass

    if tmp_path is None:
        raise RuntimeError("media: temporary upload path not created")

    return UploadCapture(temp_path=tmp_path, size_bytes=size, sha256=digest.hexdigest())


@dataclass
class ImageInfo:
    """Metadata snapshot extracted from an image file."""

    width: Optional[int] = None
    height: Optional[int] = None
    exif: Optional[dict] = None


def extract_image_info(filepath: str) -> ImageInfo:
    """Return basic width/height/EXIF information for an image file."""
    info = ImageInfo()
    # Try Pillow first
    try:
        from PIL import ExifTags, Image  # type: ignore

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

    # Fallback: attempt rasterio for tiffs (gives width/height too)
    try:
        import rasterio  # type: ignore

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
        import rasterio  # type: ignore

        with rasterio.open(filepath) as src:
            geo.is_geo = True
            try:
                geo.crs = src.crs.to_string() if src.crs else None
            except Exception:
                geo.crs = None
            try:
                b = src.bounds
                geo.bounds = {
                    "left": b.left,
                    "bottom": b.bottom,
                    "right": b.right,
                    "top": b.top,
                }
            except Exception:
                geo.bounds = None
            try:
                t = src.transform
                geo.transform = {
                    "a": t.a,
                    "b": t.b,
                    "c": t.c,
                    "d": t.d,
                    "e": t.e,
                    "f": t.f,
                }
            except Exception:
                geo.transform = None
    except Exception:
        # Not a fatal error; treat as non-geo
        pass
    return geo


# Límite duro del formato TIFF clásico: offsets de 32 bits.
TIFF_CLASSIC_MAX_BYTES = 4 * 1024 * 1024 * 1024

TIFF_INVALID_HINT = (
    "El archivo TIFF está corrupto o incompleto: la cabecera no apunta a un "
    "índice (IFD) válido. Esto suele ocurrir cuando el software que generó "
    "la ortofoto supera el límite de 4 GiB del formato TIFF clásico sin usar "
    "BigTIFF. Re-exporte como BigTIFF o COG (o con compresión) y vuelva a "
    "subir el archivo."
)


def validate_tiff_upload(filepath: str, size_bytes: int) -> Optional[str]:
    """Valida la cabecera de un TIFF antes de aceptarlo en la biblioteca.

    Lee solo los primeros 8 bytes, así que es seguro para archivos de varios
    GB. Devuelve un mensaje de error accionable o ``None`` si la estructura
    es válida.
    """
    try:
        with open(filepath, "rb") as fh:
            header = fh.read(8)
    except OSError:
        return "No se pudo leer el archivo subido."
    if len(header) < 8:
        return "El archivo es demasiado pequeño para ser un TIFF válido."

    if header[:2] == b"II":
        byteorder = "little"
    elif header[:2] == b"MM":
        byteorder = "big"
    else:
        return (
            "El archivo no tiene cabecera TIFF válida pese a su extensión. "
            "Verifique el export y vuelva a subirlo."
        )

    version = int.from_bytes(header[2:4], byteorder)
    if version == 43:
        # BigTIFF: offsets de 64 bits, sin límite de 4 GiB.
        return None
    if version != 42:
        return TIFF_INVALID_HINT

    # TIFF clásico: el offset al primer IFD no puede ser 0 ni apuntar fuera
    # del archivo, y el formato no puede direccionar >= 4 GiB.
    first_ifd_offset = int.from_bytes(header[4:8], byteorder)
    if first_ifd_offset == 0 or first_ifd_offset >= size_bytes:
        return TIFF_INVALID_HINT
    if size_bytes >= TIFF_CLASSIC_MAX_BYTES:
        return (
            "El archivo declara formato TIFF clásico pero pesa 4 GiB o más, "
            "tamaño que ese formato no puede direccionar; el export quedó "
            "corrupto casi con certeza. Re-exporte como BigTIFF o COG y "
            "vuelva a subirlo."
        )
    return None


_RASTER_UNREADABLE_PATTERNS = (
    "not recognized as being in a supported file format",
    "cannot identify image file",
)


def friendly_preprocess_error(raw: Optional[str]) -> Optional[str]:
    """Traduce errores crudos de GDAL/Pillow a un mensaje accionable.

    Se aplica al texto de ``.error`` / ``.status.json`` antes de mostrarlo
    en la vista de elemento o en el endpoint de estado.
    """
    if not raw:
        return raw
    lowered = raw.lower()
    if any(pattern in lowered for pattern in _RASTER_UNREADABLE_PATTERNS):
        return (
            "El archivo no puede leerse como raster: está corrupto o el "
            "export quedó incompleto (típico al superar el límite de 4 GiB "
            "del formato TIFF clásico). Reprocesar no lo corregirá: "
            "re-exporte como BigTIFF o COG y suba el archivo de nuevo."
        )
    return raw


def allocate_storage_path(ext: str) -> Tuple[str, str]:
    """Create a unique storage path and return (storage_key, abs_path).

    Path schema: local/<first2>/<next2>/<uuid>.<ext>
    """
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
class ThumbnailResult:
    """Description of a generated thumbnail variant stored on disk."""

    kind: str
    storage_key: str
    width: Optional[int]
    height: Optional[int]


def allocate_variant_path(
    asset_uuid: str, kind: str, ext: str = "webp"
) -> Tuple[str, str]:
    """Return storage key/absolute path for a derivative of ``asset_uuid``."""

    rel_dir = os.path.join("variants", kind, asset_uuid[:2], asset_uuid[2:4])
    abs_dir = os.path.join(_media_root(), rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    filename = f"{asset_uuid}-{kind}.{ext}"
    storage_key = os.path.join(rel_dir, filename)
    abs_path = os.path.join(abs_dir, filename)
    return storage_key, abs_path


def generate_webp_thumbnails(
    src_path: str,
    asset_uuid: str,
    specs: Optional[dict] = None,
) -> List[ThumbnailResult]:
    """Generate WebP thumbnails for the given image and return metadata.

    The default specification produces a single ``gallery`` thumbnail bounded by
    512x512 px which maps well to the card width used in the media library grid
    (~300 px on desktop) while still yielding a crisp result on HiDPI displays.
    The processing pipeline prefers the lightest operations available in Pillow
    to keep CPU and memory usage low during high-volume uploads.
    """

    try:
        from PIL import Image, ImageOps  # type: ignore
    except Exception:
        current_app.logger.warning(
            "Pillow not available; skipping thumbnail generation"
        )
        return []

    # Default to a single thumbnail tuned for the library grid unless
    # configuration overrides are provided.
    default_specs = {
        "gallery": {"max_width": 512, "max_height": 512, "quality": 82, "method": 3}
    }
    specs = specs or current_app.config.get("MEDIA_THUMBNAIL_SPECS", default_specs)

    results: List[ThumbnailResult] = []

    def build_image_via_rasterio(target_dims: Tuple[int, int]):
        try:
            import numpy as np  # type: ignore
            import rasterio  # type: ignore
            from rasterio.enums import Resampling  # type: ignore
        except Exception:
            return None

        try:
            with rasterio.open(src_path) as src:
                band_count = max(1, min(3, src.count))
                indexes = list(range(1, band_count + 1))
                scale = max(src.width / target_dims[0], src.height / target_dims[1], 1)
                out_w = max(1, int(src.width / scale))
                out_h = max(1, int(src.height / scale))
                data = src.read(
                    indexes=indexes,
                    out_shape=(band_count, out_h, out_w),
                    resampling=Resampling.bilinear,
                )
        except Exception:
            return None

        try:
            data = data.astype("float32")
            data = np.nan_to_num(data)
            min_val = data.min()
            data -= min_val
            max_val = data.max()
            if max_val > 0:
                data /= max_val
            data = (data * 255).clip(0, 255).astype("uint8")
            if band_count == 1:
                data = np.repeat(data, 3, axis=0)
            data = np.moveaxis(data, 0, -1)
            return Image.fromarray(data)
        except Exception:
            return None

    def build_image_via_pillow():
        try:
            im = Image.open(src_path)
            im = ImageOps.exif_transpose(im)
            return im
        except Exception:
            return None

    for kind, cfg in specs.items():
        target = (cfg.get("max_width", 512), cfg.get("max_height", 512))
        quality = cfg.get("quality", 82)
        method = cfg.get("method", 3)
        storage_key, abs_path = allocate_variant_path(asset_uuid, kind)

        # Rasterio-first: handles GeoTIFFs at output resolution without loading
        # the full raster into RAM. Falls back to Pillow for formats rasterio
        # cannot open (plain PNG/JPG without geo metadata).
        im = build_image_via_rasterio(target) or build_image_via_pillow()
        if im is None:
            current_app.logger.exception(
                "Failed to build %s thumbnail for asset %s", kind, asset_uuid
            )
            continue

        try:
            # Pillow keeps data lazy-loaded; ``draft`` hints reduce memory for JPEGs.
            try:
                im.draft(im.mode, target)
            except Exception:
                pass

            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGB")

            resampling_attr = getattr(Image, "Resampling", None)
            if resampling_attr is not None:
                resample_filter = resampling_attr.BILINEAR
            else:
                resample_filter = Image.BILINEAR
            im.thumbnail(target, resample=resample_filter)

            save_kwargs = {
                "format": "WEBP",
                "quality": quality,
                "method": method,
                "optimize": True,
            }

            im.save(abs_path, **save_kwargs)
            width, height = im.size
        except Exception:
            current_app.logger.exception(
                "Failed to build %s thumbnail for asset %s", kind, asset_uuid
            )
            continue

        results.append(
            ThumbnailResult(
                kind=kind, storage_key=storage_key, width=width, height=height
            )
        )

    return results


def robust_minmax(arr: np.ndarray, mask: np.ndarray | None = None, p_lo=2.0, p_hi=98.0):
    """Compute robust min/max percentiles optionally ignoring masked pixels."""
    if mask is not None:
        data = arr[~mask]
    else:
        data = arr.ravel()
    if data.size == 0:
        return 0.0, 1.0
    lo = np.percentile(data, p_lo)
    hi = np.percentile(data, p_hi)
    if hi <= lo:
        hi = lo + 1.0
    return float(lo), float(hi)


def normalize_block(band: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Normalize a single band with precomputed min/max, clipping to [0, 1]."""
    x = (band.astype("float32") - lo) / (hi - lo + 1e-8)
    return np.clip(x, 0.0, 1.0)


def read_rgb_block(src, win: Window, band_map=(1, 2, 3)):
    """Read a small RGB window from ``src`` using ``band_map`` ordering."""
    r = src.read(band_map[0], window=win)
    g = src.read(band_map[1], window=win)
    b = src.read(band_map[2], window=win)
    return r, g, b


def compute_block_minmax(src, band_map=(1, 2, 3), block=1024):
    """Scan an image in blocks to estimate robust min/max for each RGB band."""
    H, W = src.height, src.width
    r_vals, g_vals, b_vals = [], [], []
    for y in range(0, H, block):
        for x in range(0, W, block):
            win = Window(x, y, min(block, W - x), min(block, H - y))
            r, g, b = read_rgb_block(src, win, band_map)
            mask = None
            if src.nodata is not None:
                mask = (r == src.nodata) | (g == src.nodata) | (b == src.nodata)
            rl, rh = robust_minmax(r, mask)
            gl, gh = robust_minmax(g, mask)
            bl, bh = robust_minmax(b, mask)
            r_vals.append((rl, rh))
            g_vals.append((gl, gh))
            b_vals.append((bl, bh))
    r_lo = float(np.median([v[0] for v in r_vals]))
    r_hi = float(np.median([v[1] for v in r_vals]))
    g_lo = float(np.median([v[0] for v in g_vals]))
    g_hi = float(np.median([v[1] for v in g_vals]))
    b_lo = float(np.median([v[0] for v in b_vals]))
    b_hi = float(np.median([v[1] for v in b_vals]))
    return (r_lo, r_hi), (g_lo, g_hi), (b_lo, b_hi)


# --------------------- Memory / block sizing utilities --------------------- #


def get_mem_available_bytes() -> int:
    """Detect available memory from cgroup v2, cgroup v1, /proc/meminfo, or fallback.

    Returns
    -------
    int
        Estimated available bytes. Falls back to 512 MB if detection fails.
    """
    # cgroup v2
    cgroup_max = Path("/sys/fs/cgroup/memory.max")
    cgroup_cur = Path("/sys/fs/cgroup/memory.current")
    try:
        if cgroup_max.exists() and cgroup_cur.exists():
            max_raw = cgroup_max.read_text().strip()
            if max_raw != "max":
                mem_max = int(max_raw)
                mem_cur = int(cgroup_cur.read_text().strip())
                return max(0, mem_max - mem_cur)
    except Exception:
        pass

    # cgroup v1 (Docker pre-2020, some Kubernetes)
    cgroup_v1_limit = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    cgroup_v1_usage = Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    try:
        if cgroup_v1_limit.exists() and cgroup_v1_usage.exists():
            limit = int(cgroup_v1_limit.read_text().strip())
            usage = int(cgroup_v1_usage.read_text().strip())
            # 9223372036854771712 is the sentinel "no limit" value in cgroup v1
            if limit < 9_000_000_000_000_000:
                return max(0, limit - usage)
    except Exception:
        pass

    # /proc/meminfo (bare metal / macOS not available here)
    meminfo = Path("/proc/meminfo")
    try:
        if meminfo.exists():
            for line in meminfo.read_text().splitlines():
                if line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    return kb * 1024
    except Exception:
        pass

    return 512 * 1024 * 1024  # conservative fallback


def choose_block_size_auto(
    out_width: int,
    out_height: int,
    requested: Optional[int],
    mem_budget_bytes: int,
) -> int:
    """Compute an optimal square block size fitting within ``mem_budget_bytes``.

    Parameters
    ----------
    out_width, out_height
        Dimensions of the output raster in pixels.
    requested
        If provided and > 0, return it clamped to [256, 4096].
    mem_budget_bytes
        Available memory budget for block processing.

    Returns
    -------
    int
        Block side length in pixels, multiple of 64, in [256, 4096].

    Notes
    -----
    Bytes-per-pixel estimate (30):
    - band_a float32 (4) + band_b float32 (4)
    - den float32 (4) + v float32 (4) + t float32 (4)
    - gray uint16 (2) + rgba uint8×4 (4) + mask/overhead (~8)
    = 30 bytes/pixel
    Overhead factor 1.8 provides safety margin for temporaries and allocator.
    """
    if requested and requested > 0:
        return max(256, min(4096, int(requested)))

    bytes_per_pixel = 30
    overhead_factor = 1.8
    usable = int(mem_budget_bytes / overhead_factor)
    max_pixels = max(1, usable // bytes_per_pixel)
    side = int(math.sqrt(max_pixels))
    side = max(256, min(4096, side, out_width, out_height))
    side = (side // 64) * 64
    return max(256, side)


def iter_windows(width: int, height: int, block_size: int):
    """Yield rasterio ``Window`` objects covering a raster in tiles.

    Parameters
    ----------
    width, height
        Raster dimensions in pixels.
    block_size
        Tile side length in pixels.

    Yields
    ------
    rasterio.windows.Window
        Non-overlapping windows covering the full extent.
    """
    for row in range(0, height, block_size):
        for col in range(0, width, block_size):
            w = min(block_size, width - col)
            h = min(block_size, height - row)
            yield Window.from_slices((row, row + h), (col, col + w))


# Module-level LUT cache: keyed by (cmap_name, levels)
_LUT_CACHE: Dict[tuple, np.ndarray] = {}


def build_lut(cmap_name: str = "RdYlGn", levels: int = 65536) -> np.ndarray:
    """Build and cache a colormap LUT of shape (levels, 4) dtype uint8.

    Parameters
    ----------
    cmap_name
        Matplotlib colormap name (e.g. "RdYlGn", "viridis").
    levels
        Number of discrete entries. 65536 eliminates banding for float32 index values.

    Returns
    -------
    numpy.ndarray
        RGBA uint8 array of shape (levels, 4). Cached at module level.
    """
    key = (cmap_name, levels)
    if key not in _LUT_CACHE:
        import matplotlib  # noqa: PLC0415

        cmap = matplotlib.colormaps.get_cmap(cmap_name)
        x = np.linspace(0.0, 1.0, levels, dtype=np.float32)
        _LUT_CACHE[key] = cmap(x, bytes=True)  # shape (levels, 4) uint8
    return _LUT_CACHE[key]


__all__ = [
    "srgb_to_linear",
    "linear_to_srgb",
    "gray_world",
    "read_rgb",
    "read_red_nir",
    "save_quick_preview",
    "write_float32_geotiff",
    "PreprocessConfig",
    "preprocess_rgb_once",
    "true_ndvi",
    "ProcessResult",
    "process_minimal",
    "get_mem_available_bytes",
    "choose_block_size_auto",
    "iter_windows",
    "build_lut",
    "generate_nd_index_rgba",
    "compute_wb_factors_from_tif",
    "read_tif_window_as_linear_rgb",
]

# --------------------- Color transforms --------------------- #


def srgb_to_linear(x: NDArray[np.floating]) -> NDArray[np.float32]:
    """
    Convert sRGB to linear RGB (gamma removal).

    Parameters
    ----------
    x
        Array-like of sRGB values in [0, 1]. Any shape, last dimension length
        may be 3 for RGB but is not required. Values outside [0, 1] are not
        clamped here to avoid hiding data issues upstream.

    Returns
    -------
    numpy.ndarray
        Linear RGB as float32, same shape as `x`.

    Notes
    -----
    Uses the standard IEC 61966-2-1 transfer function. Thresholds and constants:
    - a = 0.055
    - thr = 0.04045

    This function operates vectorized and preserves NaN locations.

    Memory note
    -----------
    When ``x`` is already float32 the function operates **in-place** on the
    input array to avoid the peak of holding two full-size arrays in memory
    simultaneously (~2× reduction in memory spike for full-res images).
    The boolean masks ``low`` / ``~low`` partition the array disjointly, so
    modifying one subset never corrupts the values read by the other — the
    result is numerically identical to the copy-based path.
    """
    # In-place path: reuse the input buffer when dtype is already float32.
    # Non-float32 inputs still require a cast (unavoidable copy).
    a, thr = 0.055, 0.04045
    out = x if x.dtype == np.float32 else x.astype(np.float32)
    low = out <= thr
    out[low] /= 12.92
    out[~low] = ((out[~low] + a) / (1.0 + a)) ** 2.4
    return out


def linear_to_srgb(x: NDArray[np.floating]) -> NDArray[np.float32]:
    """
    Convert linear RGB to sRGB (gamma application).

    Parameters
    ----------
    x
        Array-like of linear RGB values, typically in [0, 1]. Any shape.

    Returns
    -------
    numpy.ndarray
        sRGB as float32 in [0, 1], same shape as `x`. Values are clipped to
        [0, 1] at the end.

    Notes
    -----
    Uses the inverse IEC 61966-2-1 transfer function. Thresholds and constants:
    - a = 0.055
    - thr = 0.0031308
    """
    a, thr = 0.055, 0.0031308
    y = np.empty_like(x, dtype=np.float32)
    low = x <= thr
    y[low] = 12.92 * x[low]
    y[~low] = (1 + a) * (x[~low]) ** (1 / 2.4) - a
    return np.clip(y, 0.0, 1.0).astype(np.float32)


def gray_world(img_lin: NDArray[np.floating]) -> NDArray[np.float32]:
    """
    Apply Gray-World white balance to linear RGB.

    Parameters
    ----------
    img_lin
        Linear RGB image as float array with last dimension size 3.
        Expected range [0, 1], NaN allowed (they are ignored in scaling).

    Returns
    -------
    numpy.ndarray
        White-balanced linear RGB as float32, clipped to [0, 1].

    Notes
    -----
    The Gray-World assumption scales each channel by the ratio of the mean of
    all channels to the channel mean: scale_c = mean(mean(R,G,B)) / mean(c).
    A small epsilon (1e-8) avoids division by zero.
    """
    if img_lin.shape[-1] != 3:
        raise ValueError("img_lin must have last dimension of size 3 (RGB).")
    means = img_lin.reshape(-1, 3).mean(axis=0)
    scale = means.mean() / (means + 1e-8)
    return np.clip(img_lin * scale, 0.0, 1.0).astype(np.float32)


# --------------------- IO helpers --------------------- #


def _dtype_max(dtype_str: str) -> float:
    """
    Return the maximum representable integer value for a raster dtype.

    Parameters
    ----------
    dtype_str
        Numpy/rasterio dtype string (e.g., 'uint8', 'uint16').

    Returns
    -------
    float
        Maximum representable value for integer dtypes; 1.0 for non-integer
        dtypes or if detection fails.
    """
    try:
        return float(np.iinfo(np.dtype(dtype_str)).max)  # type: ignore[arg-type]
    except Exception:
        return 1.0


def read_rgb(path: Path) -> NDArray[np.float32]:
    """
    Read an image and return sRGB float32 in [0, 1].

    Parameters
    ----------
    path
        Path to PNG/JPG/TIFF. TIFF may be 8/16-bit and can carry NoData.

    Returns
    -------
    numpy.ndarray
        Array of shape (H, W, 3) float32 in [0, 1]. Pixels matching NoData in
        any RGB band are returned as NaN triplets.

    Behavior
    --------
    1) Try rasterio:
       - Read bands 1..3 as float32.
       - Scale by dtype max if > 1 (e.g., 65535 for uint16).
       - Apply NoData as NaN.
    2) Fallback to PIL:
       - Convert to 'RGB' and scale by 255.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If a raster is opened but has fewer than 3 bands.

    Notes
    -----
    The function prefers rasterio to preserve georeferencing metadata when
    available, though it returns only pixel data.
    """
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
        # Fallback for non-GDAL formats or simple images.
        im = Image.open(path).convert("RGB")
        return (np.asarray(im, dtype=np.float32) / 255.0).astype(np.float32)


def read_red_nir(
    src: DatasetReader,
    red_band: int = 3,
    nir_band: int = 4,
) -> Tuple[NDArray[np.float32], NDArray[np.float32]]:
    """
    Read and normalize RED and NIR bands from an open rasterio dataset.

    Parameters
    ----------
    src
        Open rasterio dataset.
    red_band
        1-based index of the RED band (default 3).
    nir_band
        1-based index of the NIR band (default 4).

    Returns
    -------
    (red, nir)
        Tuple of float32 arrays in [0, 1] when integer input types are used.
        NoData values are returned as NaN.

    Raises
    ------
    ValueError
        If band indices are invalid or dataset has insufficient bands.
    """
    if src.count < max(red_band, nir_band):
        raise ValueError("Dataset does not contain the requested bands.")
    red = src.read(red_band).astype(np.float32)
    nir = src.read(nir_band).astype(np.float32)
    maxv = _dtype_max(src.dtypes[0])
    if maxv > 1.0:
        red, nir = red / maxv, nir / maxv
    if src.nodata is not None:
        m = (red == src.nodata) | (nir == src.nodata)
        red[m] = np.nan
        nir[m] = np.nan
    return red.astype(np.float32), nir.astype(np.float32)


def save_quick_preview(
    src_path: Path,
    out_path: Path,
    max_size: int = 1024,
) -> Tuple[int, int]:
    """Generate a fast RGB preview PNG from the source image.

    Uses rasterio native ``out_shape`` downsampling when the source is a
    multi-band raster to avoid loading the full-resolution image into memory.
    For large ortofotos this is the difference between a ~10 MB allocation and
    a ~2 GB one.

    Falls back to the original PIL-based path for formats rasterio cannot open
    or for single-band rasters without enough RGB bands.

    Steps
    -----
    1. Attempt rasterio path: read bands 1-3 already at target resolution via
       bilinear resampling (no full-res array ever created).
    2. On any failure, fall back to ``read_rgb`` + PIL thumbnail (original path).
    3. Normalize to [0, 1], fill NaN/nodata with 0, scale to uint8, save PNG.
    """
    try:
        with rasterio.open(src_path) as src:
            if src.count >= 3:
                src_h, src_w = src.height, src.width
                scale = max_size / max(src_h, src_w, 1)
                if scale < 1.0:
                    out_h = max(1, int(round(src_h * scale)))
                    out_w = max(1, int(round(src_w * scale)))
                else:
                    out_h, out_w = src_h, src_w
                data = src.read(
                    [1, 2, 3],
                    out_shape=(3, out_h, out_w),
                    resampling=Resampling.bilinear,
                    masked=True,
                ).astype(np.float32)
                maxv = _dtype_max(src.dtypes[0])
                if maxv > 1.0:
                    data = data / maxv
                arr = np.moveaxis(np.ma.filled(data, 0.0), 0, -1)
                arr = np.nan_to_num(arr, nan=0.0)
                arr = np.clip(arr, 0.0, 1.0)
                im = Image.fromarray((arr * 255).astype(np.uint8))
                im.save(out_path, format="PNG")
                return im.size
    except Exception:
        pass

    # Fallback: original full-res load + PIL thumbnail
    rgb = read_rgb(src_path)
    arr = np.nan_to_num(rgb, nan=0.0)
    arr = np.clip(arr, 0.0, 1.0)
    im = Image.fromarray((arr * 255).astype(np.uint8))
    w, h = im.size
    if max(w, h) > max_size:
        im.thumbnail((max_size, max_size))
    im.save(out_path, format="PNG")
    return im.size


def write_float32_geotiff(
    template: DatasetReader,
    arr: NDArray[np.floating],
    out_path: Path,
    desc: str,
) -> None:
    """
    Write a single-band float32 GeoTIFF using a template dataset profile.

    Parameters
    ----------
    template
        Open rasterio dataset to copy georeferencing/profile from.
    arr
        2D array to write. NaNs are converted to nodata sentinel (-9999.0).
    out_path
        Output file path.
    desc
        Per-band description to set on the written band.

    Notes
    -----
    - Uses DEFLATE compression, predictor=3 (floating point), tiled=True, and
      bigtiff="IF_SAFER" to mitigate file size and memory spikes.
    - This function writes count=1 with dtype=float32 and nodata=-9999.0.
    """
    profile = template.profile.copy()
    profile.update(
        count=1,
        dtype="float32",
        nodata=-9999.0,
        compress="deflate",
        predictor=3,
        tiled=True,
        bigtiff="IF_SAFER",
    )
    data = np.where(np.isfinite(arr), arr, -9999.0).astype(np.float32)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(data, 1)
        try:
            dst.set_band_description(1, desc)
        except Exception:
            # Some drivers may not support band descriptions.
            pass


# --------------------- Preprocess + cache --------------------- #


@dataclass(slots=True)
class PreprocessConfig:
    """
    Configuration for one-shot RGB preprocessing and caching.

    Attributes
    ----------
    apply_gray_world
        If True, apply gray-world white balance to linear RGB.
    apply_shadow_mask
        If True, mark very dark pixels (sum < shadow_thr) as NaN.
    shadow_thr
        Threshold on linear RGB sum [0, 3] used when `apply_shadow_mask` is True.
    cache_dir
        Directory to store artifacts (PNG preview + NPZ exact floats). If None,
        the input's parent directory is used.
    preview_max_dim
        Máxima dimensión (ancho o alto) para las previsualizaciones derivadas.
        Se aplica un muestreo por pasos simples cuando el raster supera este
        tamaño para evitar picos de memoria.
    """

    apply_gray_world: bool = True
    apply_shadow_mask: bool = True
    shadow_thr: float = 0.06
    cache_dir: Optional[Path] = None
    preview_max_dim: int = 2048


def preprocess_rgb_once(
    input_path: Path,
    cfg: PreprocessConfig,
    progress_cb: Optional[Callable[[str, float, str], None]] = None,
) -> Tuple[
    NDArray[np.float32],
    Optional[Path],
    Optional[Path],
    Optional[Path],
    Optional[Path],
]:
    """
    Preprocess RGB exactly once and cache results to disk.

    Steps
    -----
    1) Read sRGB [0, 1] and convert to linear RGB.
    2) Optional gray-world white balance.
    3) Optional shadow mask: pixels with low linear RGB sum are set to NaN.
    4) Cache artifacts:
       - NPY with exact linear float32 RGB (for scientific use).
       - PNG (sRGB 8-bit) preview for UI.

    Parameters
    ----------
    input_path
        Path to the input image (PNG/JPG/TIFF).
    cfg
        PreprocessConfig controlling the operations and cache directory.

    Returns
    -------
    (rgb_lin, png_path, npy_path, vi_gray_path, vi_heat_path, heatmap_path)
        - rgb_lin: linear RGB float32 en [0, 1] con NaNs donde aplique.
        - png_path: vista previa RGB normalizada en PNG, si se generó.
        - npy_path: cache NPY con los flotantes exactos, si se generó.
        - vi_gray_path: PNG en escala de grises con VI (G/R), si se generó.
        - vi_heat_path: PNG coloreado (tonos naranja/rojo) derivado del VI.
        - heatmap_path: PNG RGBA con heatmap pseudo-NDVI y máscara de vegetación.

    Notes
    -----
    - If the NPY cache already exists, it is used directly (fast path). The
      preview PNG is not recomputed if already present.
    - NaN pixels are mapped to black (0) in the preview PNG to avoid visible
      checkerboards, but the NPY preserves NaNs exactly.
    """
    in_key = input_path.stem
    cache_dir = cfg.cache_dir or input_path.parent
    cache_dir.mkdir(parents=True, exist_ok=True)
    npy_path = cache_dir / f"{in_key}__rgb_preproc_linear.npy"
    png_path = cache_dir / f"{in_key}__rgb_preproc_preview.png"

    def emit_progress(state: str, progress: float, message: str) -> None:
        if not progress_cb:
            return
        try:
            progress_cb(state, progress, message)
        except Exception:
            return

    def _downsample_for_preview(
        rgb_data: NDArray[np.float32], max_dim: int
    ) -> NDArray[np.float32]:
        h, w = rgb_data.shape[:2]
        if max_dim <= 0 or max(h, w) <= max_dim:
            return rgb_data
        step = int(np.ceil(max(h, w) / max_dim))
        step = max(1, step)
        ds = rgb_data[::step, ::step]
        if ds.size == 0:
            return rgb_data
        # Ensure we do not exceed max_dim due to rounding.
        h2, w2 = ds.shape[:2]
        if max(h2, w2) > max_dim:
            step2 = int(np.ceil(max(h2, w2) / max_dim))
            step2 = max(1, step2)
            ds = ds[::step2, ::step2]
            if ds.size == 0:
                return rgb_data
        return ds

    def _apply_heatmap_colormap(
        norm: NDArray[np.float32], mask: Optional[NDArray[np.bool_]]
    ) -> NDArray[np.uint8]:
        stops = np.array([0.0, 0.5, 1.0], dtype=np.float32)
        colors = np.array(
            [
                [0.647, 0.0, 0.149],  # deep red
                [1.0, 0.973, 0.533],  # yellow
                [0.0, 0.4, 0.0],  # dark green
            ],
            dtype=np.float32,
        )
        flat = np.nan_to_num(norm.ravel(), nan=0.0)
        r = np.interp(flat, stops, colors[:, 0]).reshape(norm.shape)
        g = np.interp(flat, stops, colors[:, 1]).reshape(norm.shape)
        b = np.interp(flat, stops, colors[:, 2]).reshape(norm.shape)
        rgba = np.stack(
            [
                np.clip(r * 255.0, 0, 255).astype(np.uint8),
                np.clip(g * 255.0, 0, 255).astype(np.uint8),
                np.clip(b * 255.0, 0, 255).astype(np.uint8),
                np.full(norm.shape, 255, dtype=np.uint8),
            ],
            axis=-1,
        )
        if mask is not None:
            alpha = np.where(mask, 255, 0).astype(np.uint8)
            rgba[..., 3] = alpha
        return rgba

    def ensure_rgb_preview() -> Optional[Path]:
        if png_path.exists():
            return png_path
        _png_tmp = png_path.with_suffix(".png.tmp")
        save_quick_preview(input_path, _png_tmp, max_size=cfg.preview_max_dim)
        os.replace(_png_tmp, png_path)
        return png_path

    def ensure_vi_outputs(
        rgb_data: NDArray[np.float32],
    ) -> Tuple[Optional[Path], Optional[Path]]:
        vi_gray_path = cache_dir / f"{in_key}__vi_gr_ratio.png"
        vi_heat_path = cache_dir / f"{in_key}__vi_gr_heat.png"
        if vi_gray_path.exists() and vi_heat_path.exists():
            return vi_gray_path, vi_heat_path

        vi_src = _downsample_for_preview(rgb_data, cfg.preview_max_dim)

        g = vi_src[..., 1]
        r = vi_src[..., 0]
        vi_ratio = np.divide(g, r + 1e-6)
        vi_ratio[np.isnan(vi_src).any(axis=-1)] = np.nan

        if not np.isfinite(vi_ratio).any():
            return None, None

        lo = float(np.nanpercentile(vi_ratio, 5))
        hi = float(np.nanpercentile(vi_ratio, 95))
        if not np.isfinite(lo):
            lo = float(np.nanmin(vi_ratio))
        if not np.isfinite(hi):
            hi = float(np.nanmax(vi_ratio))
        if hi <= lo:
            hi = lo + 1e-3
        vi_norm = np.clip((vi_ratio - lo) / (hi - lo), 0.0, 1.0)
        vi_norm = np.nan_to_num(vi_norm, nan=0.0)

        vi_gray = (vi_norm * 255.0).astype(np.uint8)
        Image.fromarray(vi_gray, mode="L").save(vi_gray_path)

        heat = np.zeros((*vi_norm.shape, 3), dtype=np.float32)
        heat[..., 0] = vi_norm
        heat[..., 1] = np.clip(vi_norm * 0.6, 0.0, 1.0)
        heat[..., 2] = np.clip(vi_norm * 0.2, 0.0, 1.0)
        heat_img = (heat * 255.0).astype(np.uint8)
        Image.fromarray(heat_img, mode="RGB").save(vi_heat_path)

        return vi_gray_path, vi_heat_path

    def ensure_heatmap(rgb_data: NDArray[np.float32]) -> Optional[Path]:
        heatmap_path = cache_dir / f"{in_key}__vi_heatmap.png"
        if heatmap_path.exists():
            return heatmap_path

        heat_src = _downsample_for_preview(rgb_data, cfg.preview_max_dim)
        R = heat_src[..., 0]
        G = heat_src[..., 1]
        B = heat_src[..., 2]
        EPS = 1e-6

        ngrdi = (G - R) / (G + R + EPS)
        vari = (G - R) / (G + R - B + EPS)
        gli = (2.0 * G - R - B) / (2.0 * G + R + B + EPS)
        exg = 2.0 * G - R - B
        pseudo = 0.4 * ngrdi + 0.25 * vari + 0.25 * gli + 0.10 * exg
        pseudo = np.clip(pseudo, -1.0, 1.0).astype(np.float32)

        vi = G / (R + EPS)
        mask = (exg > 0.05) & (ngrdi > 0.0) & (vi > 1.2)

        norm = (pseudo + 1.0) * 0.5
        norm = np.clip(norm, 0.0, 1.0).astype(np.float32)

        rgba = _apply_heatmap_colormap(norm, mask)
        try:
            Image.fromarray(rgba, mode="RGBA").save(heatmap_path)
        except Exception:
            return None
        return heatmap_path

    # Fast path: todos los artefactos ya existen — nada que generar.
    _vi_gray_maybe = cache_dir / f"{in_key}__vi_gr_ratio.png"
    _vi_heat_maybe = cache_dir / f"{in_key}__vi_gr_heat.png"
    _heatmap_maybe = cache_dir / f"{in_key}__vi_heatmap.png"
    if (
        png_path.exists()
        and _vi_gray_maybe.exists()
        and _vi_heat_maybe.exists()
        and _heatmap_maybe.exists()
    ):
        return (None, png_path, None, _vi_gray_maybe, _vi_heat_maybe, _heatmap_maybe)

    # 1. Preview RGB — TIF-directo, sin cargar el raster completo en RAM.
    emit_progress("preview", 0.05, "Generando vista previa RGB")
    preview_path = ensure_rgb_preview()

    # 2. Factores WB globales: se calculan por muestreo de bloques (~800 ms)
    #    y se persisten en un sidecar .wb.json de 57 bytes para reutilización.
    wb_path = cache_dir / f"{in_key}.wb.json"
    emit_progress("wb_computing", 0.08, "Calculando balance de blancos global")
    if not wb_path.exists():
        try:
            factors = compute_wb_factors_from_tif(input_path)
            wb_path.write_text(json.dumps(factors))
        except Exception:
            current_app.logger.exception(
                "media: WB computation failed for %s", input_path
            )

    # 3. Lectura del TIF a resolución de preview via WarpedVRT.
    #    Huella de memoria: out_w × out_h × 3 × 4 B ≈ 25 MB a 2 048 px.
    #    rasterio solo descomprime los tiles que intersectan la ventana.
    emit_progress("tif_reading", 0.12, "Leyendo TIF en resolución de preview")
    vi_gray_path: Optional[Path] = None
    vi_heat_path: Optional[Path] = None
    heatmap_path: Optional[Path] = None
    try:
        with rasterio.open(str(input_path)) as src:
            if src.count < 3:
                raise ValueError("imagen sin 3 bandas RGB — sin previews VI")
            raw_dtype = np.dtype(src.dtypes[0])
            dtype_max = (
                float(np.iinfo(raw_dtype).max)
                if np.issubdtype(raw_dtype, np.integer)
                else 1.0
            )
            max_dim = cfg.preview_max_dim
            longest = max(src.width, src.height)
            scale = min(1.0, max_dim / longest) if longest > 0 else 1.0
            out_w = max(1, int(round(src.width * scale)))
            out_h = max(1, int(round(src.height * scale)))

            with WarpedVRT(
                src, width=out_w, height=out_h, resampling=Resampling.bilinear
            ) as vrt:
                emit_progress(
                    "tif_reading", 0.20, f"Cargando {out_w}×{out_h} px desde TIF"
                )
                raw = vrt.read([1, 2, 3]).astype(np.float32) / dtype_max  # (3, H, W)

        # (3, H, W) → (H, W, 3), sRGB → lineal
        rgb_srgb = np.moveaxis(raw, 0, -1)
        del raw
        np.clip(rgb_srgb, 0.0, 1.0, out=rgb_srgb)
        rgb_lin = srgb_to_linear(rgb_srgb)
        del rgb_srgb

        # Aplica WB desde el sidecar; si no está disponible usa gray_world local.
        wb_factors = None
        if wb_path.exists():
            try:
                wb_factors = json.loads(wb_path.read_text())
            except Exception:
                pass
        if wb_factors:
            rgb_lin[:, :, 0] *= float(wb_factors.get("scale_r", 1.0))
            rgb_lin[:, :, 1] *= float(wb_factors.get("scale_g", 1.0))
            rgb_lin[:, :, 2] *= float(wb_factors.get("scale_b", 1.0))
            np.clip(rgb_lin, 0.0, 1.0, out=rgb_lin)
        elif cfg.apply_gray_world:
            rgb_lin = gray_world(rgb_lin)

        if cfg.apply_shadow_mask:
            dark = (
                rgb_lin[..., 0] + rgb_lin[..., 1] + rgb_lin[..., 2]
            ) < cfg.shadow_thr
            rgb_lin[dark] = np.nan

        emit_progress("vi_generating", 0.60, "Generando visualizaciones VI")
        vi_gray_path, vi_heat_path = ensure_vi_outputs(rgb_lin)

        emit_progress("heatmap_generating", 0.80, "Generando heatmap pseudo-NDVI")
        heatmap_path = ensure_heatmap(rgb_lin)

        del rgb_lin

    except Exception:
        current_app.logger.exception(
            "media: VI preview generation failed for %s", input_path
        )

    emit_progress("artifacts_done", 0.98, "Derivados listos")
    return (None, preview_path, None, vi_gray_path, vi_heat_path, heatmap_path)


def generate_nd_index_rgba(
    source_path: Path,
    cache_dir: Path,
    asset_uuid: str,
    band_a: int = 1,
    band_b: int = 2,
    cmap_name: str = "RdYlGn",
    lut_levels: int = 65536,
    mem_budget_bytes: Optional[int] = None,
    max_out_dim: int = 2048,
) -> Optional[Path]:
    """Generate a normalized-difference spectral index RGBA PNG.

    Computes ``(band_b - band_a) / (band_b + band_a)``, normalises to [0, 1],
    applies a colormap LUT, and saves a transparent RGBA PNG where NoData pixels
    have alpha = 0.

    Memory strategy
    ---------------
    The source is read **at the output resolution** using rasterio's native
    ``out_shape`` parameter (bilinear resampling).  For a 10 000 × 8 000 px
    ortofoto with ``max_out_dim=2048`` the two band arrays together occupy
    only ~32 MB instead of ~640 MB.  The final RGBA array is ~16 MB.
    The result is saved with Pillow, which streams PNG to disk without
    buffering the full raster in the GDAL PNG driver.

    Parameters
    ----------
    source_path
        Absolute path to the input raster (GeoTIFF, PNG, JPG).
    cache_dir
        Directory where the output PNG will be stored.
    asset_uuid
        UUID of the asset — used to name the output file.
    band_a
        1-based index of band A (subtracted term). Default 1.
    band_b
        1-based index of band B (added term). Default 2.
        True NDVI: band_a=3 (RED), band_b=4 (NIR).
        G/R ratio: band_a=1 (R), band_b=2 (G).
    cmap_name
        Matplotlib colormap name. Default "RdYlGn".
    lut_levels
        LUT resolution. 65 536 eliminates banding for float32 index values.
    mem_budget_bytes
        Kept for API compatibility; not used in this implementation.
    max_out_dim
        Maximum width or height of the output PNG in pixels. Default 2048.

    Returns
    -------
    Path or None
        Path to the generated PNG, or None if generation failed.

    Notes
    -----
    - Cached: if the output PNG already exists, it is returned immediately.
    - Atomic write: ``.tmp`` → ``os.replace`` (no partial files on crash).
    - Formula: ``v = (b - a) / (b + a)``; zero denominator and non-finite
      values are treated as nodata (alpha = 0).
    """
    out_path = cache_dir / f"{asset_uuid}__nd_index_rgba.png"
    if out_path.exists():
        return out_path

    cache_dir.mkdir(parents=True, exist_ok=True)
    lut = build_lut(cmap_name, lut_levels)
    # Unique tmp path prevents collision when agrovista-meta on-demand call and
    # background task run concurrently (both would write to the same .png.tmp).
    tmp_path = out_path.parent / f".{out_path.name}.{os.getpid()}.tmp"

    try:
        with rasterio.open(source_path) as src:
            n_bands = src.count

            # Auto-select bands when the requested bands exceed available count
            eff_a, eff_b = band_a, band_b
            if n_bands < max(eff_a, eff_b):
                if n_bands >= 2:
                    eff_a, eff_b = 1, 2
                elif n_bands == 1:
                    eff_a, eff_b = 1, 1
                else:
                    return None

            src_h, src_w = src.height, src.width
            src_dtype = src.dtypes[0] if n_bands > 0 else "uint8"

            # Compute output dimensions capped at max_out_dim
            scale = max_out_dim / max(src_h, src_w, 1)
            if scale < 1.0:
                out_h = max(1, int(round(src_h * scale)))
                out_w = max(1, int(round(src_w * scale)))
            else:
                out_h, out_w = src_h, src_w

            # Read both bands at output resolution — bounded memory
            # e.g. 2048×2048×2 bands×4 bytes = ~32 MB
            data = src.read(
                [eff_a, eff_b],
                out_shape=(2, out_h, out_w),
                resampling=Resampling.bilinear,
                masked=True,
            ).astype(np.float32)

        maxv = _dtype_max(src_dtype)
        if maxv > 1.0:
            data = data / maxv

        a_ma = data[0]
        b_ma = data[1]
        del data  # free the 2-band array

        base_mask = np.ma.getmaskarray(a_ma) | np.ma.getmaskarray(b_ma)
        a_f = np.ma.filled(a_ma, 0.0)
        b_f = np.ma.filled(b_ma, 0.0)
        del a_ma, b_ma

        # Normalised difference: (b - a) / (b + a)
        den = a_f + b_f
        v = np.empty_like(den, dtype=np.float32)
        np.subtract(b_f, a_f, out=v)
        np.divide(v, den, out=v, where=(den != 0.0))
        del a_f, b_f, den

        invalid = ~np.isfinite(v) | (v == 0.0)
        mask = base_mask | invalid
        del base_mask, invalid

        # Normalise [-1, 1] → [0, 1]
        t = (v + 1.0) * 0.5
        np.clip(t, 0.0, 1.0, out=t)
        t[mask] = 0.0
        del v

        # Map to LUT → RGBA uint8
        gray = np.rint(t * (lut_levels - 1)).astype(np.uint16, copy=False)
        del t
        rgba = lut[gray].copy()  # (out_h, out_w, 4) uint8
        del gray

        # Apply nodata transparency
        rgba[mask, 3] = 0
        del mask

        # Save via Pillow (streams PNG without buffering full raster in GDAL)
        try:
            Image.fromarray(rgba, mode="RGBA").save(tmp_path, format="PNG")
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise

        # Atomic rename
        os.replace(tmp_path, out_path)

    except Exception:
        try:
            current_app.logger.exception(
                "media: generate_nd_index_rgba failed for %s", asset_uuid
            )
        except Exception:
            pass
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return None

    return out_path


def true_ndvi(
    src: DatasetReader,
    red_band: int = 3,
    nir_band: int = 4,
) -> NDArray[np.float32]:
    """
    Compute true NDVI from an open rasterio dataset.

    Parameters
    ----------
    src
        Open dataset with RED and NIR bands.
    red_band
        1-based index of the RED band.
    nir_band
        1-based index of the NIR band.

    Returns
    -------
    numpy.ndarray
        NDVI float32 in [-1, 1]. NaNs propagate.

    Formula
    -------
    NDVI = (NIR - RED) / (NIR + RED)

    Notes
    -----
    Division is guarded: when (NIR + RED) == 0, the output is NaN.
    """
    red, nir = read_red_nir(src, red_band=red_band, nir_band=nir_band)
    denom = nir + red
    ndvi = np.divide(
        nir - red,
        denom,
        out=np.full_like(red, np.nan, dtype=np.float32),
        where=denom != 0,
    )
    return ndvi.astype(np.float32)


# --------------------- Minimal orchestrator --------------------- #


@dataclass(slots=True)
class ProcessResult:
    """
    Result container for `process_minimal`.

    Attributes
    ----------
    has_nir
        True if NIR band was available and true NDVI was computed.
    ndvi_map
        NDVI (if has_nir=True) or visible-only approximation (if has_nir=False).
    png_preview_path
        Path to a grayscale NDVI preview ("ndvi.png" or "ndvi_approx.png") when
        generated. For the RGB-only path, this is the approximation preview.
    rgb_cache_npy
        Path to the cached NPY containing linear RGB exact floats (RGB-only path).
    indices
        Dict of visible indices (RGB-only path). None when NIR path was used.
    """

    has_nir: bool
    ndvi_map: NDArray[np.float32]
    png_preview_path: Optional[Path]
    rgb_cache_npy: Optional[Path]
    indices: Optional[Dict[str, NDArray[np.float32]]]


def process_minimal(
    input_path: Path,
    out_dir: Path,
    red_band: int = 3,
    nir_band: int = 4,
    method: str = "combined",
    weights: Tuple[float, float, float, float] = (0.4, 0.3, 0.2, 0.1),
    cfg: Optional[PreprocessConfig] = None,
) -> ProcessResult:
    """
    Minimal processing to generate NDVI or a visible-only approximation.

    Behavior
    --------
    - If the dataset contains NIR:
        Compute true NDVI and write:
        - 'ndvi.tif' (float32 GeoTIFF, tiled/deflate) for downstream pipelines.
        - 'ndvi.png' (8-bit grayscale quicklook) for UI preview.
        Return without performing RGB preprocessing.
    - Else (RGB-only):
        1) Preprocess once (cache PNG + NPZ).
        2) Compute visible indices and combine them (`method` / `weights`).
        3) Write 'ndvi_approx.tif' and a grayscale preview 'ndvi_approx.png'.

    Parameters
    ----------
    input_path
        Path to input image (PNG/JPG/TIFF). For NDVI, TIFF with RED/NIR bands
        is required.
    out_dir
        Directory where outputs and caches are written.
    red_band
        1-based RED band index in the source.
    nir_band
        1-based NIR band index in the source.
    method
        Combination method passed to ``agrovista.helpers.combine_indices``.
    weights
        Weights used when `method="combined"`.
    cfg
        Optional `PreprocessConfig`. If None, a default is created with
        `cache_dir=out_dir`.

    Returns
    -------
    ProcessResult
        Structured result containing flags, arrays, preview paths, and indices.

    Raises
    ------
    FileNotFoundError
        If `input_path` does not exist.
    ValueError
        If a requested band index does not exist in the dataset.

    Notes
    -----
    - GeoTIFF writing uses the input dataset as a template to preserve
      georeferencing and tiling-friendly profiles.
    - PNG previews map [-1, 1] -> [0, 255] in grayscale for quick inspection.
    - Memory considerations: float32 arrays and tiled GeoTIFFs help reduce
      peak memory usage for large rasters.
    """
    if not Path(input_path).exists():
        raise FileNotFoundError(f"File not found: {input_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = cfg or PreprocessConfig(cache_dir=out_dir)

    with rasterio.open(input_path) as src:
        has_nir = src.count >= max(red_band, nir_band)
        if has_nir:
            ndvi = true_ndvi(src, red_band=red_band, nir_band=nir_band)
            write_float32_geotiff(src, ndvi, out_dir / "ndvi.tif", "NDVI")

            preview = out_dir / "ndvi.png"
            ndvi_gray = (np.clip((ndvi + 1.0) / 2.0, 0.0, 1.0) * 255.0).astype(np.uint8)
            Image.fromarray(ndvi_gray, mode="L").save(preview)

            return ProcessResult(
                has_nir=True,
                ndvi_map=ndvi.astype(np.float32),
                png_preview_path=preview,
                rgb_cache_npy=None,
                indices=None,
            )

    # RGB-only path — delega cálculo de índices a agrovista (fuente de verdad)
    rgb_lin, png_preview_path, _npy_unused, *_ = preprocess_rgb_once(input_path, cfg)
    from app.modules.agrovista.helpers import (
        VisibleConfig,
    )
    from app.modules.agrovista.helpers import combine_indices as _agrovista_combine
    from app.modules.agrovista.helpers import compute_visible_indices as _agrovista_vis

    idx = _agrovista_vis(
        rgb_lin,
        VisibleConfig(
            do_linearize=False, do_white_balance=False, shadow_mask=True, median_size=0
        ),
    )
    ndvi_approx = _agrovista_combine(idx, method=method, weights=weights)

    # Persist float32 GeoTIFF for downstream use (reuse input as template)
    with rasterio.open(input_path) as src_ref:
        write_float32_geotiff(
            src_ref, ndvi_approx, out_dir / "ndvi_approx.tif", "NDVI_approx (visible)"
        )

    # Quick grayscale preview for approximation
    preview = out_dir / "ndvi_approx.png"
    approx_gray = (np.clip((ndvi_approx + 1.0) / 2.0, 0.0, 1.0) * 255.0).astype(
        np.uint8
    )
    Image.fromarray(approx_gray, mode="L").save(preview)

    return ProcessResult(
        has_nir=False,
        ndvi_map=ndvi_approx.astype(np.float32),
        png_preview_path=png_preview_path or preview,  # keep UI RGB preview if exists
        rgb_cache_npy=None,
        indices=idx,
    )


# --------------------- TIF direct-access helpers --------------------- #


def compute_wb_factors_from_tif(
    tif_path: Path,
    block_size: int = 1024,
    sample_step: int = 4,
) -> Dict[str, float]:
    """Compute gray-world white balance scale factors by block-sampling a GeoTIFF.

    Reads every ``sample_step``-th block of ``block_size`` × ``block_size`` pixels
    from bands 1-3, accumulates per-channel means, and returns the gray-world
    correction factors (global_mean / channel_mean) as plain Python floats so the
    result is directly JSON-serializable.

    Returns {"scale_r": float, "scale_g": float, "scale_b": float}.
    Identity dict (all 1.0) is returned for images with fewer than 3 bands or
    when all sampled pixels are black/NoData.
    """
    with rasterio.open(str(tif_path)) as ds:
        if ds.count < 3:
            return {"scale_r": 1.0, "scale_g": 1.0, "scale_b": 1.0}
        h, w = ds.height, ds.width
        raw_dtype = np.dtype(ds.dtypes[0])
        dtype_max = (
            float(np.iinfo(raw_dtype).max)
            if np.issubdtype(raw_dtype, np.integer)
            else 1.0
        )

        sum_r = sum_g = sum_b = 0.0
        n = 0
        stride = block_size * sample_step
        for y in range(0, h, stride):
            for x in range(0, w, stride):
                win = Window(x, y, min(block_size, w - x), min(block_size, h - y))
                data = ds.read([1, 2, 3], window=win).astype(np.float32) / dtype_max
                valid = np.any(data > 0.0, axis=0)
                if not valid.any():
                    continue
                sum_r += float(data[0][valid].mean())
                sum_g += float(data[1][valid].mean())
                sum_b += float(data[2][valid].mean())
                n += 1

    if n == 0 or sum_r == 0.0 or sum_g == 0.0 or sum_b == 0.0:
        return {"scale_r": 1.0, "scale_g": 1.0, "scale_b": 1.0}

    mean_r = sum_r / n
    mean_g = sum_g / n
    mean_b = sum_b / n
    global_mean = (mean_r + mean_g + mean_b) / 3.0

    return {
        "scale_r": float(global_mean / mean_r),
        "scale_g": float(global_mean / mean_g),
        "scale_b": float(global_mean / mean_b),
    }


def read_tif_window_as_linear_rgb(
    tif_path: Path,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    wb_factors: Optional[Dict[str, float]] = None,
) -> NDArray[np.float32]:
    """Read a pixel BBox from a GeoTIFF as linear float32 RGB in [0, 1].

    Bands 1-3 are read into shape (y1-y0, x1-x0, 3), converted from sRGB to
    linear light, and optionally scaled by ``wb_factors`` (gray-world correction).
    NoData/out-of-range values are clipped to [0, 1] after each transform.
    """
    with rasterio.open(str(tif_path)) as ds:
        win = Window(x0, y0, x1 - x0, y1 - y0)
        raw_dtype = np.dtype(ds.dtypes[0])
        dtype_max = (
            float(np.iinfo(raw_dtype).max)
            if np.issubdtype(raw_dtype, np.integer)
            else 1.0
        )
        data = (
            ds.read([1, 2, 3], window=win).astype(np.float32) / dtype_max
        )  # (3, H, W)

    rgb = np.moveaxis(data, 0, -1)  # (H, W, 3)
    np.clip(rgb, 0.0, 1.0, out=rgb)

    rgb = srgb_to_linear(rgb)

    if wb_factors:
        rgb[:, :, 0] *= float(wb_factors.get("scale_r", 1.0))
        rgb[:, :, 1] *= float(wb_factors.get("scale_g", 1.0))
        rgb[:, :, 2] *= float(wb_factors.get("scale_b", 1.0))
        np.clip(rgb, 0.0, 1.0, out=rgb)

    return rgb
