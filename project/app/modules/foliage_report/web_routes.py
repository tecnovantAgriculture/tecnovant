"""📃 Rutas web del módulo Foliage Report (reportes nutricionales)

CONVENCIÓN DE DECORADORES DE AUTENTICACIÓN:
- @login_required: Para rutas web estándar (redirige a login si no autenticado)
- @jwt_required(): Para rutas que requieren validación JWT explícita
- @api_login_required: Para rutas API que devuelven JSON 401 (no redirección)

Este módulo usa principalmente @login_required, con @jwt_required() para
endpoints específicos que requieren validación JWT explícita (ej: vista_reporte).
"""

import json
from decimal import Decimal
from types import SimpleNamespace

from flask import current_app, render_template, request, url_for
from flask_jwt_extended import get_jwt, jwt_required
from werkzeug.exceptions import Forbidden

from app.core.controller import check_resource_access, login_required
from app.extensions import db
from app.helpers.dashboard_helpers import get_dashboard_menu
from app.modules.agrovista.helpers import compute_mineral_balance
from app.modules.agrovista.services.lot_snapshot import resolve_lot_snapshot_url
from app.modules.foliage.models import (
    CommonAnalysis,
    Crop,
    Farm,
    Lot,
    LotCrop,
    Nutrient,
    ProductPrice,
    Recommendation,
)

from . import foliage_report as web
from .controller import ReportView
from .helpers import (
    LeafAnalysisResource,
    NutrientOptimizer,
    ObjectiveResource,
    calcular_cv_nutriente,
    compute_nano_dose_rows,
    contribuciones_de_producto,
    determinar_coeficientes_variacion,
    precios_de_producto,
)
from .models import RecommendationDose


@web.route("/listar_reportes/")
@login_required
def listar_reportes():
    """Página: Listado paginado de informes de recomendación generados.

    Filtra por finca y lote vía query params. Aplica multi-tenant:
    solo muestra reportes cuyas fincas pertenecen a organizaciones
    del usuario autenticado.

    :param farm_id: ID de finca para filtrar (opcional, int)
    :param lot_id: ID de lote para filtrar (opcional, int)
    :param page: Número de página, default 1
    :param per_page: Items por página, default 50, max 100
    :status 200: Listado de informes con paginación
    """
    claims = get_jwt()
    user_role = claims.get("rol")

    # Obtener parámetros de filtro de la URL
    farm_id = request.args.get("farm_id", type=int)
    lot_id = request.args.get("lot_id", type=int)
    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get("per_page", default=50, type=int)

    # Validar parámetros de paginación
    if page < 1:
        page = 1
    if per_page < 1 or per_page > 100:
        per_page = 10

    context = {
        "dashboard": True,
        "title": "Informes de Análisis",
        "description": "Listado de informes generados.",
        "author": "Johnny De Castro",
        "site_title": "Listado de Informes",
        "data_menu": get_dashboard_menu(),
        "entity_name": "Reportes",
        "entity_name_lower": "reporte",
        "selected_farm_id": farm_id,  # Para mantener la selección
        "selected_lot_id": lot_id,  # Para mantener la selección
    }

    # Query base
    query = (
        Recommendation.query.options(
            db.joinedload(Recommendation.lot)
            .joinedload(Lot.farm)
            .joinedload(Farm.organization),
            db.joinedload(Recommendation.crop),
        )
        .filter(Recommendation.active == True)
        .order_by(Recommendation.id.asc())
    )

    # APLICAR FILTROS AQUÍ
    if lot_id:
        # Si se especifica un lote, filtrar por ese lote específico
        query = query.filter(Recommendation.lot_id == lot_id)
    elif farm_id:
        # Si solo se especifica finca, filtrar por todos los lotes de esa finca
        query = query.join(Lot).filter(Lot.farm_id == farm_id)

    accessible_recommendations = []
    all_recommendations = query.all()

    for rec in all_recommendations:
        if check_resource_access(rec.lot.farm, claims):
            accessible_recommendations.append(rec)

    # El crop solo se muestra si el lote realmente lo tiene asociado
    # (LotCrop). Los reportes de comparación agrovista usan un crop "host"
    # para el objetivo temporal que no debe aparecer en el listado.
    lot_ids = {rec.lot_id for rec in accessible_recommendations}
    lot_crop_pairs = set()
    if lot_ids:
        lot_crop_pairs = set(
            db.session.query(LotCrop.lot_id, LotCrop.crop_id)
            .filter(LotCrop.lot_id.in_(lot_ids))
            .all()
        )

    # Serializar solo los datos necesarios para la tabla
    items_list = []
    for rec in accessible_recommendations:
        items_list.append(
            {
                "id": rec.id,
                "title": rec.title,
                "finca_lote": (
                    f"{rec.lot.farm.name} / {rec.lot.name}"
                    if rec.lot and rec.lot.farm
                    else "N/A"
                ),
                "crop": (
                    rec.crop.name
                    if rec.crop and (rec.lot_id, rec.crop_id) in lot_crop_pairs
                    else ""
                ),
                "date": rec.date.strftime("%Y-%m-%d") if rec.date else "N/A",
                "autor": rec.author or "Sistema",
            }
        )

    total_informes = len(items_list)

    # Paginación manual sobre la lista ya filtrada por acceso
    pages = (total_informes + per_page - 1) // per_page if per_page > 0 else 0
    if page > pages and pages > 0:
        page = pages
    start = (page - 1) * per_page
    end = start + per_page
    paginated_items = items_list[start:end]

    pagination = SimpleNamespace(
        page=page,
        pages=pages,
        total=total_informes,
        per_page=per_page,
        has_prev=page > 1,
        has_next=page < pages,
        prev_num=page - 1 if page > 1 else 1,
        next_num=page + 1 if page < pages else pages,
    )

    return render_template(
        "listar_reportes.j2",
        **context,
        request=request,
        total_informes=total_informes,
        items=paginated_items,
        pagination=pagination,
    )


