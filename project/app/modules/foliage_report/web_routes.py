import json
from decimal import Decimal

from flask import current_app, render_template, request, url_for
from flask_jwt_extended import get_jwt, jwt_required
from werkzeug.exceptions import Forbidden

from app.core.controller import check_resource_access, login_required
from app.extensions import db
from app.modules.foliage.models import CommonAnalysis, Crop, Farm, Lot, Recommendation

from . import foliage_report as web
from .controller import ReportView
from .helpers import (
    LeafAnalysisResource,
    NutrientOptimizer,
    ObjectiveResource,
    calcular_cv_nutriente,
    contribuciones_de_producto,
    determinar_coeficientes_variacion,
)


def get_dashboard_menu():
    """Define el menu superior en los templates"""
    return {
        "menu": [
            {"name": "Home", "url": url_for("core.index")},
            {"name": "Logout", "url": url_for("core.logout")},
            {"name": "Profile", "url": url_for("core.profile")},
        ]
    }


@web.route("/listar_reportes/")
@login_required
def listar_reportes():
    claims = get_jwt()
    user_role = claims.get("rol")

    # Obtener parámetros de filtro de la URL
    farm_id = request.args.get("farm_id", type=int)
    lot_id = request.args.get("lot_id", type=int)

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
    query = Recommendation.query.options(
        db.joinedload(Recommendation.lot)
        .joinedload(Lot.farm)
        .joinedload(Farm.organization),
        db.joinedload(Recommendation.crop),
    ).filter(Recommendation.active == True)

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
                "crop": rec.crop.name if rec.crop else "N/A",
                "date": rec.date.strftime("%Y-%m-%d") if rec.date else "N/A",
                "autor": rec.author or "Sistema",
            }
        )

    total_informes = len(items_list)

    return render_template(
        "listar_reportes.j2",
        **context,
        request=request,
        total_informes=total_informes,
        items=items_list,
    )


# desarrollo temporal.
from datetime import datetime, timedelta


def calculate_trends(historical_data):
    trends = {}

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

    return trends


@web.route("/vista_reporte/<int:report_id>")
@jwt_required()
def vista_reporte(report_id):
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
        }
    )

    return render_template(
        "view_report.j2",
        **context,
        request=request,
        analysisData=analysis_data,
        nutrient_names=nutrient_names,
        minimum_law_analyses=minimum_law_analyses,
        automatic_recommendations=automatic_recommendations,
    )


