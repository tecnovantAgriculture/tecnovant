"""API routes for generating foliage analysis reports."""

import re
from datetime import datetime

from flask import jsonify, request, send_file
from flask_jwt_extended import get_jwt, jwt_required

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
    NutrientApplication,
    Objective,
    Production,
    Recommendation,
    SoilAnalysis,
    leaf_analysis_nutrients,
)

from . import foliage_report_api as api
from .controller import (
    DeleteRecommendationView,
    FollowUpComparisonView,
    FollowUpView,
    LotEvolutionView,
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

# Rutas del sistema de seguimiento post-aplicación (fase 5)
follow_up_view = FollowUpView.as_view("follow_up")
api.add_url_rule(
    "/applications/<int:application_id>/follow-up",
    view_func=follow_up_view,
    methods=["GET", "POST"],
)

follow_up_comparison_view = FollowUpComparisonView.as_view("follow_up_comparison")
api.add_url_rule(
    "/follow-up/<int:follow_up_id>/comparison",
    view_func=follow_up_comparison_view,
    methods=["GET"],
)

lot_evolution_view = LotEvolutionView.as_view("lot_evolution")
api.add_url_rule(
    "/lots/<int:lot_id>/evolution",
    view_func=lot_evolution_view,
    methods=["GET"],
)


@api.route("/get-farms")
@login_required
def get_farms():
    """Lista las fincas accesibles para el usuario autenticado.

    Filtra por alcance multi-tenant: solo retorna fincas cuyas
    organizaciones están asociadas al usuario.

    :status 200: Lista JSON con id y name de cada finca
    """
    claims = get_jwt()

    # Obtener todas las fincas que el usuario puede visualizar
    farms = (
        Farm.query.join(Organization).filter(check_resource_access(Farm, claims)).all()
    )

    return jsonify([{"id": farm.id, "name": farm.name} for farm in farms])


@api.route("/get-lots/")
@login_required
def get_lots():
    """Lista los lotes de una finca con su cultivo activo.

    Retorna cada lote con el crop_id del LotCrop más reciente,
    útil para precargar el cultivo en formularios de informe.

    :param farm_id: ID de la finca (requerido, query string)
    :status 200: Lista JSON con id, name y crop_id de cada lote
    :status 403: Usuario sin acceso a la finca
    :status 404: Finca no encontrada
    """
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
    """Lista los objetivos nutricionales asociados a un cultivo.

    :param crop_id: ID del cultivo (vía URL)
    :status 200: Lista JSON con id, name y target_value de cada objetivo
    :status 404: Cultivo no encontrado
    """
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
    """Lista los análisis comunes con datos de suelo y foliar.

    Filtra opcionalmente por finca, lote y rango de fechas.
    Incluye nutrientes foliares con sus valores para cada análisis.

    :param farm_id: ID de finca para filtrar (opcional)
    :param lot_id: ID de lote para filtrar (opcional)
    :param start_date: Fecha inicial YYYY-MM-DD (opcional)
    :param end_date: Fecha final YYYY-MM-DD (opcional)
    :status 200: Lista JSON con análisis y nutrientes
    :status 400: Formato de fecha inválido
    """
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
            "protein": common_analysis.protein,
            "yield_estimate": common_analysis.yield_estimate,
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


# ===== DOCX Export Endpoint =====
@api.route("/<int:id>/export/docx")
@jwt_required()
def export_report_docx(id):
    """Generate and stream the Word version of a Recommendation report.

    The DOCX mirrors the on-screen PDF page-for-page: cover, summary
    (Law of the Minimum), foliar detail, macro/micro nutrient pages
    with charts, soil, recommendations, and historical evolution.
    Charts are rendered server-side with matplotlib using the same
    data the web dashboard already consumes via ReportView.

    Multi-tenant isolation: the recommendation's lot must belong to
    an organization the caller can access (mirrors the pattern in
    ``get_recommendation_results``).
    """
    rec = Recommendation.query.get_or_404(id)
    lot = Lot.query.get_or_404(rec.lot_id) if rec.lot_id else None
    if not lot:
        return jsonify({"error": "Lot not found"}), 404

    claims = get_jwt()
    if not check_resource_access(lot.farm, claims):
        return jsonify({"error": "Forbidden"}), 403

    from .services.docx_export import build_report_docx_bytes  # lazy import

    buf = build_report_docx_bytes(id)

    safe_lote = (
        re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ ]", "", lot.name or "").strip() or "lote"
    )
    filename = f"informe_{safe_lote}_{datetime.now().strftime('%Y-%m-%d')}.docx"

    return send_file(
        buf,
        mimetype=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        as_attachment=True,
        download_name=filename,
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
