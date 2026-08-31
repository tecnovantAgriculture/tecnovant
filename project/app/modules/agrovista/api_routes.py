import io
import json
import math
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import numpy as np
from flask import Response, abort, current_app, jsonify, request, send_file
from flask_jwt_extended import get_jwt, jwt_required
from pyproj import Transformer
from rasterio.transform import Affine, xy
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload

from app.core.controller import check_permission, check_resource_access
from app.extensions import db
from app.helpers.csv_handler import CsvHandler
from app.modules.foliage.models import CommonAnalysis, Lot, LotAssetGeometry, Nutrient
from app.modules.media.helpers import (
    PreprocessConfig,
    _media_root,
    preprocess_rgb_once,
    read_tif_window_as_linear_rgb,
)
from app.modules.media.models import Asset, StorageLocation
from app.modules.media.storage import ensure_local_file
from app.modules.media.tasks import _resolve_cache_dir

from . import agrovista_api as api
from .bromatologia import aforo_desde_proteina, perfil_desde_ngrdi
from .controller import ensure_processed, process_upload
from .helpers import (
    VisibleConfig,
    average_protein,
    combine_indices,
    compute_mineral_balance,
    compute_secondary_objective_targets,
    compute_visible_indices,
    polygon_mask,
    protein_to_nitrogen,
    secondary_target_map,
    srgb_to_linear,
)
from .models import (
    AnalysisCrop,
    NDVIImage,
    SecondaryObjective,
    SecondaryObjectiveNutrient,
)
from .services.lot_snapshot import (
    LotSnapshotError,
    discard_lot_snapshot,
    generate_lot_snapshot,
    resolve_lot_snapshot_url,
)


def _validate_id(value: str) -> str:
    if not value or not value.replace("-", "").replace("_", "").isalnum():
        abort(400, description="invalid id")
    return value


def _validate_vertices(vertices):
    if not isinstance(vertices, list) or len(vertices) < 3:
        abort(400, description="invalid vertices")
    out = []
    for p in vertices:
        if (not isinstance(p, (list, tuple))) or len(p) != 2:
            abort(400, description="invalid vertex")
        x, y = p
        if not (isinstance(x, (int, float)) and isinstance(y, (int, float))):
            abort(400, description="invalid vertex")
        if any(math.isnan(v) or math.isinf(v) for v in (x, y)):
            abort(400, description="invalid vertex")
        out.append([float(x), float(y)])
    return out


def _round_metric(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, 3)


def _resolve_wb_sidecar(asset: Asset) -> Optional[Dict[str, float]]:
    """Load WB scale factors from .wb.json sidecar, computing on-the-fly if absent.

    Returns {"scale_r", "scale_g", "scale_b"} or None when the source TIF cannot
    be found.  A missing sidecar triggers an inline gray-world scan (~800 ms) and
    the result is persisted for subsequent calls.
    """
    from app.modules.media.helpers import compute_wb_factors_from_tif

    app = current_app._get_current_object()
    cache_dir = _resolve_cache_dir(app, asset.uuid)
    wb_path = cache_dir / f"{asset.uuid}.wb.json"

    if wb_path.exists():
        try:
            return json.loads(wb_path.read_text())
        except Exception:
            pass

    try:
        media_root = Path(_media_root())
    except Exception:
        return None
    source_path = ensure_local_file(asset.storage_key) if asset.storage == StorageLocation.GCS.value else media_root / asset.storage_key
    if not source_path.exists():
        return None

    try:
        factors = compute_wb_factors_from_tif(source_path)
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            wb_path.write_text(json.dumps(factors))
        except Exception:
            pass
        return factors
    except Exception:
        current_app.logger.exception(
            "agrovista: wb factor computation failed for %s", asset.uuid
        )
        return None


def _find_media_asset(media_asset_id: Optional[int], img_id: str) -> Optional[Asset]:
    asset: Optional[Asset] = None
    if media_asset_id is not None:
        try:
            asset = db.session.get(Asset, int(media_asset_id))
        except Exception:
            asset = None
    if asset is None:
        asset = Asset.query.filter(Asset.uuid == img_id).first()
    return asset


