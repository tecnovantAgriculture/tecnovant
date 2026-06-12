"""Agrovista helper utilities for NDVI analysis and reporting.

This module concentrates the heavy lifting for the Agrovista workflows:
reading multi-band imagery, computing true NDVI or visible approximations,
generating preview assets, and translating vegetation indices into agronomic
indicators such as protein or nutrient targets. The functions are intentionally
verbose so they can be reused safely from batch jobs, HTTP handlers, or
notebooks without rediscovering implementation details.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import matplotlib
import numpy as np
import rasterio
from matplotlib import cm, colors
from PIL import Image
from rasterio.errors import RasterioIOError
from rasterio.io import DatasetReader
from rasterio.transform import Affine

matplotlib.use("Agg")

try:
    from scipy.ndimage import median_filter as _median_filter
except Exception:  # optional dependency
    _median_filter = None


DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTS = {".tif", ".tiff", ".jp2", ".png", ".jpg", ".jpeg"}


def allowed_file(filename: str) -> bool:
    """Return True when the provided filename uses a supported extension.

    Args:
        filename: Raw filename string received from uploads or job configs.

    Returns:
        bool: ``True`` when the suffix is present in ``ALLOWED_EXTS``.
    """

    return Path(filename).suffix.lower() in ALLOWED_EXTS


# ----------------------------- Color & IO utils ----------------------------- #


def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    """Convert sRGB samples in the ``[0, 1]`` range into linear RGB.

    Args:
        x: Array with sRGB values normalized to ``[0, 1]``; the function is
            agnostic to shape and works channel-wise.

    Returns:
        np.ndarray: Array with the same shape as the input but encoded using a
        linear light response, which prevents color shifts during math-heavy
        vegetation index computations.
    """
    a, thr = 0.055, 0.04045
    y = np.empty_like(x, dtype=np.float32)
    low = x <= thr
    y[low] = x[low] / 12.92
    y[~low] = ((x[~low] + a) / (1.0 + a)) ** 2.4
    return y


def gray_world_white_balance(img: np.ndarray) -> np.ndarray:
    """Apply gray-world white balance on linear RGB values.

    Args:
        img: Float array in linear RGB space. Values are expected within
            ``[0, 1]``, but the math itself only assumes non-negative inputs.

    Returns:
        np.ndarray: Image scaled so the mean of each channel converges to a
        shared gray level, minimizing color casts before index derivation.
    """
    means = img.reshape(-1, 3).mean(axis=0)
    scale = means.mean() / (means + 1e-8)
    return np.clip(img * scale, 0, 1)


def robust_u8_range(
    x: np.ndarray,
    vmin: float = -1.0,
    vmax: float = 1.0,
) -> np.ndarray:
    """Scale numeric values to ``uint8`` using an explicit min/max window.

    Args:
        x: Arbitrary float array that will be normalized.
        vmin: Lower bound that maps to 0 in the resulting ``uint8`` raster.
        vmax: Upper bound that maps to 255 in the resulting ``uint8`` raster.

    Returns:
        np.ndarray: Array using 8-bit encoding suitable for quick previews or
        serialization APIs that expect integers.
    """
    x = np.clip((x - vmin) / (vmax - vmin), 0, 1)
    return (x * 255).astype(np.uint8)


def percent_u8(
    x: np.ndarray,
    p_low: float = 1.0,
    p_high: float = 99.0,
) -> np.ndarray:
    """Render arrays as ``uint8`` using percentile-based contrast stretching.

    Args:
        x: Input values that may contain ``NaN`` entries.
        p_low: Lower percentile used as the target black point.
        p_high: Upper percentile used as the target white point.

    Returns:
        np.ndarray: 8-bit array emphasizing the dynamic range between the two
        percentiles; degenerate inputs return zeros for safety.
    """
    finite = np.isfinite(x)
    if not finite.any():
        return np.zeros_like(x, dtype=np.uint8)
    lo, hi = np.percentile(x[finite], [p_low, p_high])
    if hi - lo < 1e-6:
        return np.zeros_like(x, dtype=np.uint8)
    y = np.clip((x - lo) / (hi - lo), 0, 1)
    return (y * 255).astype(np.uint8)


def _band_max(dtype_str: str) -> float:
    """Return the maximum representable value for raster bands.

    Args:
        dtype_str: String representation of the dtype reported by Rasterio.

    Returns:
        float: The numeric ceiling for integer dtypes; defaults to ``1.0`` for
        float inputs so callers can treat values as normalized already.
    """
    try:
        info = np.iinfo(np.dtype(dtype_str))
        return float(info.max)
    except Exception:
        return 1.0


def read_rgb_from_any(path: Path) -> np.ndarray:
    """Return RGB data from common raster formats as linearized float arrays.

    Args:
        path: Path to an RGB-compatible asset. The helper first tries Rasterio
            so GeoTIFF metadata is preserved when available, then falls back to
            Pillow for vanilla images.

    Returns:
        np.ndarray: Array with shape ``(H, W, 3)`` normalized to ``[0, 1]`` and
        padded with ``NaN`` where the source reports NoData.
    """
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


def read_red_nir(
    src: DatasetReader,
    red_band: int = 3,
    nir_band: int = 4,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return red and near-infrared bands ready for NDVI math.

    Args:
        src: Open Rasterio dataset.
        red_band: One-based index for the visible red band.
        nir_band: One-based index for the near-infrared band.

    Returns:
        Tuple[np.ndarray, np.ndarray]: Pair of ``float32`` arrays normalized to
        ``[0, 1]`` with NoData propagated as ``NaN`` so downstream math can use
        vectorized ``np.isfinite`` checks.
    """
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
    """Generate a fast RGB preview PNG from the source image.

    Args:
        src_path: Location of the source raster image on disk.
        out_path: Path where the preview PNG will be persisted.
        max_size: Maximum width or height in pixels, preserving aspect ratio.

    Returns:
        Tuple[int, int]: Final preview size expressed as ``(width, height)``.
    """
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


