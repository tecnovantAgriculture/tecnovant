from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Literal, Optional, Tuple, cast

import numpy as np
import rasterio
from flask import current_app
from PIL import Image
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.warp import transform_bounds

from app.modules.media.helpers import _media_root

ModeLiteral = Literal["rgb", "auto", "pseudo_ndvi"]


@dataclass(frozen=True)
class DisplayMetadata:
    image_id: str
    width: int
    height: int
    bounds: Tuple[float, float, float, float]
    crs: str
    transform: Dict[str, float]
    nodata: float | None
    display_png_size: Dict[str, int]
    mode: str
    storage_key: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "image_id": self.image_id,
            "width": self.width,
            "height": self.height,
            "bounds": list(self.bounds),
            "crs": self.crs,
            "transform": self.transform,
            "nodata": self.nodata,
            "display_png_size": self.display_png_size,
            "mode": self.mode,
            "display_png_key": self.storage_key,
        }


class GeoDisplayError(Exception):
    """Errores propios del generador de assets."""


def _resolve_display_dir(image_id: str) -> Path:
    base = Path(_media_root())
    safe_id = image_id.strip()
    if not safe_id or safe_id != image_id:
        raise GeoDisplayError("Invalid image identifier.")
    display_dir = base / "display" / safe_id
    display_dir.mkdir(parents=True, exist_ok=True)
    return display_dir


def _dataset_bounds_wgs84(
    src: rasterio.io.DatasetReader,
) -> Tuple[float, float, float, float]:
    if src.crs is None:
        raise GeoDisplayError("Dataset is missing CRS information.")
    try:
        w, s, e, n = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
    except Exception as exc:
        raise GeoDisplayError("Unable to transform bounds to WGS84.") from exc
    south = float(min(max(s, -90.0), 90.0))
    north = float(min(max(n, -90.0), 90.0))
    west = float(((w + 180.0) % 360.0) - 180.0)
    east = float(((e + 180.0) % 360.0) - 180.0)
    return (south, west, north, east)


def _transform_to_dict(t: Affine) -> Dict[str, float]:
    return {
        "a": float(t.a),
        "b": float(t.b),
        "c": float(t.c),
        "d": float(t.d),
        "e": float(t.e),
        "f": float(t.f),
    }


def _choose_mode(src: rasterio.io.DatasetReader, mode: ModeLiteral) -> ModeLiteral:
    has_rgb = src.count >= 3
    if mode == "auto":
        return "rgb" if has_rgb else "pseudo_ndvi"
    if mode == "rgb" and not has_rgb:
        raise GeoDisplayError("RGB mode requested but dataset lacks RGB bands.")
    return mode


def _compute_out_shape(width: int, height: int, max_dim: int) -> Tuple[int, int]:
    if max_dim <= 0 or max(width, height) <= max_dim:
        return height, width
    scale = max(width, height) / max_dim
    out_w = max(1, int(round(width / scale)))
    out_h = max(1, int(round(height / scale)))
    return out_h, out_w


def _read_downsampled(
    src: rasterio.io.DatasetReader, indexes: Tuple[int, ...], out_shape: Tuple[int, int]
) -> np.ndarray:
    bands = len(indexes)
    arr = src.read(
        indexes=indexes,
        out_shape=(bands, out_shape[0], out_shape[1]),
        resampling=Resampling.bilinear,
        masked=True,
    ).astype(np.float32)
    data = np.array(arr.filled(np.nan), dtype=np.float32)
    if src.nodata is not None:
        nod = float(src.nodata)
        mask = np.any(data == nod, axis=0)
        data[:, mask] = np.nan
    return data


def _dataset_valid_mask(
    src: rasterio.io.DatasetReader, out_shape: Tuple[int, int]
) -> np.ndarray:
    mask = src.dataset_mask(
        out_shape=out_shape,
        resampling=Resampling.nearest,
    )
    return mask > 0


def _robust_uint8(arr: np.ndarray) -> np.ndarray:
    finite = np.isfinite(arr)
    if not finite.any():
        return np.zeros(arr.shape, dtype=np.uint8)
    values = arr[finite]
    p2, p98 = np.percentile(values, [2, 98])
    if not np.isfinite(p2) or not np.isfinite(p98) or p98 <= p2:
        p2, p98 = float(values.min()), float(values.max())
        if not np.isfinite(p2) or not np.isfinite(p98) or p98 <= p2:
            return np.zeros(arr.shape, dtype=np.uint8)
    scaled = (arr - p2) / (p98 - p2 + 1e-6)
    scaled = np.clip(scaled, 0.0, 1.0)
    out = (scaled * 255.0 + 0.5).astype(np.uint8)
    out[~finite] = 0
    return out