# desarrollo temporal.
from datetime import datetime, timedelta


def calculate_trends(historical_data):
    trends = {}

    # Guardia: si no hay datos históricos, retornar vacío
    if not historical_data:
        return trends

    # Convertir las fechas a objetos datetime
    for entry in historical_data:
        entry["fecha"] = datetime.strptime(entry["fecha"], "%b %Y")

    # Ordenar los datos por fecha
    historical_data.sort(key=lambda x: x["fecha"])

    # Calcular las tendencias para cada componente
    for nutrient in historical_data[0].keys():
        if nutrient != "fecha":
            values = [entry[nutrient] for entry in historical_data]
            dates = [entry["fecha"] for entry in historical_data]

            if len(values) > 1:
                initial_value = values[0]
                final_value = values[-1]
                time_diff = dates[-1] - dates[0]

                if time_diff.days > 0:
                    if initial_value != 0:
                        percentage_change = (
                            (final_value - initial_value) / initial_value
                        ) * 100
                        monthly_change = percentage_change / (time_diff.days / 30)
                    else:
                        percentage_change = None
                        monthly_change = None

                    trends[nutrient] = {
                        "initial_value": initial_value,
                        "final_value": final_value,
                        "percentage_change": percentage_change,
                        "monthly_change": monthly_change,
                    }

    # Restaurar las fechas a string: el template serializa historical_data
    # con tojson y un datetime se volvería un http-date ilegible en el chart.
    for entry in historical_data:
        entry["fecha"] = entry["fecha"].strftime("%b %Y")

    return trends