# ------------------------ Visible indices & combination ---------------------- #


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
    """Compute VARI, NGRDI, GLI, and ExG indices from RGB imagery.

    Args:
        rgb: Float array with three channels in the ``[0, 1]`` interval. ``NaN``
            values are supported and masked throughout the computation.
        cfg: ``VisibleConfig`` that enables optional linearization, white
            balance, and median filtering.

    Returns:
        Dict[str, np.ndarray]: Mapping that includes the vegetation indices plus
        helper masks (``shadow_mask`` and ``preproc_nan``) to simplify later
        visualization steps.
    """
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
        nbi = -ngrdi

    dark = np.zeros_like(ngrdi, dtype=bool)
    if cfg.shadow_mask:
        dark = (R + G + B) < cfg.shadow_thr
        for arr_idx in (vari, ngrdi, gli, exg, nbi):
            arr_idx[dark] = np.nan

    out = {
        "VARI": np.clip(vari, -1, 1),
        "NGRDI": np.clip(ngrdi, -1, 1),
        "GLI": np.clip(gli, -1, 1),
        "ExG": np.clip(exg, -1, 1),
        "NBI": np.clip(nbi, -1, 1),
        "shadow_mask": dark,
        "preproc_nan": nan_mask,
    }

    if cfg.median_size and cfg.median_size > 1 and _median_filter is not None:
        for k in ("VARI", "NGRDI", "GLI", "ExG", "NBI"):
            x = out[k]
            valid = np.isfinite(x)
            x_f = x.copy()
            x_f[~valid] = 0
            x_f = _median_filter(x_f, size=cfg.median_size)
            x_f[~valid] = np.nan
            out[k] = x_f

    for k in ("VARI", "NGRDI", "GLI", "ExG", "NBI"):
        x = out[k]
        x[nan_mask] = np.nan
        out[k] = x

    return out


def combine_indices(
    indices: Dict[str, np.ndarray],
    method: str = "combined",
    weights: Tuple[float, float, float, float] = (0.4, 0.3, 0.2, 0.1),
) -> np.ndarray:
    """Return a pseudo-NDVI map synthesized from visible-band indices.

    Args:
        indices: Output of :func:`compute_visible_indices`.
        method: Name of the single index to favor or ``"combined"`` to run a
            weighted fusion.
        weights: Weight tuple applied when ``method == "combined"``.

    Returns:
        np.ndarray: Array constrained to ``[-1, 1]`` matching NDVI semantics.
    """
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


