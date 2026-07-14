"""Snapshot RGB del lote sobre la ortofoto.

Genera un recorte PNG del poligono dibujado en la herramienta NDVI. El recorte
se persiste como ``AssetVariant`` (kind="lot_snapshot") del asset de media
origen y se enlaza desde ``CommonAnalysis.lot_snapshot_variant_id``.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from flask import url_for
from PIL import Image, ImageDraw

from app.extensions import db
from app.modules.media.helpers import _media_root
from app.modules.media.models import Asset, AssetVariant, StorageLocation
from app.modules.media.storage import (
    delete_file_from_gcs,
    ensure_local_file,
    gcs_enabled,
    upload_file_to_gcs,
)
from app.modules.media.tasks import _resolve_cache_dir

SNAPSHOT_KIND = "lot_snapshot"
SNAPSHOT_DIR = "derived/lot_snapshots"
SNAPSHOT_MAX_DIM = 1280
OUTLINE_COLOR = (239, 68, 68)


class LotSnapshotError(Exception):
    """Errores del generador de snapshots de lote."""


def _source_path_for(asset: Asset) -> Path:
    media_root = Path(_media_root())
    if asset.storage == StorageLocation.GCS.value:
        return ensure_local_file(asset.storage_key)
    return media_root / asset.storage_key


def _preview_path_for(asset: Asset) -> Path:
    """Localiza el preview RGB preprocesado del asset."""
    source_path = _source_path_for(asset)
    from flask import current_app

    cache_dir = _resolve_cache_dir(current_app._get_current_object(), asset.uuid)
    preview = cache_dir / f"{source_path.stem}__rgb_preproc_preview.png"
    if not preview.exists():
        raise LotSnapshotError(f"RGB preview not found for asset {asset.uuid}")
    return preview


def _full_dimensions(asset: Asset, source_path: Path) -> Tuple[int, int]:
    if asset.width and asset.height:
        return int(asset.width), int(asset.height)
    try:
        import rasterio

        with rasterio.open(str(source_path)) as ds:
            return int(ds.width), int(ds.height)
    except Exception as exc:
        raise LotSnapshotError("unable to resolve full image dimensions") from exc


def generate_lot_snapshot(
    asset: Asset,
    vertices_full: Sequence[Sequence[float]],
    *,
    max_dim: int = SNAPSHOT_MAX_DIM,
) -> AssetVariant:
    """Recorta el bbox del poligono desde el preview RGB y dibuja su contorno."""
    if asset is None or asset.storage not in {
        StorageLocation.LOCAL.value,
        StorageLocation.GCS.value,
    }:
        raise LotSnapshotError("asset must be a supported media asset")
    if not vertices_full or len(vertices_full) < 3:
        raise LotSnapshotError("polygon requires at least 3 vertices")

    media_root = Path(_media_root())
    source_path = _source_path_for(asset)
    if not source_path.exists():
        raise LotSnapshotError(f"source file not found for asset {asset.uuid}")

    preview_path = _preview_path_for(asset)
    width_full, height_full = _full_dimensions(asset, source_path)

    with Image.open(preview_path) as img:
        preview = img.convert("RGB")

    sx = preview.width / float(width_full)
    sy = preview.height / float(height_full)
    points: List[Tuple[float, float]] = [
        (float(x) * sx, float(y) * sy) for x, y in vertices_full
    ]

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    pad_x = max(8.0, (max(xs) - min(xs)) * 0.05)
    pad_y = max(8.0, (max(ys) - min(ys)) * 0.05)
    x0 = max(0, int(min(xs) - pad_x))
    y0 = max(0, int(min(ys) - pad_y))
    x1 = min(preview.width, int(max(xs) + pad_x) + 1)
    y1 = min(preview.height, int(max(ys) + pad_y) + 1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        raise LotSnapshotError("polygon area is empty on the preview image")

    crop = preview.crop((x0, y0, x1, y1))
    shifted = [(px - x0, py - y0) for px, py in points]

    if max(crop.width, crop.height) > max_dim:
        scale = max_dim / float(max(crop.width, crop.height))
        new_size = (
            max(1, int(round(crop.width * scale))),
            max(1, int(round(crop.height * scale))),
        )
        crop = crop.resize(new_size, Image.LANCZOS)
        shifted = [(px * scale, py * scale) for px, py in shifted]

    draw = ImageDraw.Draw(crop)
    outline_width = max(2, round(max(crop.width, crop.height) / 200))
    draw.line(
        shifted + [shifted[0]],
        fill=OUTLINE_COLOR,
        width=outline_width,
        joint="curve",
    )

    out_dir = media_root / SNAPSHOT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{asset.uuid}_{uuid.uuid4().hex[:8]}.png"
    storage_key = f"{SNAPSHOT_DIR}/{filename}"
    out_path = out_dir / filename
    crop.save(out_path, optimize=True)

    variant_storage = StorageLocation.GCS.value if gcs_enabled() else StorageLocation.LOCAL.value
    if variant_storage == StorageLocation.GCS.value:
        upload_file_to_gcs(out_path, storage_key, "image/png")

    variant = AssetVariant(
        asset_id=asset.id,
        kind=SNAPSHOT_KIND,
        storage=variant_storage,
        storage_key=storage_key,
        width=crop.width,
        height=crop.height,
    )
    db.session.add(variant)
    return variant


def discard_lot_snapshot(variant: Optional[AssetVariant]) -> None:
    """Elimina (best-effort) el archivo y la fila de un snapshot reemplazado."""
    if variant is None or variant.kind != SNAPSHOT_KIND:
        return
    try:
        path = Path(_media_root()) / variant.storage_key
        if path.exists():
            path.unlink()
    except Exception:
        pass
    if variant.storage == StorageLocation.GCS.value:
        delete_file_from_gcs(variant.storage_key)
    db.session.delete(variant)


def resolve_lot_snapshot_url(analysis) -> Optional[str]:
    """URL servible del snapshot de un ``CommonAnalysis``, o ``None``."""
    variant = getattr(analysis, "lot_snapshot_variant", None) if analysis else None
    if variant is None or variant.storage not in {
        StorageLocation.LOCAL.value,
        StorageLocation.GCS.value,
    }:
        return None
    if variant.storage == StorageLocation.GCS.value:
        return url_for("media.serve_file", key=variant.storage_key)
    try:
        path = Path(_media_root()) / variant.storage_key
    except Exception:
        return None
    if not path.exists():
        return None
    return url_for("media.serve_file", key=variant.storage_key)
