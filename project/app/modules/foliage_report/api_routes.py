"""API routes for generating foliage analysis reports."""

from datetime import datetime

from flask import jsonify, request
from flask_jwt_extended import get_jwt

from app.core.controller import (
    api_login_required,
    check_resource_access,
    login_required,
)
from app.core.models import Organization
from app.extensions import db
from app.modules.foliage.models import (
    CommonAnalysis,
    Crop,
    Farm,
    LeafAnalysis,
    Lot,
    LotCrop,
    Nutrient,
    Objective,
    Production,
    Recommendation,
    SoilAnalysis,
    leaf_analysis_nutrients,
)

from . import foliage_report_api as api
from .controller import (
    DeleteRecommendationView,
    RecommendationFilterView,
    RecommendationGenerator,
    RecommendationView,
    ReportView,
)
from .helpers import determinar_coeficientes_variacion

report_view = ReportView.as_view("report_view")
api.add_url_rule("/report/<int:id>", view_func=report_view, methods=["GET"])

report_generator_view = RecommendationGenerator.as_view("generate_report")
api.add_url_rule("/generate", view_func=report_generator_view, methods=["POST"])

report_filter_view = RecommendationFilterView.as_view("get_filtered_reports")
api.add_url_rule("/get_filtered_reports", view_func=report_filter_view, methods=["GET"])

# Registrar la ruta en tu API
delete_report_view = DeleteRecommendationView.as_view("delete_report")
api.add_url_rule(
    "/delete_report/<int:report_id>", view_func=delete_report_view, methods=["DELETE"]
)


@api.route("/get-farms")
@login_required
def get_farms():
    claims = get_jwt()

    # Obtener todas las fincas que el usuario puede visualizar
    farms = (
        Farm.query.join(Organization).filter(check_resource_access(Farm, claims)).all()
    )

    return jsonify([{"id": farm.id, "name": farm.name} for farm in farms])


@api.route("/get-lots/")
@login_required
def get_lots():
    claims = get_jwt()
    farm_id = request.args.get("farm_id")
    farm = Farm.query.get_or_404(farm_id)

    # Verificar si el usuario tiene acceso a esta finca
    if not check_resource_access(farm, claims):
        return jsonify({"error": "No tienes acceso a esta finca"}), 403

    lots = Lot.query.filter_by(farm_id=farm_id).all()

    lots_data = []
    for lot in lots:
        # Find the most recent active LotCrop for this lot
        # Order by end_date descending (None means active), then start_date descending
        # lot_crop = db.session.query(LotCrop).\
        #     filter(LotCrop.lot_id == lot.id).\
        #     order_by(LotCrop.end_date.desc().nullsfirst(), LotCrop.start_date.desc()).first()

        lot_crop = (
            db.session.query(LotCrop)
            .filter(LotCrop.lot_id == lot.id)
            .order_by(LotCrop.end_date.desc(), LotCrop.start_date.desc())
            .first()
        )

        # return jsonify([
        #     {'id': lot.id, 'name': lot.name}
        #     for lot in lots
        # ])

        # lot_crop = db.session.query(LotCrop).\
        #     filter(LotCrop.lot_id == lot.id).\
        #     order_by(LotCrop.end_date.desc().nullsfirst(), LotCrop.start_date.desc()).limit(1).first()

        current_crop_id = lot_crop.crop_id if lot_crop else None
        lots_data.append({"id": lot.id, "name": lot.name, "crop_id": current_crop_id})
    return jsonify(lots_data)


@api.route("/get-objectives-for-crop/<int:crop_id>")
@login_required
def get_objectives_for_crop(crop_id):
    crop = Crop.query.get_or_404(crop_id)
    objectives = Objective.query.filter_by(crop_id=crop_id).all()
    objectives_data = [
        {
            "cultivo": crop.name,
            "id": obj.id,
            "name": f"ID: {obj.id} - Target: {obj.target_value}",
        }
        for obj in objectives
    ]
    return jsonify(objectives_data)