# --------------------------- True NDVI (with NIR) ---------------------------- #


def compute_true_ndvi(
    src: DatasetReader,
    red_band: int = 3,
    nir_band: int = 4,
) -> np.ndarray:
    """Compute NDVI directly from red and near-infrared bands.

    Args:
        src: Rasterio dataset already opened in read mode.
        red_band: Red band index; defaults to 3 for Sentinel-style products.
        nir_band: NIR band index; defaults to 4.

    Returns:
        np.ndarray: ``float32`` NDVI values in the canonical ``[-1, 1]`` range.
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


# ---------------------------- Pipeline interface ---------------------------- #


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
    """Compute NDVI using NIR bands when available or a visible approximation.

    Args:
        src_path: Raster path accepted by Rasterio and/or Pillow.
        red_band: 1-based red band index for true NDVI computation.
        nir_band: 1-based NIR band index for true NDVI computation.
        method: Combination strategy to use when the file lacks NIR channels.
        weights: Fusion weights applied when ``method == "combined"``.
        visible_cfg: Optional overrides for visible preprocessing toggles.

    Returns:
        PipelineResult: Rich payload with the computed raster, raw indices, and
        descriptive metadata useful for logging or downstream storage.
    """
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

                meta.update(
                    {
                        "has_nir": True,
                        "method": "ndvi",
                        "visible_method": None,
                    }
                )
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
        # Handle files unsupported by rasterio (e.g. plain PNG/JPG)
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


# ----------------------------- PNG utilities -------------------------------- #


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
    """Save a float map as PNG (RGBA) with the given colormap.

    Args:
        arr: Any float array; ``NaN`` pixels are treated as transparent.
        out_path: Destination where the PNG will be written.
        cmap_name: Matplotlib colormap name.
        vmin: Minimum value used for normalization.
        vmax: Maximum value used for normalization.
        percentile_stretch: Optional ``(low, high)`` percentiles that override
            ``vmin``/``vmax`` using the data distribution.
        transparent_nodata: When ``True`` set alpha to 0 for invalid pixels.
    """
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
    """Backward-compatible shorthand that delegates to ``save_png_float``.

    Args:
        ndvi: NDVI raster ready for visualization.
        out_path: Destination path for the PNG artifact.
    """
    save_png_float(ndvi, out_path, cmap_name="RdYlGn", vmin=-1, vmax=1)


# --------------------------- Protein estimation ----------------------------- #

DEFAULT_PROTEIN_TABLE: List[Tuple[float, float]] = [
    (0.10, 6.0),
    (0.40, 12.0),
    (0.70, 18.0),
]


def ndvi_to_protein(
    value: float,
    table: Sequence[Tuple[float, float]] | None = None,
) -> float:
    """Interpolate a single NDVI value into a protein estimate.

    Args:
        value: NDVI number expected within the domain of ``table``.
        table: Optional calibration table ordered as ``(ndvi, protein)`` pairs.

    Returns:
        float: Estimated protein percentage or ``NaN`` when the value is out of
        bounds.
    """
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
    """Vectorized variant of :func:`ndvi_to_protein` for entire rasters.

    Args:
        values: NDVI array, typically the output of :func:`compute_true_ndvi`.
        table: Optional calibration table identical to the scalar helper.

    Returns:
        np.ndarray: Protein estimates where valid and ``NaN`` elsewhere.
    """
    table = table or DEFAULT_PROTEIN_TABLE
    xs = np.array([x for x, _ in table], dtype=np.float32)
    ys = np.array([y for _, y in table], dtype=np.float32)
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    out = np.interp(values, xs, ys)
    out[(values < xs[0]) | (values > xs[-1]) | ~np.isfinite(values)] = np.nan
    return out.astype(np.float32)


def protein_to_nitrogen(value: float, factor: float = 6.25) -> float:
    """Convert protein percentage into nitrogen percentage.

    Args:
        value: Protein concentration expressed in percent.
        factor: Conversion factor; defaults to the Kjeldahl coefficient.

    Returns:
        float: Nitrogen percentage or ``NaN`` when the inputs are invalid.
    """
    if factor <= 0:
        return float("nan")
    if not np.isfinite(value):
        return float("nan")
    return float(value / factor)


def protein_to_nitrogen_vec(values: np.ndarray, factor: float = 6.25) -> np.ndarray:
    """Vectorized version of :func:`protein_to_nitrogen` for rasters.

    Args:
        values: Protein raster produced by :func:`ndvi_to_protein_vec`.
        factor: Conversion coefficient applied element-wise.

    Returns:
        np.ndarray: Nitrogen percentages with ``NaN`` for invalid pixels.
    """
    out = np.full_like(values, np.nan, dtype=np.float32)
    if factor <= 0:
        return out
    mask = np.isfinite(values)
    out[mask] = (values[mask] / factor).astype(np.float32)
    return out


# ------------------------------ Polygon masking ----------------------------- #


def _mask_from_bbox(shape, vertices):
    """Return ``(mask, row_offset, col_offset)`` limited to the polygon bounding box.

    The mask is a ``uint8`` array shaped exactly to the bounding-box extent.
    Callers must apply ``row_offset`` / ``col_offset`` when indexing back
    into the full-resolution raster.
    """
    pts = np.asarray(vertices)
    if pts.ndim != 2 or pts.shape[1] != 2 or len(pts) < 3:
        raise ValueError("vertices must be an iterable of (col, row) pairs")

    min_col = max(0, int(np.floor(pts[:, 0].min())))
    max_col = min(shape[1], int(np.ceil(pts[:, 0].max())))
    min_row = max(0, int(np.floor(pts[:, 1].min())))
    max_row = min(shape[0], int(np.ceil(pts[:, 1].max())))

    if max_col <= min_col or max_row <= min_row:
        return np.zeros((0, 0), dtype=np.uint8), min_row, min_col

    sub_h = max_row - min_row
    sub_w = max_col - min_col

    mask = np.zeros((sub_h, sub_w), dtype=np.uint8)

    # Shift vertices to sub-array origin
    shifted = pts.copy()
    shifted[:, 0] -= min_col
    shifted[:, 1] -= min_row

    # cv2 expects (x, y) = (col, row) with shape (N, 1, 2)
    cv_pts = shifted.astype(np.int32).reshape((-1, 1, 2))
    import cv2

    cv2.fillPoly(mask, [cv_pts], 1)
    return mask, min_row, min_col


def polygon_mask(
    shape: Tuple[int, int],
    vertices: Iterable[Tuple[float, float]],
    transform: Optional[Affine] = None,
) -> np.ndarray:
    """Return a boolean mask describing the pixels contained in a polygon.

    Uses ``cv2.fillPoly`` with bounding-box clipping for performance.
    Falls back to a full-image rasterization when a coordinate transform
    is supplied (the transform may map vertices outside the original extent).

    Args:
        shape: Output mask shape expressed as ``(rows, cols)``.
        vertices: Polygon coordinates in pixel space as ``(col, row)`` pairs.
        transform: Optional affine transform from pixel to map coordinates.

    Returns:
        np.ndarray: Boolean mask with ``True`` inside the polygon.
    """
    verts = np.asarray(list(vertices), dtype=np.float64)

    # When a transform is present, vertices may end up outside the image
    # extent, so the bbox optimisation would be unsafe.  Fall back to
    # the original matplotlib-based approach for correctness.
    if transform is not None:
        inv = ~transform
        pts = np.array([inv * (x, y) for x, y in verts], dtype=np.float64)
        from matplotlib.path import Path as MplPath

        y_idx, x_idx = np.meshgrid(
            np.arange(shape[0]), np.arange(shape[1]), indexing="ij"
        )
        coords = np.column_stack((x_idx.ravel() + 0.5, y_idx.ravel() + 0.5))
        return MplPath(pts).contains_points(coords).reshape(shape)

    # Fast path: cv2 with bounding-box crop
    sub_mask, row_off, col_off = _mask_from_bbox(shape, verts)
    if sub_mask.size == 0:
        return np.zeros(shape, dtype=bool)

    full_mask = np.zeros(shape, dtype=bool)
    h, w = sub_mask.shape
    full_mask[row_off : row_off + h, col_off : col_off + w] = sub_mask.astype(bool)
    return full_mask


def average_protein(
    ndvi_map: np.ndarray,
    mask: np.ndarray,
    table: Sequence[Tuple[float, float]] | None = None,
    min_count: int = 20,
    reducer: str = "mean",
) -> float:
    """Summarize protein estimates inside a polygon mask.

    Args:
        ndvi_map: NDVI raster.
        mask: Boolean mask selecting the region of interest.
        table: Optional calibration table to override the default.
        min_count: Required valid-pixel count before returning a statistic.
        reducer: ``"mean"`` or ``"median"`` aggregation strategy.

    Returns:
        float: Aggregated protein value or ``NaN`` when the mask is too small.
    """
    valid = mask & np.isfinite(ndvi_map)
    vals = ndvi_map[valid]
    if vals.size < min_count:
        return float("nan")
    prot = ndvi_to_protein_vec(vals, table=table)
    prot = prot[np.isfinite(prot)]
    if prot.size == 0:
        return float("nan")
    return float(np.median(prot) if reducer == "median" else np.mean(prot))


# ---------------------- Secondary objective estimations --------------------- #


def _coerce_non_negative(value: float | int | None) -> float:
    """Cast inputs to ``float`` while ensuring non-negative results."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(v):
        return 0.0
    return max(v, 0.0)