def _protein_from_media(
    img_id: str,
    vertices,
    media_asset_id: Optional[int],
    visible_method: Optional[str],
    preview_width: Optional[float],
    preview_height: Optional[float],
    width_full_hint: Optional[float],
    height_full_hint: Optional[float],
    scale_x_hint: Optional[float],
    scale_y_hint: Optional[float],
    coords_full_res: bool = False,
):
    """Calcula proteína y variables leyendo la ventana BBox directamente del TIF."""

    asset = _find_media_asset(media_asset_id, img_id)
    if asset is None:
        abort(404, description="asset not found")
    if asset.storage not in {StorageLocation.LOCAL.value, StorageLocation.GCS.value}:
        abort(400, description="unsupported storage for media asset")
    if not asset.crs or not asset.transform:
        abort(400, description="asset lacks georeference")

    try:
        media_root = Path(_media_root())
    except Exception:
        abort(500, description="media storage unavailable")
    source_path = ensure_local_file(asset.storage_key) if asset.storage == StorageLocation.GCS.value else media_root / asset.storage_key
    if not source_path.exists():
        abort(404, description="source TIF not found")

    # WB factors from sidecar (computed on-the-fly if absent, ~800 ms first time).
    wb_factors = _resolve_wb_sidecar(asset)

    width_full = asset.width
    height_full = asset.height
    if width_full is None or height_full is None:
        import rasterio as _rasterio

        try:
            with _rasterio.open(str(source_path)) as ds:
                width_full, height_full = ds.width, ds.height
        except Exception:
            abort(500, description="unable to read image dimensions")

    # Si el frontend ya envía coordenadas en la resolución completa, úsalo sin reescalar
    if coords_full_res:
        scaled_vertices = [(float(x), float(y)) for x, y in vertices]
    else:
        # Escala vértices desde coords de preview a resolución completa, manteniendo centros
        pw = preview_width or width_full_hint or width_full
        ph = preview_height or height_full_hint or height_full
        sx = float(scale_x_hint) if scale_x_hint else ((width_full / pw) if pw else 1.0)
        sy = (
            float(scale_y_hint) if scale_y_hint else ((height_full / ph) if ph else 1.0)
        )
        scaled_vertices = [(float(x) * sx, float(y) * sy) for x, y in vertices]

    xs = [p[0] for p in scaled_vertices]
    ys = [p[1] for p in scaled_vertices]
    x0 = max(0, int(math.floor(min(xs))))
    x1 = min(width_full, int(math.ceil(max(xs))))
    y0 = max(0, int(math.floor(min(ys))))
    y1 = min(height_full, int(math.ceil(max(ys))))
    if x1 <= x0 or y1 <= y0:
        abort(400, description="invalid area")

    shifted_vertices = [(x - x0, y - y0) for x, y in scaled_vertices]

    try:
        rgb = read_tif_window_as_linear_rgb(source_path, x0, y0, x1, y1, wb_factors)
    except Exception:
        current_app.logger.exception(
            "agrovista: TIF window read failed for %s", asset.uuid
        )
        abort(500, description="unable to read image data")

    # La lectura puede reducir ventanas muy grandes. Ajustar el polígono a la
    # matriz resultante mantiene el cálculo correcto sin crear arreglos enormes.
    source_width = max(1, x1 - x0)
    source_height = max(1, y1 - y0)
    mask_scale_x = rgb.shape[1] / float(source_width)
    mask_scale_y = rgb.shape[0] / float(source_height)
    mask_vertices = [
        (x * mask_scale_x, y * mask_scale_y) for x, y in shifted_vertices
    ]
    mask = polygon_mask(rgb.shape[:2], mask_vertices)

    vis_cfg = VisibleConfig(
        do_linearize=False,
        do_white_balance=wb_factors is None,  # local gray_world when no sidecar
        shadow_mask=True,
        median_size=0,
    )
    idx = compute_visible_indices(rgb, vis_cfg)
    vm_raw = (visible_method or "").strip().lower()
    vm = vm_raw if vm_raw in {"combined", "vari", "gli", "ngrdi", "exg"} else "combined"
    try:
        ndvi = combine_indices(idx, method=vm)
    except Exception:
        current_app.logger.warning(
            "agrovista: combine_indices fallback to combined for %s", asset.uuid
        )
        ndvi = combine_indices(idx, method="combined")
        vm = "combined"

    avg = average_protein(ndvi, mask, min_count=5)  # solo verifica píxeles válidos
    if math.isnan(avg):
        abort(400, description="invalid area")

    def _masked_mean(arr):
        if arr is None:
            return float("nan")
        finite_mask = mask & np.isfinite(arr)
        vals = arr[finite_mask]
        if vals.size == 0:
            return float("nan")
        return float(np.mean(vals))

    stats = {
        "vi": _masked_mean(ndvi),
        "vari": _masked_mean(idx.get("VARI")),
        "gli": _masked_mean(idx.get("GLI")),
        "ngrdi": _masked_mean(idx.get("NGRDI")),
        "exg": _masked_mean(idx.get("ExG") if "ExG" in idx else idx.get("EXG")),
        "nbi": _masked_mean(idx.get("NBI")),
    }

    ngrdi_val = stats.get("ngrdi") or 0.0
    _broma = perfil_desde_ngrdi(ngrdi_val) if math.isfinite(ngrdi_val) else None

    # Fuente única de verdad: bromatologia.py. Fallback a avg solo si NGRDI no disponible.
    prot_val = _broma["proteina_pct"] if _broma else avg
    nitrogen = protein_to_nitrogen(prot_val)

    nutrient_records = Nutrient.query.order_by(Nutrient.id.asc()).all()
    nutrient_payloads = compute_secondary_objective_targets(
        prot_val,
        nitrogen,
        nutrient_records,
    )

    payload = {
        "protein": round(prot_val, 2),
        "nitrogen": round(nitrogen, 2) if math.isfinite(nitrogen) else None,
        "vi": _round_metric(stats.get("vi")),
        "vari": _round_metric(stats.get("vari")),
        "gli": _round_metric(stats.get("gli")),
        "ngrdi": _round_metric(stats.get("ngrdi")),
        "exg": _round_metric(stats.get("exg")),
        "nbi": _round_metric(stats.get("nbi")),
        "variables": {
            "vi": _round_metric(stats.get("vi")),
            "vari": _round_metric(stats.get("vari")),
            "gli": _round_metric(stats.get("gli")),
            "ngrdi": _round_metric(stats.get("ngrdi")),
            "exg": _round_metric(stats.get("exg")),
            "nbi": _round_metric(stats.get("nbi")),
        },
        "bromatologia": (
            {
                "proteina_pct": _broma["proteina_pct"] if _broma else None,
                "energia_mcal": _broma["energia_mcal"] if _broma else None,
                "energia2_mcal": _broma["energia2_mcal"] if _broma else None,
                "fda_pct": _broma["fda_pct"] if _broma else None,
                "fdn_pct": _broma["fdn_pct"] if _broma else None,
                "energia_mj": _broma["energia_mj"] if _broma else None,
                "aforo_ua_ha": _broma["aforo_ua_ha"] if _broma else None,
                "indice_vigor": _broma["indice_vigor"] if _broma else None,
                "en_rango": _broma["en_rango_valido"] if _broma else None,
                "minerales": _broma["minerales"] if _broma else None,
            }
            if _broma
            else None
        ),
        "ndvi_ready": True,
        "ndvi_stamp": int(asset.created_at.timestamp()) if asset.created_at else None,
        "method": "ndvi_approx",
        "visible_method": vm,
        "has_nir": False,
        "source": "media",
        "media_asset_id": asset.id,
    }
    payload["nutrients"] = nutrient_payloads
    return jsonify(payload)


def _affine_from_dict(data: dict | None) -> Optional[Affine]:
    if not data or not isinstance(data, dict):
        return None
    try:
        return Affine(
            float(data.get("a", 0)),
            float(data.get("b", 0)),
            float(data.get("c", 0)),
            float(data.get("d", 0)),
            float(data.get("e", 0)),
            float(data.get("f", 0)),
        )
    except Exception:
        return None



def _polygon_coordinates(value):
    try:
        obj = json.loads(value) if isinstance(value, str) else value
        if obj.get("type") == "Feature":
            obj = obj.get("geometry") or {}
        if obj.get("type") != "Polygon" or not obj.get("coordinates"):
            raise ValueError
        coords = obj["coordinates"][0]
        if len(coords) < 3:
            raise ValueError
        return [(float(item[0]), float(item[1])) for item in coords]
    except (TypeError, ValueError, KeyError, AttributeError, json.JSONDecodeError):
        abort(400, description="invalid polygon geometry")


def _feature_from_coordinates(coords):
    points = [[float(x), float(y)] for x, y in coords]
    if points and points[0] != points[-1]:
        points.append(points[0])
    return {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [points]}}


def _preview_geometry_to_wgs84(geometry, asset, preview_width, preview_height):
    affine = _affine_from_dict(asset.transform)
    if affine is None or not asset.crs or not asset.width or not asset.height:
        abort(400, description="orthophoto lacks valid georeference")
    transformer = Transformer.from_crs(asset.crs, "EPSG:4326", always_xy=True)
    sx = float(asset.width) / float(preview_width)
    sy = float(asset.height) / float(preview_height)
    result = []
    for x_preview, y_preview in _polygon_coordinates(geometry):
        col = x_preview * sx
        row = (float(preview_height) - y_preview) * sy
        x_map, y_map = affine * (col, row)
        result.append(transformer.transform(x_map, y_map))
    return _feature_from_coordinates(result)


def _wgs84_geometry_to_preview(geometry, asset, preview_width, preview_height):
    affine = _affine_from_dict(asset.transform)
    if affine is None or not asset.crs or not asset.width or not asset.height:
        abort(400, description="orthophoto lacks valid georeference")
    inverse = ~affine
    transformer = Transformer.from_crs("EPSG:4326", asset.crs, always_xy=True)
    result = []
    for lon, lat in _polygon_coordinates(geometry):
        x_map, y_map = transformer.transform(lon, lat)
        col, row = inverse * (x_map, y_map)
        x_preview = col * float(preview_width) / float(asset.width)
        y_preview = float(preview_height) - (row * float(preview_height) / float(asset.height))
        result.append((x_preview, y_preview))
    return _feature_from_coordinates(result)


