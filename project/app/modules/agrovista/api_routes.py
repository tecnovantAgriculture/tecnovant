import math
from pathlib import Path
from typing import Dict, Optional

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload

from flask import abort, current_app, jsonify, request, send_file
from flask_jwt_extended import jwt_required

from app.extensions import db
from app.modules.foliage.models import Nutrient
from app.modules.media.helpers import (
    PreprocessConfig,
    _media_root,
    preprocess_rgb_once,
    visible_indices,
    combine_indices,
    srgb_to_linear,
)
from app.modules.media.models import Asset, StorageLocation
from app.modules.media.tasks import _resolve_cache_dir
from pyproj import Transformer
import io
import zipfile
from rasterio.transform import Affine, xy

from . import agrovista_api as api
from .controller import ensure_processed, process_upload
from .helpers import (
    average_protein,
    compute_secondary_objective_targets,
    polygon_mask,
    protein_to_nitrogen,
    secondary_target_map,
)
from .models import (
    AnalysisCrop,
    NDVIImage,
    SecondaryObjective,
    SecondaryObjectiveNutrient,
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


def _resolve_media_cache(asset: Asset) -> Optional[Path]:
    """Garantiza la existencia del NPZ de caché para un asset de media."""

    app = current_app._get_current_object()
    cache_dir = _resolve_cache_dir(app, asset.uuid)
    npz_path = cache_dir / f"{asset.uuid}__rgb_preproc_linear.npz"
    if npz_path.exists():
        return npz_path

    try:
        media_root = Path(_media_root())
    except Exception:
        return None
    source_path = media_root / asset.storage_key
    if not source_path.exists():
        return None

    cfg = PreprocessConfig(
        cache_dir=cache_dir,
        preview_max_dim=int(app.config.get("MEDIA_PREVIEW_MAX_DIM", 2048)),
    )
    try:
        preprocess_rgb_once(source_path, cfg)
    except Exception:
        current_app.logger.exception("agrovista: media cache warmup failed for %s", asset.uuid)
        return None

    return npz_path if npz_path.exists() else None


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
    """Calcula proteína y variables usando la caché de Media (NPZ + preview)."""

    asset = _find_media_asset(media_asset_id, img_id)
    if asset is None:
        abort(404, description="asset not found")
    if asset.storage != StorageLocation.LOCAL.value:
        abort(400, description="unsupported storage for media asset")
    if not asset.crs or not asset.transform:
        abort(400, description="asset lacks georeference")

    cache_dir = _resolve_cache_dir(current_app._get_current_object(), asset.uuid)
    npz_path = _resolve_media_cache(asset)
    rgb = None

    # Prefer el NPZ exacto (full res); si falta, usar preview PNG como respaldo.
    if npz_path and npz_path.exists():
        try:
            rgb = np.load(npz_path, mmap_mode="r", allow_pickle=False)["rgb"]
        except Exception:
            current_app.logger.exception("agrovista: unable to read media cache npz for %s", asset.uuid)
            rgb = None

    if rgb is None:
        preview_path = cache_dir / f"{asset.uuid}__rgb_preproc_preview.png"
        if not preview_path.exists():
            abort(500, description="media cache unavailable")
        try:
            from PIL import Image

            with Image.open(preview_path) as img:
                rgb_srgb = np.array(img.convert("RGB"), dtype=np.float32) / 255.0
            rgb = srgb_to_linear(rgb_srgb)
        except Exception:
            current_app.logger.exception("agrovista: failed to read preview for %s", asset.uuid)
            abort(500, description="unable to read media cache")

    height_full, width_full = rgb.shape[:2]

    # Si el frontend ya envía coordenadas en la resolución completa, úsalo sin reescalar
    if coords_full_res:
        scaled_vertices = [(float(x), float(y)) for x, y in vertices]
    else:
        # Escala vértices desde coords de preview a resolución completa, manteniendo centros
        pw = preview_width or width_full_hint or width_full
        ph = preview_height or height_full_hint or height_full
        sx = float(scale_x_hint) if scale_x_hint else ((width_full / pw) if pw else 1.0)
        sy = float(scale_y_hint) if scale_y_hint else ((height_full / ph) if ph else 1.0)
        scaled_vertices = [(float(x) * sx, float(y) * sy) for x, y in vertices]

    xs = [p[0] for p in scaled_vertices]
    ys = [p[1] for p in scaled_vertices]
    x0 = max(0, int(math.floor(min(xs))))
    x1 = min(width_full, int(math.ceil(max(xs))))
    y0 = max(0, int(math.floor(min(ys))))
    y1 = min(height_full, int(math.ceil(max(ys))))
    if x1 <= x0 or y1 <= y0:
        abort(400, description="invalid area")

    crop_shape = (y1 - y0, x1 - x0)
    shifted_vertices = [(x - x0, y - y0) for x, y in scaled_vertices]
    mask = polygon_mask(crop_shape, shifted_vertices)
    rgb = rgb[y0:y1, x0:x1, :]

    idx = visible_indices(rgb)
    vm_raw = (visible_method or "").strip().lower()
    vm = vm_raw if vm_raw in {"combined", "vari", "gli", "ngrdi", "exg"} else "combined"
    try:
        ndvi = combine_indices(idx, method=vm)
    except Exception:
        current_app.logger.warning("agrovista: combine_indices fallback to combined for %s", asset.uuid)
        ndvi = combine_indices(idx, method="combined")
        vm = "combined"

    avg = average_protein(ndvi, mask, min_count=5)
    if math.isnan(avg):
        abort(400, description="invalid area")
    nitrogen = protein_to_nitrogen(avg)

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
    }

    nutrient_records = Nutrient.query.order_by(Nutrient.id.asc()).all()
    nutrient_payloads = compute_secondary_objective_targets(
        avg,
        nitrogen,
        nutrient_records,
    )

    payload = {
        "protein": round(avg, 2),
        "nitrogen": round(nitrogen, 2) if math.isfinite(nitrogen) else None,
        "vi": _round_metric(stats.get("vi")),
        "vari": _round_metric(stats.get("vari")),
        "gli": _round_metric(stats.get("gli")),
        "ngrdi": _round_metric(stats.get("ngrdi")),
        "exg": _round_metric(stats.get("exg")),
        "variables": {
            "vi": _round_metric(stats.get("vi")),
            "vari": _round_metric(stats.get("vari")),
            "gli": _round_metric(stats.get("gli")),
            "ngrdi": _round_metric(stats.get("ngrdi")),
            "exg": _round_metric(stats.get("exg")),
        },
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


@api.route("/polygon-kmz", methods=["POST"])
@jwt_required()
def polygon_kmz():
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
        "nutrient_targets": [
            _serialize_nutrient_target(target) for target in targets
        ],
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
def upload():
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
    avg = average_protein(ndvi, mask)
    if math.isnan(avg):
        abort(400, description="invalid area")
    nitrogen = protein_to_nitrogen(avg)

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
    for key, name in (("vari", "vari"), ("gli", "gli"), ("ngrdi", "ngrdi"), ("exg", "exg")):
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

    nutrient_records = Nutrient.query.order_by(Nutrient.id.asc()).all()
    nutrient_payloads = compute_secondary_objective_targets(
        avg,
        nitrogen,
        nutrient_records,
    )

    payload = {
        "protein": round(avg, 2),
        "nitrogen": round(nitrogen, 2) if math.isfinite(nitrogen) else None,
        "vi": _round_metric(stats.get("vi")),
        "vari": _round_metric(stats.get("vari")),
        "gli": _round_metric(stats.get("gli")),
        "ngrdi": _round_metric(stats.get("ngrdi")),
        "exg": _round_metric(stats.get("exg")),
        "variables": {
            "vi": _round_metric(stats.get("vi")),
            "vari": _round_metric(stats.get("vari")),
            "gli": _round_metric(stats.get("gli")),
            "ngrdi": _round_metric(stats.get("ngrdi")),
            "exg": _round_metric(stats.get("exg")),
        },
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
    crops = AnalysisCrop.query.order_by(AnalysisCrop.name.asc()).all()
    return jsonify([_serialize_analysis_crop(crop) for crop in crops])


@api.route("/analysis-crops", methods=["POST"])
@jwt_required()
def create_analysis_crop():
    data = request.get_json(force=True, silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not name:
        abort(400, description="name is required")
    description = data.get("description")
    query = AnalysisCrop.query.filter(
        func.lower(AnalysisCrop.name) == name.lower()
    )
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
            crop = (
                AnalysisCrop.query.filter(
                    func.lower(AnalysisCrop.name) == name.lower()
                )
                .first()
            )
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
def update_secondary_objective(objective_id: int):
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
    nitrogen = _as_float(
        data.get("nitrogen") or data.get("nitrogen_estimated")
    )
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
        existing = {
            target.nutrient_id: target
            for target in objective.nutrient_targets
        }
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
def delete_secondary_objective(objective_id: int):
    objective = db.session.get(SecondaryObjective, objective_id)
    if objective is None:
        abort(404, description="secondary objective not found")
    db.session.delete(objective)
    db.session.commit()
    return jsonify({"status": "deleted", "id": objective_id})