def _mineral_rule(
    pendiente: float, intercepto: float
) -> Callable[[float, float], float]:
    """Genera una rule de nutriente basada en la regresión real proteína → mineral.

    Las regresiones están calibradas con datos de pastos colombianos.
    El contrato es el mismo que el anterior: rule(protein, nitrogen) -> float.
    Solo se usa protein; nitrogen se ignora (la regresión real no lo necesita).

    # coeficientes derivados de modelo propietario de análisis espectral de pastos
    """

    def _rule(protein: float, nitrogen: float) -> float:
        prot = _coerce_non_negative(protein)
        return pendiente * prot + intercepto

    return _rule


def _constant_rule(valor: float) -> Callable[[float, float], float]:
    """Rule para minerales sin calibración espectral local.

    Retorna un valor constante de referencia bibliográfica internacional.
    No varía con la proteína — usar solo como orden de magnitud.
    El valor debe ir acompañado de su cita en el punto de uso.
    """

    def _rule(protein: float, nitrogen: float) -> float:  # noqa: ARG001
        return valor

    return _rule


# Regla de fallback para nutrientes sin regresión calibrada de alta calidad
DEFAULT_SECONDARY_RULE = _mineral_rule(0.0, 0.0)


# Reglas de contenido mineral calibradas con datos reales de pastos colombianos.
# Cada rule(protein, nitrogen) retorna el contenido estimado del mineral en el cultivo.
# Alta confiabilidad (R² > 0.96): N, K, P, Cu, B, S.
# Aproximados (R² < 0.90): Mg, Ca, Fe, Zn, Mn — usar con precaución.
# # coeficientes derivados de modelo propietario de análisis espectral de pastos
NUTRIENT_SPECTRAL_RULES: Dict[str, Callable[[float, float], float]] = {
    # Macronutrientes
    "n": _mineral_rule(1 / 6.25, 0.0),  # N% = Prot/6.25 (exacto)
    "nitrogeno": _mineral_rule(1 / 6.25, 0.0),
    "k": _mineral_rule(0.264356, -0.825480),  # R²=0.978
    "potasio": _mineral_rule(0.264356, -0.825480),
    "p": _mineral_rule(0.016552, 0.085562),  # R²=0.983
    "fosforo": _mineral_rule(0.016552, 0.085562),
    "s": _mineral_rule(0.018605, -0.042103),  # R²=0.960
    "azufre": _mineral_rule(0.018605, -0.042103),
    # Micronutrientes con calibración alta (R² > 0.96)
    "cu": _mineral_rule(0.258814, 1.365927),  # Cu ppm, R²=0.973
    "cobre": _mineral_rule(0.258814, 1.365927),
    "b": _mineral_rule(-0.071392, 3.856644),  # B ppm, R²=0.992
    "boro": _mineral_rule(-0.071392, 3.856644),
    # Minerales con correlación aproximada (R² < 0.90)
    "ca": _mineral_rule(-0.008070, 0.471893),  # R²=0.863
    "calcio": _mineral_rule(-0.008070, 0.471893),
    "mg": _mineral_rule(-0.004588, 0.251493),  # R²=0.384
    "magnesio": _mineral_rule(-0.004588, 0.251493),
    "fe": _mineral_rule(5.639372, 48.586601),  # Fe ppm, R²=0.532
    "hierro": _mineral_rule(5.639372, 48.586601),
    "zn": _mineral_rule(-0.013478, 28.964293),  # Zn ppm, R²=0.002
    "zinc": _mineral_rule(-0.013478, 28.964293),
    "mn": _mineral_rule(-7.061378, 179.018960),  # Mn ppm, R²=0.689
    "manganeso": _mineral_rule(-7.061378, 179.018960),
    # ── Minerales sin calibración espectral local ──────────────────────────────
    #
    # Mo — Molibdeno
    #   Valor: 0.50 mg/kg MS  (punto medio del rango de suficiencia 0.2–2.0 mg/kg MS)
    #   Fuente: Gupta & Gupta (1998) en Molybdenum deficiency (plant disorder)
    #   URL: https://en.wikipedia.org/wiki/Molybdenum_deficiency_(plant_disorder)
    #   Nota: sin calibración local. Usar solo como orden de magnitud.
    "mo": _constant_rule(0.50),
    "molibdeno": _constant_rule(0.50),
    #
    # Si — Silicio
    #   Valor: 1.50 %MS  (promedio ~1.5% en gramíneas, Hodson et al.)
    #   Fuente primaria: Hodson et al. (2005) — Silicon, the neglected nutrient
    #   URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC4174135/
    #   Fuente secundaria: Melo et al. (2003) — Brachiaria decumbens y B. brizantha,
    #   acumuladoras de Si en suelos del Cerrado (análogos a Llanos Orientales).
    #   URL: https://www.researchgate.net/publication/26365730
    #   Nota: extrapolado desde Brachiaria/Cerrado; sin calibración local.
    "si": _constant_rule(1.50),
    "silicio": _constant_rule(1.50),
    #
    # Cl — Cloro
    #   Sin referencia bibliográfica verificable para gramíneas colombianas.
    #   No se incluye en paneles estándar de análisis foliar de pastos en Colombia.
    #   Se mantiene en cero — filtrar en el template para que no aparezca en el reporte.
}