def _geometry_fits_asset(geometry, asset, tolerance=2.0):
    """Indica si el polígono geográfico está completamente cubierto por el TIF."""
    affine = _affine_from_dict(asset.transform)
    if affine is None or not asset.crs or not asset.width or not asset.height:
        return False
    try:
        inverse = ~affine
        transformer = Transformer.from_crs("EPSG:4326", asset.crs, always_xy=True)
        coordinates = _polygon_coordinates(geometry)
        if len(coordinates) < 3:
            return False
        for lon, lat in coordinates:
            x_map, y_map = transformer.transform(lon, lat)
            col, row = inverse * (x_map, y_map)
            if col < -tolerance or row < -tolerance:
                return False
            if col > float(asset.width) + tolerance or row > float(asset.height) + tolerance:
                return False
        return True
    except Exception:
        return False


def _asset_legacy_preview_dimensions(asset):
    """Reconstruye las dimensiones usadas por la vista Leaflet de un TIF legado."""
    width = int(asset.width or 0)
    height = int(asset.height or 0)
    if width <= 0 or height <= 0:
        return width, height
    max_dim = int(current_app.config.get("MEDIA_PREVIEW_MAX_DIM", 2048) or 2048)
    if max_dim <= 0 or max(width, height) <= max_dim:
        return width, height
    scale = float(max(width, height)) / float(max_dim)
    return max(1, int(round(width / scale))), max(1, int(round(height / scale)))


def _preview_geometry_fits_dimensions(geometry, width, height, tolerance=2.0):
    try:
        coordinates = _polygon_coordinates(geometry)
        if len(coordinates) < 3:
            return False
        return all(
            -tolerance <= float(x) <= float(width) + tolerance
            and -tolerance <= float(y) <= float(height) + tolerance
            for x, y in coordinates
        )
    except Exception:
        return False


def _legacy_lot_geographic_geometry(lot):
    """Recupera el GPS legado eligiendo la escala que coincide con más ortofotos."""
    if not lot.geometry or not lot.media_asset_id:
        return None
    legacy_asset = db.session.get(Asset, lot.media_asset_id)
    if legacy_asset is None:
        return None
    legacy_geometry = json.loads(lot.geometry)
    max_dimensions = {
        int(current_app.config.get("MEDIA_PREVIEW_MAX_DIM", 2048) or 2048),
        int(current_app.config.get("MEDIA_DISPLAY_MAX_DIM", 4096) or 4096),
        2048,
        4096,
        max(int(legacy_asset.width or 0), int(legacy_asset.height or 0)),
    }
    dimensions = []
    for max_dim in max_dimensions:
        if max_dim <= 0 or not legacy_asset.width or not legacy_asset.height:
            continue
        if max(legacy_asset.width, legacy_asset.height) <= max_dim:
            width, height = int(legacy_asset.width), int(legacy_asset.height)
        else:
            scale = float(max(legacy_asset.width, legacy_asset.height)) / float(max_dim)
            width = max(1, int(round(float(legacy_asset.width) / scale)))
            height = max(1, int(round(float(legacy_asset.height) / scale)))
        if (width, height) not in dimensions:
            dimensions.append((width, height))
    candidate_assets = (
        Asset.query
        .filter(
            Asset.ext.in_(["tif", "tiff"]),
            Asset.is_geo.is_(True),
            Asset.width.isnot(None),
            Asset.height.isnot(None),
            Asset.crs.isnot(None),
            Asset.transform.isnot(None),
        )
        .all()
    )
    best = None
    best_score = -1
    for legacy_width, legacy_height in dimensions:
        try:
            geographic = _preview_geometry_to_wgs84(
                legacy_geometry, legacy_asset, legacy_width, legacy_height
            )
        except Exception:
            continue
        score = sum(1 for candidate in candidate_assets if _geometry_fits_asset(geographic, candidate))
        if score > best_score:
            best = (legacy_asset, legacy_geometry, geographic, legacy_width, legacy_height)
            best_score = score
    return best


def _scoped_farm_lots(farm_id):
    lots = Lot.query.filter_by(farm_id=farm_id, active=True).all()
    if lots and not check_resource_access(lots[0].farm, get_jwt()):
        abort(403, description="forbidden")
    return lots