@web.route("/vista_reporte/<int:report_id>")
@jwt_required()
def vista_reporte(report_id):
    """Página: Vista detallada de un informe de recomendación nutricional.

    Renderiza análisis foliar, Ley del Mínimo, balance de minerales,
    dosis nano, tendencias históricas y snapshot RGB del lote. Aplica
    validación multi-tenant sobre la finca del lote asociado.

    :param report_id: ID de la recomendación a visualizar
    :status 200: Vista detallada del informe
    :status 403: Usuario sin acceso a la finca del lote
    :status 404: Recomendación no encontrada
    """
    claims = get_jwt()
    context = {
        "dashboard": True,
        "title": "Análisis y Recomendaciones",
        "description": "Detalles del informe.",
        "author": "Johnny De Castro",
        "site_title": "Ver Informe",
        "data_menu": get_dashboard_menu(),
    }
    view = ReportView()
    response = view.get(report_id)
    data_response = response.get_json()

    # Extraer los datos históricos de la respuesta
    historical_data = data_response.get("historicalData", [])
    trends = calculate_trends(historical_data)

    analysis_data = data_response.get("analysisData", {})
    minimum_law_analyses = data_response.get("minimum_law_analyses", {})
    automatic_recommendations = data_response.get("automatic_recommendations", {})
    text_recommendations = data_response.get("text_recommendations", "")

    # Referencia de comparación: persistida en el snapshot por los informes
    # de agrovista (comparison_label). Fallback para informes anteriores:
    # el crop validado contra LotCrop (objetivo ideal) o etiqueta genérica.
    comparison_label = (
        minimum_law_analyses.get("comparison_label")
        if isinstance(minimum_law_analyses, dict)
        else None
    )
    if not comparison_label:
        crop_info = data_response.get("crop")
        if crop_info and crop_info.get("name"):
            comparison_label = f"Datos cultivo ideal {crop_info['name']}"
        else:
            comparison_label = "Referencia personalizada"

    # Cargar filas de dosis por ha persistidas por RecommendationGenerator.
    # Una por producto en la combinación del optimizer. El template las
    # renderiza en la pestaña Recomendaciones con tabla estructurada
    # (kg/ha polvo | L/ha líquido + costo/ha). Si la lista está vacía
    # (Recomendaciones legacy anteriores a la fase 002_add_recommendation_dose)
    # se cae al fallback de texto plano de automatic_recommendations.
    dose_rows = (
        RecommendationDose.query.filter_by(recommendation_id=report_id)
        .order_by(RecommendationDose.id.asc())
        .all()
    )
    recommendation_doses = [d.to_dict() for d in dose_rows]

    # Snapshot RGB del lote (generado por agrovista al guardar el análisis).
    # Opcional: si el análisis base no tiene snapshot, el template no muestra nada.
    lot_image_url = None
    recommendation = db.session.get(Recommendation, report_id)
    if recommendation is not None and recommendation.base_analysis is not None:
        lot_image_url = resolve_lot_snapshot_url(recommendation.base_analysis)

    # Obtener CV de nutrientes para la tabla de Ley del Mínimo
    lot_id = (
        data_response.get("lot", {}).get("id") if data_response.get("lot") else None
    )
    cv_data = {}
    if lot_id:
        try:
            cv_data = determinar_coeficientes_variacion(lot_id)
            cv_data = {k: float(v) for k, v in cv_data.items()}
        except Exception:
            cv_data = {}

    nutrient_names = {
        "nitrógeno": "N",
        "fósforo": "P",
        "potasio": "K",
        "calcio": "Ca",
        "magnesio": "Mg",
        "azufre": "S",
        "hierro": "Fe",
        "manganeso": "Mn",
        "zinc": "Zn",
        "cobre": "Cu",
        "boro": "B",
        "molibdeno": "Mo",
        "silicio": "Si",
        "ph": "pH",
        "materiaOrganica": "MO",
        "cic": "CIC",
    }

    # Agregar los datos históricos y las tendencias al contexto
    context.update(
        {
            "historical_data": historical_data,
            "trends": trends,
            "cv_data": cv_data,
        }
    )

    # --- Balance de Minerales (mismo cálculo que agrovista.comparison_config) ---
    # Usa los datos foliares y el objetivo productivo ya persistidos en el
    # reporte para computar déficits, grados y dosis de producto nano por ha.
    mineral_balance = {}
    nano_doses = {}
    productive_obj = data_response.get("productiveObjective") or {}
    foliar_data = (
        analysis_data.get("foliar", {}) if isinstance(analysis_data, dict) else {}
    )
    if foliar_data and isinstance(foliar_data, dict):
        nutrients = Nutrient.query.order_by(Nutrient.id.asc()).all()
        # Mapa: clave foliar (nombre sin espacios ni tildes) → símbolo químico
        name_to_symbol = {n.name.lower().replace(" ", ""): n.symbol for n in nutrients}
        order = []
        targets = {}
        actuals = {}
        for key, entry in foliar_data.items():
            if key == "id" or not isinstance(entry, dict):
                continue
            symbol = name_to_symbol.get(key)
            if not symbol:
                continue
            order.append(symbol)
            if entry.get("ideal") is not None:
                targets[symbol] = float(entry["ideal"])
            if entry.get("valor") is not None:
                actuals[symbol] = float(entry["valor"])
        # Sort order to match agrovista/comparacion column layout
        # (Nutrient.id order: N, P, K, Ca, Mg, S, Cu, Zn, Mn, B, Mo, Cl, Fe, Si).
        symbol_position = {n.symbol: i for i, n in enumerate(nutrients)}
        order.sort(key=lambda s: symbol_position.get(s, 9999))
        # Aforo objetivo: meta productiva (fallback al actual); aforo actual:
        # el del common analysis, convierte la fila Actual (kg/ha).
        aforo_actual = productive_obj.get("current", {}).get("yield")
        aforo = productive_obj.get("target", {}).get("yield") or aforo_actual
        if order and aforo:
            try:
                mineral_balance = compute_mineral_balance(
                    order,
                    targets,
                    actuals,
                    aforo,
                    nutrients,
                    aforo_actual=aforo_actual,
                )
            except Exception:
                current_app.logger.warning(
                    "mineral_balance computation failed for report %s", report_id
                )
                mineral_balance = {}

        # Costeo de los déficits con la línea nano: por cada déficit del
        # balance se elige el producto con aporte (ProductContribution)
        # que cubre el requerimiento al menor costo. Reemplaza la tabla
        # de dosis del optimizer en el template; recommendation_doses
        # queda como fallback para reportes sin balance computable.
        if mineral_balance.get("entries"):
            try:
                now = datetime.now()
                price_units = {
                    pp.product.name: pp.price_unit
                    for pp in ProductPrice.query.filter(
                        ProductPrice.start_date <= now,
                        ProductPrice.end_date >= now,
                    ).all()
                }
                nano_doses = compute_nano_dose_rows(
                    mineral_balance,
                    {n.symbol: n.name for n in nutrients},
                    contribuciones_de_producto(),
                    precios_de_producto(),
                    price_units,
                )
            except Exception:
                current_app.logger.warning(
                    "nano dose costing failed for report %s", report_id
                )
                nano_doses = {}

    return render_template(
        "view_report.j2",
        **context,
        request=request,
        lot_image_url=lot_image_url,
        analysisData=analysis_data,
        nutrient_names=nutrient_names,
        minimum_law_analyses=minimum_law_analyses,
        automatic_recommendations=automatic_recommendations,
        text_recommendations=text_recommendations,
        recommendation_doses=recommendation_doses,
        crop_name=(
            data_response.get("crop", {}).get("name")
            if data_response.get("crop")
            else None
        ),
        report_title=data_response.get("title", ""),
        report_author=data_response.get("author", ""),
        recommendation_id=report_id,
        productiveObjective=productive_obj,
        comparison_label=comparison_label,
        lot_area=(data_response.get("lot") or {}).get("area"),
        mineral_balance=mineral_balance,
        nano_doses=nano_doses,
    )