@web.route("/vista_report")
@login_required
def vista_report():
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

    analysisData = {
        "common": {
            "id": 3,
            "fechaAnalisis": "2025-03-26",
            "finca": "El nuevo rocío",
            "lote": "Lote 1",
            "proteinas": 6.0,
            "descanso": 5.0,
            "diasDescanso": 5,
            "mes": 5,
        },
        "foliar": {
            "id": 1,
            "nitrogeno": 2.5,
            "fosforo": 0.3,
            "potasio": 1.8,
            "calcio": 1.2,
            "magnesio": 0.4,
            "azufre": 0.2,
            "hierro": 85,
            "manganeso": 45,
            "zinc": 18,
            "cobre": 6,
            "boro": 25,
        },
        "soil": {
            "id": 1,
            "ph": 6.5,
            "materiaOrganica": 3.2,
            "nitrogeno": 0.15,
            "fosforo": 12,
            "potasio": 180,
            "calcio": 1200,
            "magnesio": 180,
            "azufre": 15,
            "textura": "Franco-arcillosa",
            "cic": 15.2,
        },
    }

    optimalLevels = {
        "foliar": {
            "nitrogeno": {"min": 2.8, "max": 3.5},
            "fosforo": {"min": 0.2, "max": 0.4},
            "potasio": {"min": 2.0, "max": 3.0},
            "calcio": {"min": 1.0, "max": 2.0},
            "magnesio": {"min": 0.3, "max": 0.6},
            "azufre": {"min": 0.2, "max": 0.4},
            "hierro": {"min": 50, "max": 150},
            "manganeso": {"min": 25, "max": 100},
            "zinc": {"min": 20, "max": 50},
            "cobre": {"min": 5, "max": 15},
            "boro": {"min": 20, "max": 50},
        },
        "soil": {
            "ph": {"min": 6.0, "max": 7.0},
            "materiaOrganica": {"min": 3.0, "max": 5.0},
            "nitrogeno": {"min": 0.15, "max": 0.25},
            "fosforo": {"min": 15, "max": 30},
            "potasio": {"min": 150, "max": 250},
            "calcio": {"min": 1000, "max": 2000},
            "magnesio": {"min": 150, "max": 300},
            "azufre": {"min": 10, "max": 20},
            "cic": {"min": 12, "max": 25},
        },
    }

    foliarChartData = [
        {
            "name": "N",
            "actual": analysisData["foliar"]["nitrogeno"],
            "min": optimalLevels["foliar"]["nitrogeno"]["min"],
            "max": optimalLevels["foliar"]["nitrogeno"]["max"],
        },
        {
            "name": "P",
            "actual": analysisData["foliar"]["fosforo"],
            "min": optimalLevels["foliar"]["fosforo"]["min"],
            "max": optimalLevels["foliar"]["fosforo"]["max"],
        },
        {
            "name": "K",
            "actual": analysisData["foliar"]["potasio"],
            "min": optimalLevels["foliar"]["potasio"]["min"],
            "max": optimalLevels["foliar"]["potasio"]["max"],
        },
        {
            "name": "Ca",
            "actual": analysisData["foliar"]["calcio"],
            "min": optimalLevels["foliar"]["calcio"]["min"],
            "max": optimalLevels["foliar"]["calcio"]["max"],
        },
        {
            "name": "Mg",
            "actual": analysisData["foliar"]["magnesio"],
            "min": optimalLevels["foliar"]["magnesio"]["min"],
            "max": optimalLevels["foliar"]["magnesio"]["max"],
        },
        {
            "name": "S",
            "actual": analysisData["foliar"]["azufre"],
            "min": optimalLevels["foliar"]["azufre"]["min"],
            "max": optimalLevels["foliar"]["azufre"]["max"],
        },
    ]

    soilChartData = [
        {
            "name": "pH",
            "actual": analysisData["soil"]["ph"],
            "min": optimalLevels["soil"]["ph"]["min"],
            "max": optimalLevels["soil"]["ph"]["max"],
            "unit": "",
        },
        {
            "name": "M.O.",
            "actual": analysisData["soil"]["materiaOrganica"],
            "min": optimalLevels["soil"]["materiaOrganica"]["min"],
            "max": optimalLevels["soil"]["materiaOrganica"]["max"],
            "unit": "%",
        },
        {
            "name": "N",
            "actual": analysisData["soil"]["nitrogeno"],
            "min": optimalLevels["soil"]["nitrogeno"]["min"],
            "max": optimalLevels["soil"]["nitrogeno"]["max"],
            "unit": "%",
        },
        {
            "name": "P",
            "actual": analysisData["soil"]["fosforo"],
            "min": optimalLevels["soil"]["fosforo"]["min"],
            "max": optimalLevels["soil"]["fosforo"]["max"],
            "unit": "ppm",
        },
        {
            "name": "K",
            "actual": analysisData["soil"]["potasio"],
            "min": optimalLevels["soil"]["potasio"]["min"],
            "max": optimalLevels["soil"]["potasio"]["max"],
            "unit": "ppm",
        },
        {
            "name": "CIC",
            "actual": analysisData["soil"]["cic"],
            "min": optimalLevels["soil"]["cic"]["min"],
            "max": optimalLevels["soil"]["cic"]["max"],
            "unit": "meq/100g",
        },
    ]

    historicalData = [
        {"fecha": "Ene 2025", "nitrogeno": 2.3, "fosforo": 0.25, "potasio": 1.5},
        {"fecha": "Feb 2025", "nitrogeno": 2.4, "fosforo": 0.28, "potasio": 1.6},
        {"fecha": "Mar 2025", "nitrogeno": 2.5, "fosforo": 0.3, "potasio": 1.8},
    ]

    nutrientNames = {
        "nitrogeno": "Nitrógeno",
        "fosforo": "Fósforo",
        "potasio": "Potasio",
        "calcio": "Calcio",
        "magnesio": "Magnesio",
        "azufre": "Azufre",
        "hierro": "Hierro",
        "manganeso": "Manganeso",
        "zinc": "Zinc",
        "cobre": "Cobre",
        "boro": "Boro",
        "ph": "pH",
        "materiaOrganica": "Materia Orgánica",
        "cic": "CIC",
    }

    def getNutrientStatus(actual, min, max):
        if actual < min:
            return "deficiente"
        if actual > max:
            return "excesivo"
        return "óptimo"

    def getStatusColor(status):
        match status:
            case "deficiente":
                return "text-red-500"
            case "excesivo":
                return "text-yellow-500"
            case "óptimo":
                return "text-green-500"
            case _:
                return ""

    def getStatusIcon(status):
        match status:
            case "deficiente":
                return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-4 w-4 text-red-500"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"></polygon><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>'
            case "excesivo":
                return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-4 w-4 text-yellow-500"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"></polygon><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>'
            case "óptimo":
                return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-4 w-4 text-green-500"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="12 2 2 7.86 12 12"></polyline><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>'
            case _:
                return ""

    def findLimitingNutrient():
        limitingNutrient = None
        lowestPercentage = 100

        for nutrient, value in analysisData["foliar"].items():
            if nutrient in optimalLevels["foliar"]:
                min_value = optimalLevels["foliar"][nutrient]["min"]
                max_value = optimalLevels["foliar"][nutrient]["max"]
                optimalMid = (min_value + max_value) / 2
                percentage = (value / optimalMid) * 100
                if percentage < lowestPercentage and percentage < 90:
                    lowestPercentage = percentage
                    limitingNutrient = {
                        "name": nutrient,
                        "value": value,
                        "optimal": optimalMid,
                        "percentage": percentage,
                        "type": "foliar",
                    }

        for nutrient, value in analysisData["soil"].items():
            if nutrient in optimalLevels["soil"] and nutrient != "ph":
                min_value = optimalLevels["soil"][nutrient]["min"]
                max_value = optimalLevels["soil"][nutrient]["max"]
                optimalMid = (min_value + max_value) / 2
                percentage = (value / optimalMid) * 100
                if percentage < lowestPercentage and percentage < 90:
                    lowestPercentage = percentage
                    limitingNutrient = {
                        "name": nutrient,
                        "value": value,
                        "optimal": optimalMid,
                        "percentage": percentage,
                        "type": "soil",
                    }

        return limitingNutrient

    def generateRecommendations():
        recommendations = []

        limitingNutrient = findLimitingNutrient()

        if limitingNutrient:
            nutrientName = (
                nutrientNames[limitingNutrient["name"]] or limitingNutrient["name"]
            )
            recommendations.append(
                {
                    "title": f"Corregir deficiencia de {nutrientName}",
                    "description": f"El {nutrientName} es el nutriente limitante según la Ley de Liebig. Está al limitingNutrient['percentage']% del nivel óptimo.",
                    "priority": "alta",
                    "action": (
                        "Aplicar fertilizante foliar rico en {nutrientName}"
                        if limitingNutrient["type"] == "foliar"
                        else f"Incorporar {nutrientName} al suelo mediante fertilización"
                    ),
                }
            )

        phStatus = getNutrientStatus(
            analysisData["soil"]["ph"],
            optimalLevels["soil"]["ph"]["min"],
            optimalLevels["soil"]["ph"]["max"],
        )
        if phStatus != "óptimo":
            recommendations.append(
                {
                    "title": (
                        "Corregir acidez del suelo"
                        if phStatus == "deficiente"
                        else "Reducir alcalinidad del suelo"
                    ),
                    "description": f"El pH actual ({analysisData['soil']['ph']}) está {'por debajo' if phStatus == 'deficiente' else 'por encima'} del rango óptimo.",
                    "priority": "media",
                    "action": (
                        "Aplicar cal agrícola para elevar el pH"
                        if phStatus == "deficiente"
                        else "Aplicar azufre elemental o materia orgánica para reducir el pH"
                    ),
                }
            )

        moStatus = getNutrientStatus(
            analysisData["soil"]["materiaOrganica"],
            optimalLevels["soil"]["materiaOrganica"]["min"],
            optimalLevels["soil"]["materiaOrganica"]["max"],
        )
        if moStatus == "deficiente":
            recommendations.append(
                {
                    "title": "Aumentar materia orgánica",
                    "description": f"El nivel de materia orgánica ({analysisData['soil']['materiaOrganica']}%) está por debajo del óptimo.",
                    "priority": "media",
                    "action": "Incorporar compost, estiércol bien descompuesto o abonos verdes",
                }
            )

        return recommendations

    limitingNutrient = findLimitingNutrient()
    recommendations = generateRecommendations()

    return render_template(
        "ver_reporte2.j2",
        **context,
        request=request,
        analysisData=analysisData,
        optimalLevels=optimalLevels,
        foliarChartData=foliarChartData,
        soilChartData=soilChartData,
        historicalData=historicalData,
        nutrientNames=nutrientNames,
        limitingNutrient=limitingNutrient,
        recommendations=recommendations,
    )


@web.route("/solicitar_informe")
@login_required
def generar_informe():
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