# Alias de compatibilidad — eliminar en una próxima limpieza
NUTRIENT_DUMMY_RULES = NUTRIENT_SPECTRAL_RULES


# Mapeo símbolo/nombre → clave de tabla bromatológica (fuente de verdad).
# La tabla interpolada es más precisa que las regresiones para los 11 minerales
# medidos en campo; las reglas espectrales solo aplican a Mo y Si (no en tabla).
_TABLE_MINERAL_KEY: Dict[str, str] = {
    "n": "N",
    "nitrogeno": "N",
    "nitrógeno": "N",
    "k": "K",
    "potasio": "K",
    "p": "P",
    "fosforo": "P",
    "fósforo": "P",
    "mg": "Mg",
    "magnesio": "Mg",
    "ca": "Ca",
    "calcio": "Ca",
    "s": "S",
    "azufre": "S",
    "cu": "Cu",
    "cobre": "Cu",
    "fe": "Fe",
    "hierro": "Fe",
    "zn": "Zn",
    "zinc": "Zn",
    "mn": "Mn",
    "manganeso": "Mn",
    "b": "B",
    "boro": "B",
}


def compute_secondary_objective_targets(
    protein_average: float,
    nitrogen_estimated: float,
    nutrients: Sequence[object],
    *,
    digits: int | None = 3,
) -> List[Dict[str, object]]:
    """Return nutrient content estimates for a given protein/nitrogen pair.

    Values are derived from calibrated regressions on Colombian tropical grasses.
    High-reliability minerals (R² > 0.96): N, K, P, Cu, B, S.
    Approximate minerals (R² < 0.90): Mg, Ca, Fe, Zn, Mn.

    Args:
        protein_average: Average protein percentage for the zone.
        nitrogen_estimated: Estimated nitrogen percentage (used as fallback
            for nutrients without a direct regression).
        nutrients: Iterable of ORM-like objects with ``symbol``, ``name``,
            ``unit``, and ``id`` attributes.
        digits: Decimal precision applied to the generated values.

    Returns:
        List[Dict[str, object]]: Payload ready for serialization in API
        responses.
    """

    from .bromatologia import _interpolar_mineral

    def _resolve_table_key(symbol: str | None, name: str | None) -> str | None:
        for key in filter(None, [symbol, name]):
            table_key = _TABLE_MINERAL_KEY.get(key.lower())
            if table_key is not None:
                return table_key
        return None

    def _resolve_rule(
        symbol: str | None, name: str | None
    ) -> Callable[[float, float], float]:
        for key in filter(None, [symbol, name]):
            key_l = key.lower()
            if key_l in NUTRIENT_SPECTRAL_RULES:
                return NUTRIENT_SPECTRAL_RULES[key_l]
        return DEFAULT_SECONDARY_RULE

    out: List[Dict[str, object]] = []
    for nutrient in nutrients:
        symbol = getattr(nutrient, "symbol", None)
        name = getattr(nutrient, "name", None)
        unit = getattr(nutrient, "unit", None)
        nutrient_id = getattr(nutrient, "id", None)
        table_key = _resolve_table_key(symbol, name)
        if table_key is not None:
            value = _interpolar_mineral(protein_average, table_key)
        else:
            func = _resolve_rule(symbol, name)
            value = func(protein_average, nitrogen_estimated)
        if digits is not None and math.isfinite(value):
            value = round(value, digits)
        out.append(
            {
                "nutrient_id": nutrient_id,
                "nutrient_name": name,
                "nutrient_symbol": symbol,
                "nutrient_unit": unit,
                "target_value": value,
            }
        )
    return out