@web.route("/seguimiento/<int:lot_id>")
@login_required
def seguimiento_lote(lot_id: int):
    """Página de seguimiento foliar post-aplicación para un lote."""
    lot = Lot.query.get_or_404(lot_id)
    claims = get_jwt()
    if not check_resource_access(lot.farm, claims):
        raise Forbidden("No tienes acceso a este lote.")
    # author = usuario autenticado (full_name, fallback username, fallback "Sistema")
    author = claims.get("full_name") or claims.get("username") or "Sistema"
    context = {
        "dashboard": True,
        "title": "Seguimiento Foliar",
        "description": "Evolución nutricional post-aplicación.",
        "author": author,
        "site_title": "Seguimiento Foliar",
        "data_menu": get_dashboard_menu(),
        "lot_id": lot_id,
        "lot_name": lot.name,
        "farm_name": lot.farm.name,
    }
    return render_template("seguimiento_lote.j2", **context, request=request)


@web.route("/solicitar_informe")
@login_required
def generar_informe():
    """Página: Formulario de solicitud de informe nutricional.

    Permite seleccionar finca, lote, cultivo y objetivo para generar
    un nuevo reporte de recomendación. El formulario envía los datos
    a la API para su procesamiento.

    :status 200: Formulario de solicitud de informe
    """
    context = {
        "dashboard": True,
        "title": "Dashboard TecnoAgro",
        "description": "Panel de control.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "og_image": "/img/og-image.jpg",
        "twitter_image": "/img/twitter-image.jpg",
        "data_menu": get_dashboard_menu(),
    }
    return render_template("solicitar_informe2.j2", **context, request=request)