def _pseudo_ndvi_rgb(data: np.ndarray, valid_mask: Optional[np.ndarray]) -> np.ndarray:
    eps = 1e-6
    R = data[0]
    G = data[1]
    B = data[2]
    ngrdi = (G - R) / (G + R + eps)
    vari = (G - R) / (G + R - B + eps)
    gli = (2.0 * G - R - B) / (2.0 * G + R + B + eps)
    exg = 2.0 * G - R - B
    pseudo = 0.4 * ngrdi + 0.25 * vari + 0.25 * gli + 0.10 * exg
    pseudo = np.clip(pseudo, -1.0, 1.0)
    vi = G / (R + eps)
    veg_mask = (exg > 0.05) & (ngrdi > 0.0) & (vi > 1.2)
    norm = np.clip((pseudo + 1.0) * 0.5, 0.0, 1.0).astype(np.float32)
    rgb = np.empty((*norm.shape, 3), dtype=np.uint8)
    # simple colormap red-yellow-green
    flat = norm.ravel()
    r = np.interp(flat, [0.0, 0.5, 1.0], [165, 255, 0]).reshape(norm.shape)
    g = np.interp(flat, [0.0, 0.5, 1.0], [0, 247, 102]).reshape(norm.shape)
    b = np.interp(flat, [0.0, 0.5, 1.0], [38, 0, 0]).reshape(norm.shape)
    rgb[..., 0] = r.astype(np.uint8)
    rgb[..., 1] = g.astype(np.uint8)
    rgb[..., 2] = b.astype(np.uint8)
    display_mask = veg_mask
    if valid_mask is not None:
        display_mask = valid_mask & veg_mask
    rgb[~display_mask] = 255
    logger = current_app.logger
    finite = np.isfinite(pseudo)
    pseudo_min = float(np.nanmin(pseudo)) if finite.any() else float("nan")
    pseudo_max = float(np.nanmax(pseudo)) if finite.any() else float("nan")
    logger.info(
        "agrovista: display stats pseudo_ndvi[min=%.4f,max=%.4f]",
        pseudo_min,
        pseudo_max,
    )
    logger.info(
        "agrovista: display pseudo_ndvi dtype=%s shape=%s", rgb.dtype, rgb.shape
    )
    return rgb


def _rgb_visualisation(data: np.ndarray, mask: Optional[np.ndarray]) -> np.ndarray:
    r = data[0]
    g = data[1]
    b = data[2]
    R = _robust_uint8(r)
    G = _robust_uint8(g)
    B = _robust_uint8(b)
    rgb = np.stack([R, G, B], axis=-1)
    if mask is not None:
        rgb[~mask] = 255
    logger = current_app.logger
    finite_r = np.isfinite(r)
    finite_g = np.isfinite(g)
    finite_b = np.isfinite(b)
    r_min = float(np.nanmin(r)) if finite_r.any() else float("nan")
    r_max = float(np.nanmax(r)) if finite_r.any() else float("nan")
    g_min = float(np.nanmin(g)) if finite_g.any() else float("nan")
    g_max = float(np.nanmax(g)) if finite_g.any() else float("nan")
    b_min = float(np.nanmin(b)) if finite_b.any() else float("nan")
    b_max = float(np.nanmax(b)) if finite_b.any() else float("nan")
    logger.info(
        "agrovista: display stats R[min=%.4f,max=%.4f] G[min=%.4f,max=%.4f] B[min=%.4f,max=%.4f]",
        r_min,
        r_max,
        g_min,
        g_max,
        b_min,
        b_max,
    )
    logger.info("agrovista: display rgb dtype=%s shape=%s", rgb.dtype, rgb.shape)
    return rgb


def _grayscale_visualisation(
    base: np.ndarray, mask: Optional[np.ndarray]
) -> np.ndarray:
    Gs = _robust_uint8(base)
    rgb = np.stack([Gs, Gs, Gs], axis=-1)
    if mask is not None:
        rgb[~mask] = 255
    logger = current_app.logger
    finite = np.isfinite(base)
    base_min = float(np.nanmin(base)) if finite.any() else float("nan")
    base_max = float(np.nanmax(base)) if finite.any() else float("nan")
    logger.info(
        "agrovista: display stats grayscale[min=%.4f,max=%.4f]",
        base_min,
        base_max,
    )
    logger.info("agrovista: display grayscale dtype=%s shape=%s", rgb.dtype, rgb.shape)
    return rgb