def secondary_target_map(
    protein_average: float,
    nitrogen_estimated: float,
    nutrients: Sequence[object],
    *,
    digits: int | None = 3,
) -> Dict[int, float]:
    """Return a mapping from nutrient identifiers to target values.

    Args:
        protein_average: Average protein percentage.
        nitrogen_estimated: Estimated nitrogen percentage.
        nutrients: Same sequence used by
            :func:`compute_secondary_objective_targets`.
        digits: Decimal precision for the output map.

    Returns:
        Dict[int, float]: Compact lookup keyed by ``nutrient_id``.
    """

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


# Concentración (grado) de los productos de la línea nano, por símbolo.
# Port del btn_Nano_formula del FRM_Balance (Foliar Digital.xlsm).
NANO_PRODUCT_GRADES: Dict[str, float] = {"N": 16.0, "P": 11.0, "K": 19.0}
DEFAULT_NANO_GRADE = 40.0


def compute_mineral_balance(
    order: Sequence[str],
    targets: Dict[str, object],
    actuals: Dict[str, object],
    aforo: object,
    nutrients: Sequence[object],
    *,
    aforo_actual: object = None,
    digits: int | None = 2,
) -> Dict[str, object]:
    """Compute the mineral balance table (port of FRM_Balance in Excel).

    Macros convert as ``% × aforo × 100`` and micros as ``ppm × aforo ÷ 100``
    to express both sides in kg/ha. The objective row converts with the
    objective aforo and the actual row with the actual aforo (falling back
    to the objective one so legacy reports without an actual aforo keep
    rendering). The difference keeps only deficits (surpluses clamp to 0).
    The formula grade is each deficit share of the total requirement, and
    the nano dosage divides each deficit by the nano product concentration
    (N 16, P 11, K 19, others 40).

    Args:
        order: Nutrient display order (names as the frontend knows them).
        targets: Reference values keyed by nutrient name (% or ppm).
        actuals: Leaf analysis values keyed by nutrient name (% or ppm).
        aforo: Forage yield of the objective side; converts the objective
            row and acts as fallback for the actual row.
        nutrients: ORM ``Nutrient`` rows to classify macro/micro and map
            names to symbols.
        aforo_actual: Forage yield of the lot/analysis side; converts the
            actual row. ``None`` or invalid falls back to ``aforo``.
        digits: Rounding applied to every numeric output.

    Returns:
        Dict[str, object]: ``{"entries": [...], "total_kg_ha": float|None,
        "aforo_actual_fallback": bool}`` where each entry carries
        objective/actual raw and kg values, the deficit, grade percentage
        and nano dosage for one nutrient. ``aforo_actual_fallback`` is True
        when the actual row was converted with the objective aforo because
        no valid actual aforo was provided.
    """

    from app.modules.foliage.models import NutrientCategory

    def _to_float(value: object) -> Optional[float]:
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    info: Dict[str, Tuple[bool, Optional[str]]] = {}
    for nutrient in nutrients:
        is_macro = getattr(nutrient, "category", None) == NutrientCategory.MACRONUTRIENT
        symbol = getattr(nutrient, "symbol", None)
        for key in filter(None, [getattr(nutrient, "name", None), symbol]):
            info[key] = (is_macro, symbol)

    aforo_val = _to_float(aforo)
    if aforo_val is not None and aforo_val <= 0:
        aforo_val = None
    aforo_act_val = _to_float(aforo_actual)
    if aforo_act_val is None or aforo_act_val <= 0:
        aforo_act_val = aforo_val
        aforo_actual_fallback = aforo_val is not None
    else:
        aforo_actual_fallback = False

    def _round(value: Optional[float]) -> Optional[float]:
        if value is None or digits is None:
            return value
        return round(value, digits)

    entries: List[Dict[str, object]] = []
    for name in order:
        targ = _to_float(targets.get(name))
        act = _to_float(actuals.get(name))
        is_macro, symbol = info.get(name, (False, None))
        entry: Dict[str, object] = {
            "name": name,
            "objective_raw": targ,
            "actual_raw": act,
            "objective_kg": None,
            "actual_kg": None,
            "difference_kg": None,
            "grade_pct": None,
            "nano_kg": None,
            "_symbol": symbol,
        }
        if targ is not None and act is not None and aforo_val is not None:
            obj_factor = aforo_val * 100 if is_macro else aforo_val / 100
            act_factor = aforo_act_val * 100 if is_macro else aforo_act_val / 100
            obj_kg = targ * obj_factor
            act_kg = act * act_factor
            entry["objective_kg"] = obj_kg
            entry["actual_kg"] = act_kg
            entry["difference_kg"] = min(act_kg - obj_kg, 0.0)
        entries.append(entry)

    total = sum(
        abs(entry["difference_kg"])  # type: ignore[arg-type]
        for entry in entries
        if entry["difference_kg"] is not None
    )

    for entry in entries:
        deficit = entry["difference_kg"]
        if deficit is not None:
            magnitude = abs(deficit)  # type: ignore[arg-type]
            if total > 0:
                entry["grade_pct"] = magnitude / total * 100
            grade = NANO_PRODUCT_GRADES.get(entry["_symbol"] or "", DEFAULT_NANO_GRADE)
            entry["nano_kg"] = magnitude / grade
        del entry["_symbol"]
        for key in (
            "objective_raw",
            "actual_raw",
            "objective_kg",
            "actual_kg",
            "difference_kg",
            "grade_pct",
            "nano_kg",
        ):
            entry[key] = _round(entry[key])  # type: ignore[arg-type]

    return {
        "entries": entries,
        "total_kg_ha": _round(total) if total > 0 else None,
        "aforo_actual_fallback": aforo_actual_fallback,
    }