@api.route("/lot-asset-geometries", methods=["GET", "POST", "DELETE"])
@jwt_required()
def lot_asset_geometries():
    """Guarda y proyecta geometrías de lotes entre ortofotos georreferenciadas."""
    if request.method == "POST":
        data = request.get_json(force=True, silent=False) or {}
        try:
            lot_id = int(data.get("lot_id"))
            asset_id = int(data.get("media_asset_id"))
            preview_width = int(round(float(data.get("preview_width"))))
            preview_height = int(round(float(data.get("preview_height"))))
        except (TypeError, ValueError):
            abort(400, description="invalid identifiers or preview dimensions")
        if preview_width <= 0 or preview_height <= 0:
            abort(400, description="invalid preview dimensions")
        lot = db.session.get(Lot, lot_id)
        asset = db.session.get(Asset, asset_id)
        if lot is None or asset is None:
            abort(404, description="lot or orthophoto not found")
        if not check_resource_access(lot.farm, get_jwt()):
            abort(403, description="forbidden")
        geometry_obj = _feature_from_coordinates(_polygon_coordinates(data.get("geometry")))
        geographic_obj = _preview_geometry_to_wgs84(geometry_obj, asset, preview_width, preview_height)
        record = LotAssetGeometry.query.filter_by(lot_id=lot.id, media_asset_id=asset.id).first()
        if record is None:
            record = LotAssetGeometry(lot_id=lot.id, media_asset_id=asset.id)
            db.session.add(record)
        record.geometry = json.dumps(geometry_obj)
        record.geographic_geometry = json.dumps(geographic_obj)
        record.preview_width = preview_width
        record.preview_height = preview_height
        record.calculation_data = None
        record.calculated_at = None
        is_objective = bool(data.get("is_objective"))
        if is_objective:
            Lot.query.filter(Lot.farm_id == lot.farm_id, Lot.id != lot.id).update({"is_objective": False}, synchronize_session=False)
            lot.is_objective = True
        elif not lot.is_objective:
            lot.is_objective = False
        lot.geometry = record.geometry
        lot.media_asset_id = asset.id
        db.session.commit()
        return jsonify({"id": record.id, "lot_id": lot.id, "lot_name": lot.name, "geometry": record.geometry, "geographic_geometry": record.geographic_geometry, "media_asset_id": asset.id, "is_objective": bool(lot.is_objective)}), 200

    try:
        farm_id = int(request.args.get("farm_id"))
        asset_id = int(request.args.get("media_asset_id"))
    except (TypeError, ValueError):
        abort(400, description="invalid farm or orthophoto")
    lots = _scoped_farm_lots(farm_id)
    asset = db.session.get(Asset, asset_id)
    if asset is None:
        abort(404, description="orthophoto not found")

    if request.method == "DELETE":
        lot_id = request.args.get("lot_id", type=int)
        lot = next((item for item in lots if item.id == lot_id), None)
        if lot is None:
            abort(404, description="lot not found")
        record = LotAssetGeometry.query.filter_by(lot_id=lot.id, media_asset_id=asset.id).first()
        if record:
            db.session.delete(record)
        if lot.media_asset_id == asset.id:
            latest = LotAssetGeometry.query.filter(LotAssetGeometry.lot_id == lot.id, LotAssetGeometry.media_asset_id != asset.id).order_by(LotAssetGeometry.updated_at.desc()).first()
            lot.geometry = latest.geometry if latest else None
            lot.media_asset_id = latest.media_asset_id if latest else None
        if not LotAssetGeometry.query.filter(LotAssetGeometry.lot_id == lot.id, LotAssetGeometry.media_asset_id != asset.id).first():
            lot.is_objective = False
        db.session.commit()
        return jsonify({"deleted": True}), 200

    preview_width = request.args.get("preview_width", type=float) or asset.width
    preview_height = request.args.get("preview_height", type=float) or asset.height
    items = []
    created_legacy_records = False
    for lot in lots:
        record = LotAssetGeometry.query.filter_by(lot_id=lot.id, media_asset_id=asset.id).first()
        transferred = False
        source_asset_name = None
        if record:
            geometry_obj = json.loads(record.geometry)
            if not _preview_geometry_fits_dimensions(geometry_obj, preview_width, preview_height):
                legacy = _legacy_lot_geographic_geometry(lot)
                if legacy is None:
                    continue
                _, _, geographic_obj, _, _ = legacy
                repaired_geometry = _wgs84_geometry_to_preview(
                    geographic_obj, asset, preview_width, preview_height
                )
                if not _preview_geometry_fits_dimensions(repaired_geometry, preview_width, preview_height):
                    continue
                geometry_obj = repaired_geometry
                record.geometry = json.dumps(geometry_obj)
                record.geographic_geometry = json.dumps(geographic_obj)
                record.preview_width = int(round(preview_width))
                record.preview_height = int(round(preview_height))
                record.calculation_data = None
                record.calculated_at = None
                created_legacy_records = True
        elif lot.media_asset_id == asset.id and lot.geometry:
            legacy = _legacy_lot_geographic_geometry(lot)
            if legacy is None:
                continue
            _, _, geographic_obj, _, _ = legacy
            geometry_obj = _wgs84_geometry_to_preview(
                geographic_obj, asset, preview_width, preview_height
            )
            record = LotAssetGeometry(
                lot_id=lot.id,
                media_asset_id=asset.id,
                geometry=json.dumps(geometry_obj),
                geographic_geometry=json.dumps(geographic_obj),
                preview_width=int(round(preview_width)),
                preview_height=int(round(preview_height)),
            )
            db.session.add(record)
            created_legacy_records = True
        else:
            source = LotAssetGeometry.query.filter_by(lot_id=lot.id).order_by(LotAssetGeometry.updated_at.desc()).first()
            if not source and lot.geometry and lot.media_asset_id:
                legacy = _legacy_lot_geographic_geometry(lot)
                if legacy is not None:
                    legacy_asset, legacy_geometry, legacy_geographic, legacy_width, legacy_height = legacy
                    source = LotAssetGeometry(
                        lot_id=lot.id,
                        media_asset_id=legacy_asset.id,
                        geometry=json.dumps(legacy_geometry),
                        geographic_geometry=json.dumps(legacy_geographic),
                        preview_width=legacy_width,
                        preview_height=legacy_height,
                    )
                    db.session.add(source)
                    db.session.flush()
                    created_legacy_records = True
            if not source:
                continue
            geometry_obj = _wgs84_geometry_to_preview(source.geographic_geometry, asset, preview_width, preview_height)
            if not _preview_geometry_fits_dimensions(geometry_obj, preview_width, preview_height):
                legacy = _legacy_lot_geographic_geometry(lot)
                if legacy is None:
                    continue
                _, _, repaired_geographic, _, _ = legacy
                geometry_obj = _wgs84_geometry_to_preview(
                    repaired_geographic, asset, preview_width, preview_height
                )
                if not _preview_geometry_fits_dimensions(geometry_obj, preview_width, preview_height):
                    continue
                source.geographic_geometry = json.dumps(repaired_geographic)
                source.calculation_data = None
                source.calculated_at = None
                created_legacy_records = True
            transferred = True
            source_asset = db.session.get(Asset, source.media_asset_id)
            source_asset_name = source_asset.original_name if source_asset else None
            record = LotAssetGeometry(
                lot_id=lot.id,
                media_asset_id=asset.id,
                geometry=json.dumps(geometry_obj),
                geographic_geometry=source.geographic_geometry,
                preview_width=int(round(preview_width)),
                preview_height=int(round(preview_height)),
            )
            db.session.add(record)
            created_legacy_records = True
        items.append({"lot_id": lot.id, "lot_name": lot.name, "geometry": json.dumps(geometry_obj), "is_objective": bool(lot.is_objective), "saved_for_asset": bool(record or lot.media_asset_id == asset.id), "transferred": transferred, "source_asset_name": source_asset_name, "calculation_data": record.calculation_data if record else None, "calculated_at": record.calculated_at.isoformat() if record and record.calculated_at else None})
    if created_legacy_records:
        db.session.commit()
    return jsonify({"items": items, "objective_lot_id": next((lot.id for lot in lots if lot.is_objective), None)}), 200


@api.route("/lot-asset-calculations", methods=["GET"])
@jwt_required()
def list_lot_asset_calculations():
    """Lista el historial calculado de una finca, separado por ortofoto."""
    farm_id = request.args.get("farm_id", type=int)
    if not farm_id:
        abort(400, description="farm_id is required")
    lots = _scoped_farm_lots(farm_id)
    lot_map = {lot.id: lot for lot in lots}
    if not lot_map:
        return jsonify({"items": []}), 200

    existing_records = LotAssetGeometry.query.filter(LotAssetGeometry.lot_id.in_(lot_map)).all()
    existing_keys = {(record.lot_id, record.media_asset_id) for record in existing_records}
    source_by_lot = {}
    for record in existing_records:
        if record.geographic_geometry and record.lot_id not in source_by_lot:
            source_by_lot[record.lot_id] = record.geographic_geometry

    if source_by_lot:
        candidate_assets = (
            Asset.query
            .filter(
                Asset.ext.in_(["tif", "tiff"]),
                Asset.is_geo.is_(True),
                Asset.width.isnot(None),
                Asset.height.isnot(None),
                Asset.crs.isnot(None),
                Asset.transform.isnot(None),
            )
            .all()
        )
        created_records = False
        for asset in candidate_assets:
            for lot_id, geographic_geometry in source_by_lot.items():
                if (lot_id, asset.id) in existing_keys:
                    continue
                if not _geometry_fits_asset(geographic_geometry, asset):
                    continue
                preview_geometry = _wgs84_geometry_to_preview(
                    geographic_geometry, asset, asset.width, asset.height
                )
                db.session.add(LotAssetGeometry(
                    lot_id=lot_id,
                    media_asset_id=asset.id,
                    geometry=json.dumps(preview_geometry),
                    geographic_geometry=geographic_geometry,
                    preview_width=asset.width,
                    preview_height=asset.height,
                ))
                existing_keys.add((lot_id, asset.id))
                created_records = True
        if created_records:
            db.session.commit()

    records = (
        LotAssetGeometry.query
        .filter(LotAssetGeometry.lot_id.in_(lot_map))
        .order_by(LotAssetGeometry.calculated_at.desc(), LotAssetGeometry.id.desc())
        .all()
    )
    items = []
    for record in records:
        asset = db.session.get(Asset, record.media_asset_id)
        lot = lot_map.get(record.lot_id)
        items.append({
            "id": record.id,
            "lot_id": record.lot_id,
            "lot_name": lot.name if lot else "Lote",
            "farm_id": farm_id,
            "media_asset_id": record.media_asset_id,
            "asset_uuid": asset.uuid if asset else "",
            "orthophoto_name": asset.original_name if asset else "",
            "geometry": record.geometry,
            "preview_width": record.preview_width,
            "preview_height": record.preview_height,
            "width_full": asset.width if asset else None,
            "height_full": asset.height if asset else None,
            "calculation_data": record.calculation_data,
            "calculated_at": record.calculated_at.isoformat() if record.calculated_at else None,
        })
    return jsonify({"items": items}), 200