def generate_display_assets(
    image_id: str,
    tiff_uri: str,
    *,
    mode: ModeLiteral = "auto",
    max_display_px: int = 4096,
    force: bool = False,
) -> Dict[str, object]:
    """
    Generate lightweight display PNG + metadata for geospatial visualization.

    Parameters
    ----------
    image_id:
        Unique identifier of the source asset (typically UUID).
    tiff_uri:
        Absolute path to the GeoTIFF on local storage.
    mode:
        Rendering strategy: "rgb", "auto", or "pseudo_ndvi".
    max_display_px:
        Maximum width/height for the generated PNG to keep it lightweight.
    force:
        If True, regenerate assets even if they already exist.
    """
    if not image_id:
        raise GeoDisplayError("image_id is required.")

    if not tiff_uri:
        raise GeoDisplayError("tiff_uri is required.")

    mode_normalized = cast(ModeLiteral, str(mode or "auto").lower())
    if mode_normalized not in {"rgb", "auto", "pseudo_ndvi"}:
        raise GeoDisplayError(f"Unsupported mode: {mode}")

    tiff_path = Path(tiff_uri).resolve()
    media_root = Path(_media_root()).resolve()
    if not str(tiff_path).startswith(str(media_root)):
        raise GeoDisplayError("tiff_uri must be inside the media storage root.")

    if not tiff_path.exists():
        raise GeoDisplayError(f"Source TIFF not found: {tiff_path}")

    display_dir = _resolve_display_dir(image_id)
    display_png = display_dir / "display.png"
    metadata_json = display_dir / "metadata.json"
    storage_key = os.path.join("display", image_id, "display.png")

    if not force and display_png.exists() and metadata_json.exists():
        try:
            with metadata_json.open("r", encoding="utf-8") as fh:
                meta = json.load(fh)
            bounds = tuple(meta.get("bounds", [None, None, None, None]))
            return {
                "image_id": image_id,
                "display_png_path": str(display_png),
                "display_png_key": storage_key,
                "metadata_path": str(metadata_json),
                "bounds": bounds,
                "metadata": meta,
            }
        except Exception:
            pass

    with rasterio.open(tiff_path) as src:
        if src.count == 0:
            raise GeoDisplayError("The dataset does not contain any bands.")

        chosen_mode = _choose_mode(src, mode_normalized)
        out_h, out_w = _compute_out_shape(src.width, src.height, max_display_px)

        indexes = tuple(range(1, min(3, src.count) + 1))
        data = _read_downsampled(src, indexes, (out_h, out_w))
        valid_mask = _dataset_valid_mask(src, (out_h, out_w))

        if chosen_mode == "pseudo_ndvi" and data.shape[0] >= 3:
            rgb = _pseudo_ndvi_rgb(data[:3], valid_mask)
        elif data.shape[0] >= 3:
            rgb = _rgb_visualisation(data[:3], valid_mask)
        else:
            base_band = data[0]
            rgb = _grayscale_visualisation(base_band, valid_mask)

        Image.fromarray(rgb, mode="RGB").save(display_png, optimize=True)
        current_app.logger.info(
            "agrovista: display png saved %s size=%sx%s dtype=%s",
            display_png,
            rgb.shape[1],
            rgb.shape[0],
            rgb.dtype,
        )

        bounds_wgs84 = _dataset_bounds_wgs84(src)
        transform_dict = _transform_to_dict(src.transform)
        metadata = DisplayMetadata(
            image_id=image_id,
            width=src.width,
            height=src.height,
            bounds=bounds_wgs84,
            crs=src.crs.to_string() if src.crs else "unknown",
            transform=transform_dict,
            nodata=(
                float(src.nodata)
                if src.nodata is not None and not math.isnan(src.nodata)
                else None
            ),
            display_png_size={"width": int(rgb.shape[1]), "height": int(rgb.shape[0])},
            mode=chosen_mode,
            storage_key=storage_key,
        )

    with metadata_json.open("w", encoding="utf-8") as fh:
        json.dump(metadata.to_dict(), fh, ensure_ascii=False, indent=2)

    current_app.logger.info(
        "agrovista: generated display assets for %s at %s",
        image_id,
        display_dir,
    )

    return {
        "image_id": image_id,
        "display_png_path": str(display_png),
        "display_png_key": storage_key,
        "metadata_path": str(metadata_json),
        "bounds": list(metadata.bounds),
        "metadata": metadata.to_dict(),
    }