@api.route("/get-objectives")
@login_required
def get_all_objectives():
    """Return a list of all objectives with their crop names."""
    objectives = Objective.query.all()
    data = [
        {
            "cultivo": obj.crop.name,
            "crop_id": obj.crop_id,
            "id": obj.id,
            "name": f"ID: {obj.id} - Target: {obj.target_value}",
        }
        for obj in objectives
    ]
    return jsonify(data)


@api.route("/analyses")
@login_required
def get_analyses():
    claims = get_jwt()
    farm_id = request.args.get("farm_id")
    lot_id = request.args.get("lot_id")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    # Construir la query con relaciones eager loading
    query = CommonAnalysis.query.options(
        db.joinedload(CommonAnalysis.soil_analysis),
        db.joinedload(CommonAnalysis.leaf_analysis),
        db.joinedload(CommonAnalysis.lot).joinedload(Lot.farm),
    )

    # Aplicar filtros
    if farm_id:
        query = query.filter(CommonAnalysis.lot.has(Lot.farm_id == farm_id))

    if lot_id:
        query = query.filter(CommonAnalysis.lot_id == lot_id)

    if start_date and end_date:
        try:
            start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
            query = query.filter(CommonAnalysis.date.between(start_date, end_date))
        except ValueError:
            return jsonify({"error": "Formato de fecha incorrecto"}), 400

    # Obtener resultados
    common_analyses = query.all()

    # Preparar la respuesta
    analyses = []
    for common_analysis in common_analyses:
        soil_analysis = common_analysis.soil_analysis
        leaf_analysis = common_analysis.leaf_analysis

        # Procesar los nutrientes del análisis foliar
        leaf_nutrients = []
        if leaf_analysis:
            # Consultar los nutrientes y sus valores asociados a esta LeafAnalysis
            nutrient_entries = (
                db.session.query(Nutrient, leaf_analysis_nutrients.c.value)
                .join(
                    leaf_analysis_nutrients,
                    Nutrient.id == leaf_analysis_nutrients.c.nutrient_id,
                )
                .filter(leaf_analysis_nutrients.c.leaf_analysis_id == leaf_analysis.id)
                .order_by(Nutrient.id)
                .all()
            )

            for nutrient, value in nutrient_entries:
                leaf_nutrients.append(
                    {
                        "nutrient_id": nutrient.id,
                        "value": value,
                        "nutrient_name": nutrient.name,
                    }
                )

        analysis_data = {
            "id": common_analysis.id,
            "date": common_analysis.date.strftime("%Y-%m-%d"),
            "lot": {
                "id": common_analysis.lot.id,
                "name": common_analysis.lot.name,
                "farm": {
                    "id": common_analysis.lot.farm.id,
                    "name": common_analysis.lot.farm.name,
                },
            },
            "soil_analysis": {
                "energy": soil_analysis.energy if soil_analysis else None,
                "grazing": soil_analysis.grazing if soil_analysis else None,
            },
            "leaf_analysis": {"nutrients": leaf_nutrients},
        }
        analyses.append(analysis_data)

    return jsonify(analyses)


@api.route("/cv-nutrients")
@login_required
def get_cv_nutrients():
    """Return coefficient of variation values stored for nutrients."""

    lot_id = request.args.get("lot_id", type=int)
    if not lot_id:
        return jsonify({"error": "lot_id es requerido"}), 400

    lot = Lot.query.get_or_404(lot_id)
    claims = get_jwt()
    if not check_resource_access(lot.farm, claims):
        return jsonify({"error": "No tienes acceso a este lote"}), 403

    coeficientes = determinar_coeficientes_variacion(lot_id)
    data = {
        name: float(value) if value is not None else None
        for name, value in coeficientes.items()
    }

    return jsonify(data)


