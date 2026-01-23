"""Consolidated API routes prioritizing agrovista endpoints."""

import math
from pathlib import Path
from typing import Dict

import numpy as np
from flask import abort, jsonify, request, send_file
from flask_jwt_extended import jwt_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload

from app.core.controller import login_required
from app.extensions import db
from app.modules.foliage.models import Nutrient

from . import agro_engine_api as api
from .controller import ensure_processed, load_ndvi, process_upload, MediaController
from .helpers import (
    average_protein,
    compute_secondary_objective_targets,
    polygon_mask,
    protein_to_nitrogen,
    secondary_target_map,
)
from .models import (
    AnalysisCrop,
    Asset,
    NDVIImage,
    SecondaryObjective,
    SecondaryObjectiveNutrient,
)


# ==================== Agrovista API Routes (Priority) ====================

def _validate_id(value: str) -> str:
    if not value or not value.isalnum():
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
    """Upload and process NDVI image (agrovista priority)."""
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
    """Get NDVI image PNG."""
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
    """Compute protein and nutrient targets from polygon selection."""
    data = request.get_json(force=True, silent=False) or {}
    img_id = _validate_id(str(data.get("id", "")))
    vertices = _validate_vertices(data.get("vertices", []))
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

    def _round_metric(value: float | None) -> float | None:
        if value is None or not math.isfinite(value):
            return None
        return round(value, 3)

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
    """List all analysis crops."""
    crops = AnalysisCrop.query.order_by(AnalysisCrop.name.asc()).all()
    return jsonify([_serialize_analysis_crop(crop) for crop in crops])


@api.route("/analysis-crops", methods=["POST"])
@jwt_required()
def create_analysis_crop():
    """Create a new analysis crop."""
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
    """List all nutrients."""
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
    """List all secondary objectives."""
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
    """Create a new secondary objective."""
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
    """Get a specific secondary objective."""
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
    """Update a secondary objective."""
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
    """Delete a secondary objective."""
    objective = db.session.get(SecondaryObjective, objective_id)
    if objective is None:
        abort(404, description="secondary objective not found")
    db.session.delete(objective)
    db.session.commit()
    return jsonify({"status": "deleted", "id": objective_id})


# ==================== Media API Routes ====================

@api.route("/ping", methods=["GET"])
def ping():
    """Health check endpoint."""
    return jsonify(message="pong from agro_engine API")


@api.route("/assets", methods=["GET"])
@login_required
def list_assets():
    """List all media assets."""
    from sqlalchemy.orm import selectinload
    items = (
        Asset.query.options(selectinload(Asset.variants))
        .order_by(Asset.created_at.desc())
        .all()
    )

    def to_dict(asset: Asset):
        return {
            "id": asset.id,
            "uuid": asset.uuid,
            "original_name": asset.original_name,
            "ext": asset.ext,
            "mime": asset.mime,
            "asset_type": asset.asset_type,
            "storage": asset.storage,
            "storage_key": asset.storage_key,
            "size_bytes": asset.size_bytes,
            "width": asset.width,
            "height": asset.height,
            "is_geo": asset.is_geo,
            "created_at": asset.created_at.isoformat(),
            "variants": [
                {
                    "kind": variant.kind,
                    "storage": variant.storage,
                    "storage_key": variant.storage_key,
                    "width": variant.width,
                    "height": variant.height,
                }
                for variant in asset.variants
            ],
        }

    return jsonify([to_dict(x) for x in items]), 200


@api.route("/assets/upload", methods=["POST"])
@login_required
def upload_local_api():
    """Upload a media asset."""
    if "file" not in request.files:
        return jsonify({"message": "No file part"}), 400
    file = request.files["file"]
    try:
        ctrl = MediaController()
        asset, created = ctrl.save_local_upload(file)
        status = 201 if created else 200
        return (
            jsonify(
                {
                    "message": "Uploaded" if created else "Asset already existed",
                    "asset_id": asset.id,
                    "uuid": asset.uuid,
                    "storage_key": asset.storage_key,
                    "created": created,
                }
            ),
            status,
        )
    except ValueError as e:
        return jsonify({"message": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Upload failed"}), 500


@api.route("/assets/<int:asset_id>", methods=["DELETE"])
@login_required
def delete_asset(asset_id: int):
    """Delete a media asset."""
    try:
        ctrl = MediaController()
        ok = ctrl.delete_asset(asset_id)
        if not ok:
            return jsonify({"message": "Asset not found"}), 404
        return jsonify({"message": "Deleted"}), 200
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Delete failed"}), 500