@api.route("/lot-asset-geometries/calculation", methods=["POST"])
@jwt_required()
def save_lot_asset_calculation():
    """Persiste el cálculo de un lote para una ortofoto específica."""
    data = request.get_json(force=True, silent=False) or {}
    try:
        lot_id = int(data.get("lot_id"))
        asset_id = int(data.get("media_asset_id"))
    except (TypeError, ValueError):
        abort(400, description="invalid lot or orthophoto")
    calculation = data.get("calculation_data")
    if not isinstance(calculation, dict):
        abort(400, description="invalid calculation data")
    lot = db.session.get(Lot, lot_id)
    if lot is None or not check_resource_access(lot.farm, get_jwt()):
        abort(404, description="lot not found")
    record = LotAssetGeometry.query.filter_by(lot_id=lot_id, media_asset_id=asset_id).first()
    if record is None:
        abort(404, description="polygon is not saved for this orthophoto")
    record.calculation_data = calculation
    record.calculated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"saved": True, "calculated_at": record.calculated_at.isoformat()}), 200


@api.route("/polygon-kmz", methods=["POST"])
@jwt_required()
def polygon_kmz():
    """Convierte un polígono de coordenadas de imagen a KMZ georreferenciado.

    Recibe vértices en coordenadas de preview o full-res, los transforma
    a coordenadas geográficas (EPSG:4326) usando el CRS y affine del asset,
    y devuelve un archivo KMZ descargable.

    :status 200: Archivo KMZ generado exitosamente
    :status 400: Vértices inválidos, dimensiones no disponibles o CRS inválido
    :status 404: Asset no encontrado
    """
    data = request.get_json(force=True, silent=False) or {}
    img_id = _validate_id(str(data.get("id", "")))
    vertices = _validate_vertices(data.get("vertices", []))
    coords_full_res = bool(data.get("coords_full_res"))
    media_asset_id = data.get("media_asset_id")
    preview_width = data.get("width_preview")
    preview_height = data.get("height_preview")
    width_full_hint = data.get("width_full")
    height_full_hint = data.get("height_full")
    scale_x_hint = data.get("scale_x")
    scale_y_hint = data.get("scale_y")

    asset = _find_media_asset(media_asset_id, img_id)
    if asset is None:
        abort(404, description="asset not found")
    if not asset.crs or not asset.transform:
        abort(400, description="asset lacks georeference")

    width_full = width_full_hint or asset.width
    height_full = height_full_hint or asset.height
    if not width_full or not height_full:
        abort(400, description="asset dimensions unavailable")

    if coords_full_res:
        scaled_vertices = [(float(x), float(y)) for x, y in vertices]
    else:
        pw = preview_width or width_full
        ph = preview_height or height_full
        if not pw or not ph:
            abort(400, description="preview dimensions unavailable")

        sx = float(width_full) / float(pw)
        sy = float(height_full) / float(ph)
        # Map centros de píxel del preview a centros en full-res
        scaled_vertices = [(float(x) * sx, float(y) * sy) for x, y in vertices]

    affine = _affine_from_dict(asset.transform)
    if affine is None:
        abort(400, description="invalid transform")

    try:
        transformer = Transformer.from_crs(asset.crs, "EPSG:4326", always_xy=True)
    except Exception:
        abort(400, description="invalid CRS")

    coords = []
    for x, y in scaled_vertices:
        # usar centro de píxel para evitar desplazamientos; xy espera (row, col)
        x_map, y_map = xy(affine, y, x, offset="center")
        lon, lat = transformer.transform(x_map, y_map)
        coords.append((lon, lat))
    if coords and (coords[0] != coords[-1]):
        coords.append(coords[0])

    kml_coords = " ".join(f"{lon},{lat},0" for lon, lat in coords)
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Polygon {img_id}</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>{kml_coords}</coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>
"""
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", kml)
    mem.seek(0)
    fname = f"polygon_{img_id}.kmz"
    return send_file(
        mem,
        mimetype="application/vnd.google-earth.kmz",
        as_attachment=True,
        download_name=fname,
        max_age=0,
    )


def _iso(dt):
    if not dt:
        return None
    try:
        return dt.isoformat()
    except AttributeError:
        return None


def _serialize_nutrient_target(target: SecondaryObjectiveNutrient) -> Dict[str, object]:
    nutrient = target.nutrient
    return {
        "id": target.id,
        "nutrient_id": target.nutrient_id,
        "target_value": target.target_value,
        "nutrient_name": getattr(nutrient, "name", None),
        "nutrient_symbol": getattr(nutrient, "symbol", None),
        "nutrient_unit": getattr(nutrient, "unit", None),
        "created_at": _iso(target.created_at),
        "updated_at": _iso(target.updated_at),
    }


def _serialize_secondary_objective(obj: SecondaryObjective) -> Dict[str, object]:
    crop = obj.analysis_crop
    targets = sorted(
        obj.nutrient_targets,
        key=lambda item: (item.nutrient_id or 0, item.id or 0),
    )
    return {
        "id": obj.id,
        "analysis_crop_id": obj.analysis_crop_id,
        "analysis_crop": {
            "id": getattr(crop, "id", None),
            "name": getattr(crop, "name", None),
            "description": getattr(crop, "description", None),
        },
        "protein_average": obj.protein_average,
        "nitrogen_estimated": obj.nitrogen_estimated,
        "created_at": _iso(obj.created_at),
        "updated_at": _iso(obj.updated_at),
        "nutrient_targets": [_serialize_nutrient_target(target) for target in targets],
    }


def _serialize_analysis_crop(crop: AnalysisCrop) -> Dict[str, object]:
    return {
        "id": crop.id,
        "name": crop.name,
        "description": crop.description,
        "created_at": _iso(crop.created_at),
        "updated_at": _iso(crop.updated_at),
    }


def _as_float(value, default: float | None = None) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    return result


@api.route("/upload", methods=["POST"])
@jwt_required()
@check_permission(required_roles=["administrator", "reseller"])
def upload():
    """Sube y procesa una imagen multiespectral (GeoTIFF).

    Solo administradores y resellers. El archivo se recibe como
    multipart/form-data campo 'file'. El procesamiento extrae
    índices de vegetación y los persiste en caché NPZ.

    :status 201: Imagen procesada exitosamente
    :status 400: Archivo inválido o error de procesamiento
    :status 500: Error interno de procesamiento
    """
    try:
        meta = process_upload(request.files.get("file"))
        return jsonify(meta), 201
    except ValueError as e:
        abort(400, description=str(e))
    except Exception:
        abort(500, description="processing error")


@api.route("/image/<img_id>.png", methods=["GET"])
@jwt_required()
def image(img_id: str):
    """Sirve una imagen PNG pre-procesada desde el almacenamiento NDVI.

    :param img_id: ID de la imagen NDVI registrada
    :status 200: Imagen PNG servida (cache 1h)
    :status 404: Imagen no encontrada en BD o en disco
    """
    _validate_id(img_id)
    record = db.session.get(NDVIImage, img_id)
    if not record:
        abort(404)
    path = Path(record.png_path)
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="image/png", max_age=3600)


@api.route("/protein", methods=["POST"])
@jwt_required()
def protein():
    """Calcula proteína cruda, nitrógeno y perfil mineral desde un polígono.

    Recibe vértices de un polígono sobre una imagen multiespectral y
    retorna estimaciones de proteína, nitrógeno, índices de vegetación
    (VI, VARI, GLI, NGRDI, ExG, NBI), perfil bromatológico y objetivos
    secundarios de nutrientes.

    Soporta dos fuentes: assets de media (source=media) y registros
    NDVI históricos.

    :status 200: JSON con proteína, nitrógeno, índices y perfil mineral
    :status 400: Vértices inválidos o área sin píxeles válidos
    :status 404: Asset/imagen no encontrada
    :status 500: Error de lectura del TIF
    """
    data = request.get_json(force=True, silent=False) or {}
    img_id = _validate_id(str(data.get("id", "")))
    vertices = _validate_vertices(data.get("vertices", []))

    source = str(data.get("source") or "").lower()
    media_asset_id = data.get("media_asset_id")
    visible_method = data.get("visible_method")
    preview_width = data.get("width_preview")
    preview_height = data.get("height_preview")
    width_full_hint = data.get("width_full")
    height_full_hint = data.get("height_full")
    scale_x_hint = data.get("scale_x")
    scale_y_hint = data.get("scale_y")
    coords_full_res = bool(data.get("coords_full_res"))
    if source == "media" or media_asset_id is not None:
        return _protein_from_media(
            img_id,
            vertices,
            media_asset_id,
            visible_method,
            preview_width,
            preview_height,
            width_full_hint,
            height_full_hint,
            scale_x_hint,
            scale_y_hint,
            coords_full_res,
        )

    meta = ensure_processed(img_id)
    ndvi = np.load(meta["npy_path"], allow_pickle=False)
    mask = polygon_mask(ndvi.shape, vertices)
    avg = average_protein(ndvi, mask)  # solo verifica píxeles válidos
    if math.isnan(avg):
        abort(400, description="invalid area")

    def _masked_mean(arr):
        if arr is None:
            return float("nan")
        finite_mask = mask & np.isfinite(arr)
        vals = arr[finite_mask]
        if vals.size == 0:
            return float("nan")
        return float(np.mean(vals))

    stats = {
        "vi": _masked_mean(ndvi),
    }

    index_paths = meta.get("indices_paths", {})
    for key, name in (
        ("vari", "vari"),
        ("gli", "gli"),
        ("ngrdi", "ngrdi"),
        ("exg", "exg"),
        ("nbi", "nbi"),
    ):
        path = index_paths.get(key)
        if not path:
            stats[name] = float("nan")
            continue
        try:
            arr = np.load(path, allow_pickle=False)
        except Exception:
            stats[name] = float("nan")
            continue
        stats[name] = _masked_mean(arr)

    ngrdi_val = stats.get("ngrdi") or 0.0
    _broma = perfil_desde_ngrdi(ngrdi_val) if math.isfinite(ngrdi_val) else None

    # Fuente única de verdad: bromatologia.py. Fallback a avg solo si NGRDI no disponible.
    prot_val = _broma["proteina_pct"] if _broma else avg
    nitrogen = protein_to_nitrogen(prot_val)

    nutrient_records = Nutrient.query.order_by(Nutrient.id.asc()).all()
    nutrient_payloads = compute_secondary_objective_targets(
        prot_val,
        nitrogen,
        nutrient_records,
    )

    payload = {
        "protein": round(prot_val, 2),
        "nitrogen": round(nitrogen, 2) if math.isfinite(nitrogen) else None,
        "vi": _round_metric(stats.get("vi")),
        "vari": _round_metric(stats.get("vari")),
        "gli": _round_metric(stats.get("gli")),
        "ngrdi": _round_metric(stats.get("ngrdi")),
        "exg": _round_metric(stats.get("exg")),
        "nbi": _round_metric(stats.get("nbi")),
        "variables": {
            "vi": _round_metric(stats.get("vi")),
            "vari": _round_metric(stats.get("vari")),
            "gli": _round_metric(stats.get("gli")),
            "ngrdi": _round_metric(stats.get("ngrdi")),
            "exg": _round_metric(stats.get("exg")),
            "nbi": _round_metric(stats.get("nbi")),
        },
        "bromatologia": (
            {
                "proteina_pct": _broma["proteina_pct"] if _broma else None,
                "energia_mcal": _broma["energia_mcal"] if _broma else None,
                "energia2_mcal": _broma["energia2_mcal"] if _broma else None,
                "fda_pct": _broma["fda_pct"] if _broma else None,
                "fdn_pct": _broma["fdn_pct"] if _broma else None,
                "energia_mj": _broma["energia_mj"] if _broma else None,
                "aforo_ua_ha": _broma["aforo_ua_ha"] if _broma else None,
                "indice_vigor": _broma["indice_vigor"] if _broma else None,
                "en_rango": _broma["en_rango_valido"] if _broma else None,
                "minerales": _broma["minerales"] if _broma else None,
            }
            if _broma
            else None
        ),
        "ndvi_ready": bool(meta.get("processed")),
        "ndvi_stamp": meta.get("stamp"),
        "method": meta.get("method") or "ndvi_approx",
        "visible_method": meta.get("visible_method") or "combined",
        "has_nir": meta.get("has_nir") if meta.get("has_nir") is not None else False,
    }
    payload["nutrients"] = nutrient_payloads
    return jsonify(payload)


@api.route("/analysis-crops", methods=["GET"])
@jwt_required()
def list_analysis_crops():
    """Lista todos los cultivos de análisis registrados.

    :status 200: Lista JSON de cultivos con id, name y description
    """
    crops = AnalysisCrop.query.order_by(AnalysisCrop.name.asc()).all()
    return jsonify([_serialize_analysis_crop(crop) for crop in crops])


@api.route("/analysis-crops", methods=["POST"])
@jwt_required()
@check_permission(required_roles=["administrator", "reseller"])
def create_analysis_crop():
    """Crea un nuevo cultivo de análisis o retorna uno existente.

    Si ya existe un cultivo con el mismo nombre (case-insensitive),
    actualiza su descripción si la nueva es no vacía y la existente
    no estaba definida.

    :status 201: Cultivo creado exitosamente
    :status 200: Cultivo ya existía, retornado con posible update
    :status 400: Nombre vacío o ausente
    """
    data = request.get_json(force=True, silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not name:
        abort(400, description="name is required")
    description = data.get("description")
    query = AnalysisCrop.query.filter(func.lower(AnalysisCrop.name) == name.lower())
    existing = query.first()
    if existing:
        if description and not existing.description:
            existing.description = description
            db.session.commit()
        return jsonify(_serialize_analysis_crop(existing)), 200

    crop = AnalysisCrop(name=name, description=description)
    db.session.add(crop)
    db.session.commit()
    return jsonify(_serialize_analysis_crop(crop)), 201


@api.route("/nutrients", methods=["GET"])
@jwt_required()
def list_nutrients():
    """Lista todos los nutrientes registrados con su categoría.

    :status 200: Lista JSON con id, name, symbol, unit y category
    """
    nutrients = Nutrient.query.order_by(Nutrient.name.asc()).all()
    payload = [
        {
            "id": nutrient.id,
            "name": nutrient.name,
            "symbol": nutrient.symbol,
            "unit": nutrient.unit,
            "category": getattr(nutrient.category, "value", None),
        }
        for nutrient in nutrients
    ]
    return jsonify(payload)


@api.route("/mineral-balance", methods=["POST"])
@jwt_required()
def mineral_balance():
    """Compute the mineral balance table server-side (FRM_Balance port).

    Body:
        order: list[str] — nutrient display order (names).
        targets: dict — reference values (% macros / ppm micros) by name.
        actuals: dict — leaf analysis values by name.
        aforo_objective / aforo_actual: float|None — the objective aforo
            converts the objective row, the actual aforo converts the
            actual row; each falls back to the other when missing.
        protein: float|None — when present, targets are re-derived from
            this protein value using the calibrated regressions, and the
            objective aforo is re-estimated from the same protein, before
            computing the balance.

    Returns:
        JSON with per-nutrient entries (raw, kg/ha, deficit, grade, nano),
        the total requirement, the (possibly derived) targets used and
        the derived objective aforo when protein was provided.
    """
    data = request.get_json(silent=True) or {}
    order = data.get("order")
    targets = data.get("targets")
    actuals = data.get("actuals")
    if not isinstance(order, list) or not all(isinstance(name, str) for name in order):
        abort(400, description="invalid order")
    if not isinstance(targets, dict) or not isinstance(actuals, dict):
        abort(400, description="invalid targets/actuals")

    nutrients = Nutrient.query.order_by(Nutrient.id.asc()).all()

    protein = data.get("protein")
    derived_aforo = None
    if protein is not None:
        try:
            protein_val = float(protein)
        except (TypeError, ValueError):
            abort(400, description="invalid protein")
        if not math.isfinite(protein_val) or protein_val <= 0:
            abort(400, description="invalid protein")
        nitrogen = protein_to_nitrogen(protein_val)
        derived = compute_secondary_objective_targets(protein_val, nitrogen, nutrients)
        for item in derived:
            for key in filter(
                None, [item.get("nutrient_name"), item.get("nutrient_symbol")]
            ):
                if key in targets or key in order:
                    targets[key] = item.get("target_value")
        candidate = aforo_desde_proteina(protein_val)
        if math.isfinite(candidate) and candidate > 0:
            derived_aforo = candidate

    aforo = derived_aforo if derived_aforo is not None else data.get("aforo_objective")
    try:
        aforo_val = float(aforo) if aforo is not None else None
    except (TypeError, ValueError):
        aforo_val = None
    if aforo_val is None or not math.isfinite(aforo_val) or aforo_val <= 0:
        aforo = data.get("aforo_actual")

    result = compute_mineral_balance(
        order,
        targets,
        actuals,
        aforo,
        nutrients,
        aforo_actual=(None if data.get("use_objective_aforo_for_actual") else data.get("aforo_actual")),
    )
    result["targets"] = targets
    result["aforo_objective"] = derived_aforo
    return jsonify(result)


@api.route("/secondary-objectives", methods=["GET"])
@jwt_required()
def list_secondary_objectives():
    """API GET para listar objetivos secundarios (CRUD completo).

    NOTA: Este es el endpoint API principal para operaciones CRUD.
    Para la vista web que renderiza template, ver `agrovista/web_routes.py`.
    """
    objectives = (
        SecondaryObjective.query.options(
            joinedload(SecondaryObjective.analysis_crop),
            selectinload(SecondaryObjective.nutrient_targets).joinedload(
                SecondaryObjectiveNutrient.nutrient
            ),
        )
        .order_by(SecondaryObjective.created_at.desc())
        .all()
    )
    return jsonify([_serialize_secondary_objective(obj) for obj in objectives])


def _resolve_analysis_crop(analysis_crop_id, analysis_crop_name):
    crop = None
    if analysis_crop_id:
        try:
            crop = db.session.get(AnalysisCrop, int(analysis_crop_id))
        except (TypeError, ValueError):
            crop = None
    if crop is None and analysis_crop_name:
        name = str(analysis_crop_name).strip()
        if name:
            crop = AnalysisCrop.query.filter(
                func.lower(AnalysisCrop.name) == name.lower()
            ).first()
            if crop is None:
                crop = AnalysisCrop(name=name)
                db.session.add(crop)
                db.session.flush()
    return crop


def _parse_nutrient_targets(
    payload: Dict[str, object] | None,
    *,
    protein_average: float,
    nitrogen_estimated: float,
) -> Dict[int, float]:
    mapping: Dict[int, float] = {}
    items = []
    if isinstance(payload, dict):
        items = [payload]
    elif isinstance(payload, list):
        items = payload
    for item in items:
        if not isinstance(item, dict):
            continue
        nutrient_id = item.get("nutrient_id")
        value = _as_float(item.get("target_value"))
        if nutrient_id is None or value is None:
            continue
        try:
            mapping[int(nutrient_id)] = value
        except (TypeError, ValueError):
            continue

    nutrients = Nutrient.query.order_by(Nutrient.id.asc()).all()
    defaults = secondary_target_map(
        protein_average,
        nitrogen_estimated,
        nutrients,
    )
    for nutrient_id, value in defaults.items():
        mapping.setdefault(nutrient_id, value)
    return mapping


@api.route("/secondary-objectives", methods=["POST"])
@jwt_required()
@check_permission(required_roles=["administrator", "reseller"])
def create_secondary_objective():
    """API POST para crear objetivos secundarios (CRUD completo)."""
    data = request.get_json(force=True, silent=True) or {}
    protein = _as_float(data.get("protein") or data.get("protein_average"), 0.0)
    nitrogen = _as_float(
        data.get("nitrogen") or data.get("nitrogen_estimated"),
        0.0,
    )
    crop = _resolve_analysis_crop(
        data.get("analysis_crop_id"),
        data.get("analysis_crop_name"),
    )
    if crop is None:
        abort(400, description="analysis crop is required")

    nutrient_payload = data.get("nutrient_targets") or data.get("nutrients")
    nutrient_map = _parse_nutrient_targets(
        nutrient_payload,
        protein_average=protein,
        nitrogen_estimated=nitrogen,
    )

    objective = SecondaryObjective(
        analysis_crop=crop,
        protein_average=protein or 0.0,
        nitrogen_estimated=nitrogen or 0.0,
    )
    for nutrient_id, value in nutrient_map.items():
        objective.nutrient_targets.append(
            SecondaryObjectiveNutrient(
                nutrient_id=nutrient_id,
                target_value=value,
            )
        )

    db.session.add(objective)
    db.session.commit()
    db.session.refresh(objective)
    return jsonify(_serialize_secondary_objective(objective)), 201


@api.route("/secondary-objectives/<int:objective_id>", methods=["GET"])
@jwt_required()
def get_secondary_objective(objective_id: int):
    """Obtiene un objetivo secundario por ID con sus nutrientes.

    :param objective_id: ID del objetivo secundario (vía URL)
    :status 200: JSON con el objetivo y sus nutrient_targets
    :status 404: Objetivo no encontrado
    """
    objective = (
        SecondaryObjective.query.options(
            joinedload(SecondaryObjective.analysis_crop),
            selectinload(SecondaryObjective.nutrient_targets).joinedload(
                SecondaryObjectiveNutrient.nutrient
            ),
        )
        .filter_by(id=objective_id)
        .first()
    )
    if objective is None:
        abort(404, description="secondary objective not found")
    return jsonify(_serialize_secondary_objective(objective))


@api.route("/secondary-objectives/<int:objective_id>", methods=["PUT"])
@jwt_required()
@check_permission(required_roles=["administrator", "reseller"])
def update_secondary_objective(objective_id: int):
    """Actualiza un objetivo secundario existente.

    Permite modificar cultivo, proteína, nitrógeno y nutrient_targets.
    Solo administradores y resellers.

    :param objective_id: ID del objetivo secundario (vía URL)
    :status 200: Objetivo actualizado exitosamente
    :status 404: Objetivo no encontrado
    """
    objective = db.session.get(SecondaryObjective, objective_id)
    if objective is None:
        abort(404, description="secondary objective not found")

    data = request.get_json(force=True, silent=True) or {}

    crop = _resolve_analysis_crop(
        data.get("analysis_crop_id") or objective.analysis_crop_id,
        data.get("analysis_crop_name"),
    )
    if crop is not None:
        objective.analysis_crop = crop

    protein = _as_float(data.get("protein") or data.get("protein_average"))
    nitrogen = _as_float(data.get("nitrogen") or data.get("nitrogen_estimated"))
    if protein is not None:
        objective.protein_average = protein
    if nitrogen is not None:
        objective.nitrogen_estimated = nitrogen

    nutrient_payload = data.get("nutrient_targets") or data.get("nutrients")
    if nutrient_payload is not None:
        nutrient_map = _parse_nutrient_targets(
            nutrient_payload,
            protein_average=objective.protein_average,
            nitrogen_estimated=objective.nitrogen_estimated,
        )
        existing = {target.nutrient_id: target for target in objective.nutrient_targets}
        for nutrient_id, value in nutrient_map.items():
            target = existing.get(nutrient_id)
            if target is None:
                objective.nutrient_targets.append(
                    SecondaryObjectiveNutrient(
                        nutrient_id=nutrient_id,
                        target_value=value,
                    )
                )
            else:
                target.target_value = value

    db.session.commit()
    db.session.refresh(objective)
    return jsonify(_serialize_secondary_objective(objective))


@api.route("/secondary-objectives/<int:objective_id>", methods=["DELETE"])
@jwt_required()
@check_permission(required_roles=["administrator", "reseller"])
def delete_secondary_objective(objective_id: int):
    """Elimina un objetivo secundario (hard delete).

    Solo administradores y resellers.

    :param objective_id: ID del objetivo secundario (vía URL)
    :status 200: Objetivo eliminado exitosamente
    :status 404: Objetivo no encontrado
    """
    objective = db.session.get(SecondaryObjective, objective_id)
    if objective is None:
        abort(404, description="secondary objective not found")
    db.session.delete(objective)
    db.session.commit()
    return jsonify({"status": "deleted", "id": objective_id})


# ---------------------------------------------------------------------------
# CSV download endpoint
# ---------------------------------------------------------------------------


@api.route("/secondary-objectives/csv/download")
@jwt_required()
def download_secondary_objectives_csv():
    """Download CSV of secondary objectives with nutrient targets."""
    handler = CsvHandler()
    nutrient_map = {n.id: n.name for n in Nutrient.query.all()}

    query = SecondaryObjective.query.options(
        joinedload(SecondaryObjective.analysis_crop),
        selectinload(SecondaryObjective.nutrient_targets),
    ).order_by(SecondaryObjective.id.asc())
    objectives = query.all()

    if not objectives:
        csv_data = handler.export_to_csv([])
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={
                "Content-Disposition": "attachment; "
                "filename=secondary_objectives.csv",
            },
        )

    rows = []
    for obj in objectives:
        row = {
            "id": obj.id,
            "analysis_crop_id": obj.analysis_crop_id,
            "analysis_crop_name": (obj.analysis_crop.name if obj.analysis_crop else ""),
            "protein_average": obj.protein_average,
            "nitrogen_estimated": obj.nitrogen_estimated,
            "created_at": str(obj.created_at),
            "updated_at": str(obj.updated_at),
        }
        for target in obj.nutrient_targets:
            row[f"nutrient_{target.nutrient_id}"] = target.target_value or ""
        for nid in sorted(nutrient_map):
            row.setdefault(f"nutrient_{nid}", "")
        rows.append(row)

    csv_data = handler.export_to_csv(rows)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; " "filename=secondary_objectives.csv",
        },
    )


def _get_scoped_common_analysis(common_analysis_id: int) -> CommonAnalysis:
    """Carga un CommonAnalysis validando el alcance organizacional del JWT.

    Args:
        common_analysis_id: ID del análisis común.

    Returns:
        CommonAnalysis: El análisis si existe y el usuario tiene acceso.
    """
    analysis = db.session.get(CommonAnalysis, common_analysis_id)
    if analysis is None:
        abort(404, description="common analysis not found")
    farm = analysis.lot.farm if analysis.lot else None
    if farm is None or not check_resource_access(farm, get_jwt()):
        abort(403, description="forbidden")
    return analysis


@api.route("/lot-snapshot", methods=["POST"])
@jwt_required()
def create_lot_snapshot():
    """Genera y enlaza el snapshot RGB del lote para un análisis común.

    Payload JSON:
        common_analysis_id (int): Análisis al que se ancla el snapshot.
        media_asset_id (int): Asset de media (ortofoto) origen.
        vertices (list[[x, y]]): Polígono en coordenadas raster full-res
            (misma convención que ``/protein`` con ``coords_full_res=True``).

    Returns:
        201 con ``{"variant_id", "url"}`` si el snapshot fue generado.
    """
    data = request.get_json(force=True, silent=False) or {}
    try:
        common_analysis_id = int(data.get("common_analysis_id"))
        media_asset_id = int(data.get("media_asset_id"))
    except (TypeError, ValueError):
        abort(400, description="invalid identifiers")
    vertices = _validate_vertices(data.get("vertices"))

    analysis = _get_scoped_common_analysis(common_analysis_id)

    asset = db.session.get(Asset, media_asset_id)
    if asset is None:
        abort(404, description="media asset not found")

    previous = analysis.lot_snapshot_variant
    try:
        variant = generate_lot_snapshot(asset, vertices)
        analysis.lot_snapshot_variant = variant
        discard_lot_snapshot(previous)
        db.session.commit()
    except LotSnapshotError as e:
        db.session.rollback()
        abort(400, description=str(e))
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "agrovista: lot snapshot generation failed for analysis %s",
            common_analysis_id,
        )
        abort(500, description="snapshot generation failed")

    return (
        jsonify(
            {
                "common_analysis_id": analysis.id,
                "variant_id": variant.id,
                "url": resolve_lot_snapshot_url(analysis),
            }
        ),
        201,
    )


@api.route("/lot-snapshot/<int:common_analysis_id>", methods=["GET"])
@jwt_required()
def get_lot_snapshot(common_analysis_id: int):
    """Resuelve la URL del snapshot de lote de un análisis común.

    Returns:
        200 con ``{"url"}`` si existe; 404 si el análisis no tiene snapshot
        (la UI lo trata como "no mostrar nada").
    """
    analysis = _get_scoped_common_analysis(common_analysis_id)
    url = resolve_lot_snapshot_url(analysis)
    if not url:
        abort(404, description="snapshot not available")
    return jsonify({"common_analysis_id": analysis.id, "url": url}), 200