# ===== Recommendation Results Endpoint =====
@api.route("/recommendations/<int:recommendation_id>/results")
@api_login_required
def get_recommendation_results(recommendation_id):
    """
    Retorna los resultados de una recomendación: producción real vs objetivo.

    Returns:
        200: Datos de resultados (incluso si production/objective son null)
        403: Usuario no tiene acceso al lote
        404: Recomendación no existe
    """
    # 1. Obtener recomendación
    rec = Recommendation.query.get_or_404(recommendation_id)

    # 2. Validar acceso (org isolation)
    lot = Lot.query.get_or_404(rec.lot_id) if rec.lot_id else None
    if not lot:
        return jsonify({"error": "Lot not found"}), 404

    claims = get_jwt()
    if not check_resource_access(lot.farm, claims):
        return jsonify({"error": "Forbidden"}), 403

    # 3. Obtener producción más reciente del mismo lote
    prod = (
        Production.query.filter_by(lot_id=rec.lot_id)
        .order_by(Production.date.desc())
        .first()
    )

    # 4. Obtener objetivo de producción del cultivo
    obj = None
    if rec.crop_id:
        obj = Objective.query.filter_by(crop_id=rec.crop_id).first()

    # 5. Calcular resumen
    result_summary = _calculate_result_summary(prod, obj)

    return (
        jsonify(
            {
                "success": True,
                "recommendation": {
                    "id": rec.id,
                    "lot_id": rec.lot_id,
                    "crop_id": rec.crop_id,
                    "date": rec.date.isoformat() if rec.date else None,
                    "title": rec.title,
                    "applied": rec.applied if hasattr(rec, "applied") else None,
                    "automatic_recommendations": (
                        rec.automatic_recommendations
                        if hasattr(rec, "automatic_recommendations")
                        else None
                    ),
                    "text_recommendations": (
                        rec.text_recommendations
                        if hasattr(rec, "text_recommendations")
                        else None
                    ),
                },
                "production": (
                    {
                        "id": prod.id,
                        "lot_id": prod.lot_id,
                        "date": prod.date.isoformat() if prod.date else None,
                        "production_kg": prod.production_kg,
                        "bags": prod.bags,
                        "price_per_kg": prod.price_per_kg,
                    }
                    if prod
                    else None
                ),
                "objective": (
                    {
                        "id": obj.id,
                        "crop_id": obj.crop_id,
                        "target_value": obj.target_value,
                    }
                    if obj
                    else None
                ),
                "result_summary": result_summary,
                "roi": {
                    "cost_estimated": None,
                    "benefit_estimated": None,
                    "note": "ROI económico disponible en fase futura (requiere datos de costo)",
                },
            }
        ),
        200,
    )


def _calculate_result_summary(prod, obj):
    """Calcula el resumen de resultado de la recomendación."""
    if prod is None:
        return {
            "status": "PENDING_PRODUCTION",
            "status_text": "Producción no registrada aún",
            "actual_kg": None,
            "target_kg": obj.target_value if obj else None,
            "delta_kg": None,
            "delta_pct": None,
            "success": None,
        }

    actual = prod.production_kg
    target = obj.target_value if obj else None
    delta_kg = (actual - target) if target is not None else None
    delta_pct = ((delta_kg / target) * 100) if (target and target != 0) else None
    success = (delta_kg >= 0) if delta_kg is not None else None

    return {
        "status": (
            "SUCCESS" if success else ("FAILED" if success is False else "NO_TARGET")
        ),
        "status_text": (
            ("✅ EXITOSA" if success else "⚠️ NO CUMPLIDA")
            if success is not None
            else "Sin objetivo definido"
        ),
        "actual_kg": actual,
        "target_kg": target,
        "delta_kg": round(delta_kg, 2) if delta_kg is not None else None,
        "delta_pct": round(delta_pct, 2) if delta_pct is not None else None,
        "success": success,
    }


# @api.route("/cv-nutrients")
# @login_required
# def get_cv_nutrients():
#     """Return coefficient of variation for nutrients on a lot."""
#     lot_id = request.args.get("lot_id", type=int)
#     if not lot_id:
#         return jsonify({"error": "lot_id es requerido"}), 400

#     lot = Lot.query.get_or_404(lot_id)
#     claims = get_jwt()
#     if not check_resource_access(lot.farm, claims):
#         return jsonify({"error": "No tienes acceso a este lote"}), 403

#     coeficientes = determinar_coeficientes_variacion(lot_id)
#     data = {name: float(value) for name, value in coeficientes.items()}
#     return jsonify(data)