# return render_template("solicitar_informe.j2", **context, request=request)


@web.route("/cv_nutrientes")
@login_required
def cv_nutrientes():
    """
    Página: Renderiza la vista de CV de nutrientes
    """
    # Calcular el CV para cada nutriente en el lote con ID 1
    coeficientes_variacion = determinar_coeficientes_variacion(1)
    productos_contribuciones = contribuciones_de_producto()
    objective_resource = ObjectiveResource()
    response = objective_resource.get_objective_list()

    # Obtener demandas ideales para el cultivo de papa
    crop_objectives = response.papa
    demandas_ideales = crop_objectives.get(index=0)
    demandas_ideales_dict = demandas_ideales.nutrient_data  # Already Decimal

    # Obtener análisis de hojas para el lote con ID 1
    leaf_analysis_resource = LeafAnalysisResource()
    response = leaf_analysis_resource.get_leaf_analysis_list()
    data_string = response.get_json()
    data = json.loads(data_string)
    nutrientes_actuales_raw = data["4"][0]["nutrients"]

    # Convertir los valores de nutrientes_actuales a Decimal
    nutrientes_actuales = {
        nutriente: Decimal(str(valor))  # Convert string to Decimal
        for nutriente, valor in nutrientes_actuales_raw.items()
    }

    # Asegurar que demandas_ideales_dict es un diccionario
    if not isinstance(demandas_ideales_dict, dict):
        raise ValueError("demandas_ideales no es un diccionario")

    # Asegurar que nutrientes_actuales es un diccionario
    if not isinstance(nutrientes_actuales, dict):
        raise ValueError("nutrientes_actuales no es un diccionario")

    # Instanciar y usar la clase
    optimizador = NutrientOptimizer(
        nutrientes_actuales,
        demandas_ideales_dict,
        productos_contribuciones,
        coeficientes_variacion,
    )
    limitante = optimizador.identificar_limitante()
    recomendacion = optimizador.generar_recomendacion(lot_id=1)
    return f"Nutriente limitante: {limitante}\n{recomendacion}"
