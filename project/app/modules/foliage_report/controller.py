# Python standard library imports
import json
import unicodedata
from datetime import datetime
from decimal import Decimal
from functools import wraps

from flask import Response, current_app, jsonify, request
from flask.views import MethodView
from flask_jwt_extended import get_jwt, jwt_required

# Third party imports
from werkzeug.exceptions import BadRequest, Forbidden, InternalServerError, NotFound

from app.core.controller import check_permission, check_resource_access
from app.core.models import ResellerPackage, RoleEnum

# Local application imports
from app.extensions import db
from app.modules.foliage.models import (
    CommonAnalysis,
    Crop,
    Farm,
    FollowUpAnalysis,
    LeafAnalysis,
    Lot,
    LotCrop,
    Nutrient,
    NutrientApplication,
    Objective,
    Product,
    ProductPrice,
    Recommendation,
    SoilAnalysis,
    leaf_analysis_nutrients,
    objective_nutrients,
)

from .helpers import (
    LeafAnalysisResource,
    LeyLiebig,
    NutrientOptimizer,
    ObjectiveResource,
    RecommendationError,
    compare_analyses,
    compute_dose,
    compute_dose_from_contributions,
    contribuciones_de_producto,
    precios_de_producto,
)
from .models import RecommendationDose


class ReportView(MethodView):
    """Clase para presentar reportes integrados de análisis"""

    decorators = [jwt_required()]

    def get(self, id):
        recommendation = Recommendation.query.get_or_404(id)

        def safe_json_load(data):
            try:
                return json.loads(data) if data else {}
            except json.JSONDecodeError:
                return {}

        foliar_data = safe_json_load(recommendation.foliar_analysis_details)
        optimal_levels = safe_json_load(recommendation.optimal_comparison)

        def normalize_key(s):
            return "".join(
                c
                for c in unicodedata.normalize("NFD", s.lower())
                if unicodedata.category(c) != "Mn"
            )

        def build_foliar_chart(foliar, optimal):
            keys = {
                "N": "nitrógeno",
                "P": "fósforo",
                "K": "potasio",
                "Ca": "calcio",
                "Mg": "magnesio",
                "S": "azufre",
                "Fe": "hierro",
                "Mn": "manganeso",
                "Zn": "zinc",
                "Cu": "cobre",
                "B": "boro",
                "Mo": "molibdeno",
                "Si": "silicio",
            }
            normalized_optimal = {normalize_key(k): v for k, v in optimal.items()}

            chart = []
            for name, key in keys.items():
                actual = foliar.get(key)
                opt_key = normalize_key(key)
                opt = normalized_optimal.get(opt_key)

                if actual is not None and opt and "min" in opt and "max" in opt:
                    chart.append(
                        {
                            "name": name,
                            "actual": actual,
                            "min": opt["min"],
                            "max": opt["max"],
                        }
                    )

            return chart

        response = {
            "id": recommendation.id,
            "date": recommendation.date.isoformat(),
            "title": recommendation.title,
            "author": recommendation.author,
            "analysisData": {
                "common": {
                    "id": recommendation.id,
                    "fechaAnalisis": recommendation.date.isoformat(),
                    "finca": (
                        recommendation.lot.farm.name
                        if recommendation.lot and recommendation.lot.farm
                        else "N/A"
                    ),
                    "lote": recommendation.lot.name if recommendation.lot else "N/A",
                },
                "foliar": foliar_data,
                "soil": safe_json_load(recommendation.soil_analysis_details),
            },
            "optimalLevels": optimal_levels,
            "foliarChartData": build_foliar_chart(foliar_data, optimal_levels),
            "historicalData": self._get_historical_data(
                recommendation.lot_id, recommendation.date
            ),
            # El crop solo se muestra si el lote realmente lo tiene asociado
            # (LotCrop). Los reportes de comparación agrovista usan un crop
            # "host" para el objetivo temporal que no debe aparecer.
            "crop": (
                {
                    "id": recommendation.crop.id,
                    "name": recommendation.crop.name,
                }
                if recommendation.crop
                and db.session.query(LotCrop.id)
                .filter_by(
                    lot_id=recommendation.lot_id,
                    crop_id=recommendation.crop_id,
                )
                .first()
                is not None
                else None
            ),
            "lot": (
                {
                    "id": recommendation.lot.id,
                    "name": recommendation.lot.name,
                    "area": float(recommendation.lot.area or 0),
                    "farm": (
                        {
                            "id": recommendation.lot.farm.id,
                            "name": recommendation.lot.farm.name,
                        }
                        if recommendation.lot.farm
                        else None
                    ),
                }
                if recommendation.lot
                else None
            ),
            "limiting_nutrient_id": recommendation.limiting_nutrient_id,
            "automatic_recommendations": recommendation.automatic_recommendations or "",
            "text_recommendations": recommendation.text_recommendations or "",
            "minimum_law_analyses": safe_json_load(recommendation.minimum_law_analyses),
            "applied": recommendation.applied,
            "active": recommendation.active,
            "created_at": recommendation.created_at.isoformat(),
            "updated_at": recommendation.updated_at.isoformat(),
            "organization": (
                {
                    "id": recommendation.organization.id,
                    "name": recommendation.organization.name,
                }
                if recommendation.organization
                else None
            ),
            "productiveObjective": self._get_productive_objective(
                recommendation.lot_id, recommendation.crop_id, recommendation.date
            ),
        }

        return jsonify(response)

    def _get_common_analysis(self, analysis_id):
        """Obtiene el análisis común con relaciones optimizadas"""
        return CommonAnalysis.query.options(
            db.joinedload(CommonAnalysis.lot).joinedload(Lot.farm),
            db.joinedload(CommonAnalysis.soil_analysis),
            db.joinedload(CommonAnalysis.leaf_analysis),
        ).get_or_404(analysis_id)

    def _check_access(self, common_analysis):
        """Valida permisos de acceso a la organización"""
        claims = get_jwt()
        user_role = claims.get("rol")

        if user_role == RoleEnum.ADMINISTRATOR.value:
            return

        if user_role == RoleEnum.RESELLER.value:
            org_id = (
                common_analysis.organization.id
                if common_analysis.organization
                else None
            )
            if not org_id:
                raise Forbidden("No se pudo determinar la organización del análisis")

            reseller_package = ResellerPackage.query.filter_by(
                reseller_id=claims.get("org_id")
            ).first()

            if not reseller_package or org_id not in reseller_package.organization_ids:
                raise Forbidden("Acceso denegado al recurso")

    def _build_analysis_data(self, analysis, objective_id=None):
        """Construye la estructura principal del reporte"""
        return {
            "common": self._serialize_common(analysis),
            "foliar": self._get_foliar_data(
                analysis.leaf_analysis, objective_id=objective_id
            ),
            "soil": self._get_soil_data(analysis.soil_analysis),
        }

    def _serialize_common(self, analysis):
        """Serializa datos del análisis común"""
        return {
            "id": analysis.id,
            "fechaAnalisis": analysis.date.isoformat(),
            "finca": (
                analysis.farm_name if analysis.lot and analysis.lot.farm else "N/A"
            ),
            "lote": analysis.lot_name if analysis.lot else "N/A",
            "proteinas": analysis.protein,
            "descanso": analysis.rest,
            "diasDescanso": analysis.rest_days,
            "mes": analysis.month,
            "aforo": analysis.yield_estimate,
        }

    def _get_foliar_data(self, leaf_analysis, objective_id=None):
        """Obtiene y formatea datos foliares con detalles adicionales."""
        if not leaf_analysis:
            return None

        foliar_data = {"id": leaf_analysis.id}
        leaf_nutrients = (
            db.session.query(leaf_analysis_nutrients)
            .filter_by(leaf_analysis_id=leaf_analysis.id)
            .all()
        )

        # Obtener todos los nutrientes y sus valores ideales del objetivo en una sola consulta
        ideal_values = {}
        if objective_id:
            obj_nutrients = (
                db.session.query(objective_nutrients)
                .filter_by(objective_id=objective_id)
                .all()
            )
            ideal_values = {on.nutrient_id: on.target_value for on in obj_nutrients}

        all_nutrients_query = Nutrient.query.all()
        nutrients_map = {n.id: n for n in all_nutrients_query}

        for ln in leaf_nutrients:
            nutrient = nutrients_map.get(ln.nutrient_id)
            if nutrient:
                key = nutrient.name.lower().replace(" ", "")
                ideal_value = ideal_values.get(ln.nutrient_id)

                foliar_data[key] = {
                    "valor": ln.value,
                    "tipo": (
                        nutrient.category.value if nutrient.category else "desconocido"
                    ),
                    "unidad": nutrient.unit,
                    "ideal": ideal_value,
                }

        return foliar_data

    def _get_soil_data(self, soil_analysis):
        """Obtiene y formatea datos de suelo"""
        if not soil_analysis:
            return None

        return {
            "id": soil_analysis.id,
            "energia": soil_analysis.energy,
            "pastoreo": soil_analysis.grazing,
        }

    def _lot_crop_data(self, common_analysis):
        """Obtiene el cultivo activo del lote en la fecha del análisis"""
        if not common_analysis or not common_analysis.lot_id:
            return None

        lot_crop = (
            LotCrop.query.filter(
                LotCrop.lot_id == common_analysis.lot_id,
                LotCrop.start_date <= common_analysis.date,
                db.or_(
                    LotCrop.end_date >= common_analysis.date, LotCrop.end_date.is_(None)
                ),
            )
            .options(db.joinedload(LotCrop.crop))
            .first()
        )

        return lot_crop

    def _get_optimal_levels(self, common_analysis):
        """Obtiene niveles óptimos del cultivo actual"""
        lot_crop = self._lot_crop_data(common_analysis)
        if not lot_crop or not lot_crop.crop:
            return None

        objective = Objective.query.filter_by(crop_id=lot_crop.crop.id).first()
        if not objective:
            return None

        return {
            "info": {
                "cultivo": lot_crop.crop.name,
                "valor_obj": objective.target_value,
                "proteina": objective.protein,
                "descanso": objective.rest,
            },
            "nutrientes": self._get_nutrient_targets(objective),
        }

    def _get_nutrient_targets(self, objective):
        """Obtiene y formatea los objetivos de nutrientes desde objective_nutrients"""
        targets = {}
        obj_nutrients = (
            db.session.query(objective_nutrients)
            .filter_by(objective_id=objective.id)
            .all()
        )

        for on in obj_nutrients:
            nutrient = Nutrient.query.get(on.nutrient_id)
            if nutrient:
                key = nutrient.name.lower().replace(" ", "")
                targets[key] = on.target_value

        return targets

    def _get_historical_data(self, lot_id, current_date):
        """Obtiene datos históricos de análisis foliares para el lote."""

        # Permitir recibir un objeto Lot o simplemente su id
        if isinstance(lot_id, Lot):
            lot_id = lot_id.id

        # <= para incluir el análisis base del informe: con < quedaba fuera
        # todo análisis del mismo día (caso agrovista: análisis e informe
        # creados hoy → histórico vacío en la vista del reporte).
        historical_analyses = (
            LeafAnalysis.query.join(CommonAnalysis)
            .filter(
                CommonAnalysis.lot_id == lot_id,
                CommonAnalysis.date <= current_date,
            )
            .order_by(CommonAnalysis.date.desc())
            .limit(5)
            .all()
        )

        data = []
        for analysis in reversed(historical_analyses):
            nutrients = (
                db.session.query(leaf_analysis_nutrients)
                .filter_by(leaf_analysis_id=analysis.id)
                .all()
            )
            entry = {"fecha": analysis.common_analysis.date.strftime("%b %Y")}
            for nv in nutrients:
                nutrient = Nutrient.query.get(nv.nutrient_id)
                if nutrient:
                    key = nutrient.name.lower().replace(" ", "")
                    entry[key] = nv.value
            data.append(entry)

        return data

    def _get_productive_objective(self, lot_id, crop_id, analysis_date):
        """Obtiene el objetivo productivo: actual (CommonAnalysis) vs meta (Objective)."""
        if not lot_id or not crop_id:
            return {}

        # Análisis actual del lote
        common = (
            CommonAnalysis.query.filter_by(lot_id=lot_id)
            .order_by(CommonAnalysis.date.desc())
            .first()
        )
        if not common:
            return {}

        # Objetivo del cultivo
        objective = Objective.query.filter_by(crop_id=crop_id).first()
        if not objective:
            return {}

        return {
            "current": {
                "yield": float(common.yield_estimate or 0),
                "protein": float(common.protein or 0),
                "rest": float(common.rest or 0),
            },
            "target": {
                "yield": float(objective.target_value or 0),
                "protein": float(objective.protein or 0),
                "rest": float(objective.rest or 0),
            },
            "gaps": {
                "yield": round(
                    float(common.yield_estimate or 0)
                    - float(objective.target_value or 0),
                    2,
                ),
                "yield_pct": round(
                    (
                        (
                            (
                                float(common.yield_estimate or 0)
                                - float(objective.target_value or 0)
                            )
                            / float(objective.target_value or 1)
                            * 100
                        )
                        if objective.target_value
                        else 0
                    ),
                    1,
                ),
                "protein": round(
                    float(common.protein or 0) - float(objective.protein or 0), 2
                ),
                "protein_pct": round(
                    (
                        (
                            (float(common.protein or 0) - float(objective.protein or 0))
                            / float(objective.protein or 1)
                            * 100
                        )
                        if objective.protein
                        else 0
                    ),
                    1,
                ),
            },
        }

    def _get_limiting_nutrient_data(self, limiting_name, analysisData, optimalLevels):
        """Intenta reconstruir los datos del nutriente limitante."""
        if not limiting_name or not analysisData or not optimalLevels:
            return None

        for key, value in analysisData.get("foliar", {}).items():
            if nutrient_names_map.get(key, key).lower() == limiting_name.lower():
                levels = optimalLevels.get("nutrientes", {}).get(key)
                if (
                    levels
                    and isinstance(levels, dict)
                    and "min" in levels
                    and "max" in levels
                ):
                    optimalMid = (levels["min"] + levels["max"]) / 2
                    percentage = (value / optimalMid * 100) if optimalMid != 0 else 0
                    return {
                        "name": key,
                        "value": value,
                        "percentage": percentage,
                        "type": "foliar",
                    }

        for key, value in analysisData.get("soil", {}).items():
            if (
                key != "ph"
                and nutrient_names_map.get(key, key).lower() == limiting_name.lower()
            ):
                levels = optimalLevels.get("nutrientes", {}).get(key)
                if (
                    levels
                    and isinstance(levels, dict)
                    and "min" in levels
                    and "max" in levels
                ):
                    optimalMid = (levels["min"] + levels["max"]) / 2
                    percentage = (value / optimalMid * 100) if optimalMid != 0 else 0
                    return {
                        "name": key,
                        "value": value,
                        "percentage": percentage,
                        "type": "soil",
                    }

        return {
            "name": limiting_name,
            "percentage": None,
            "type": "unknown",
        }

    def _get_nutrient_name_map(self):
        """Genera un mapa de claves internas a nombres legibles."""
        return {
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
            # Añade mapeos para todas las claves que uses
        }


nutrient_names_map = ReportView()._get_nutrient_name_map()


class RecommendationView(MethodView):
    """Class to manage CRUD operations for recommendations"""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, recommendation_id=None):
        """
        Retrieve a list of recommendations or a specific recommendation
        Args:
            recommendation_id (int, optional): ID of the recommendation to retrieve
        Returns:
            JSON: List of recommendations or details of a specific recommendation
        """
        if recommendation_id:
            return self._get_recommendation(recommendation_id)
        return self._get_recommendation_list()

    @check_permission(required_roles=["administrator", "reseller"])
    def post(self):
        """
        Create a new recommendation
        Returns:
            JSON: Details of the created recommendation
        """
        data = request.get_json()
        required_fields = ["lot_id", "date", "recommendation"]
        if not data or not all(k in data for k in required_fields):
            raise BadRequest("Missing required fields")
        return self._create_recommendation(data)

    @check_permission(resource_owner_check=True)
    def put(self, id: int):
        """
        Update an existing recommendation
        Args:
            recommendation_id (int): ID of the recommendation to update
        Returns:
            JSON: Details of the updated recommendation
        """
        data = request.get_json()
        recommendation_id = id
        if not data or not recommendation_id:
            raise BadRequest("Missing recommendation_id or data")
        return self._update_recommendation(recommendation_id, data)

    @check_permission(resource_owner_check=True)
    def delete(self, id=None):
        """
        Delete an existing recommendation
        Args:
            recommendation_id (int): ID of the recommendation to delete
        Returns:
            JSON: Confirmation message
        """
        recommendation_id = id
        if not recommendation_id:
            raise BadRequest("Missing recommendation_id")
        return self._delete_recommendation(recommendation_id)

    # Helper Methods
    def _get_recommendation_list(self):
        """Retrieve a list of all recommendations"""
        claims = get_jwt()
        user_role = claims.get("rol")
        if user_role == RoleEnum.ADMINISTRATOR.value:
            recommendations = Recommendation.query.all()
        elif user_role == RoleEnum.RESELLER.value:
            reseller_package = ResellerPackage.query.filter_by(
                reseller_id=claims.get("org_id")
            ).first()
            if not reseller_package:
                raise NotFound("Reseller package not found.")
            recommendations = []
            for organization in reseller_package.organizations:
                for lot in organization.lots:
                    recommendations.extend(lot.recommendations)
        else:
            raise Forbidden(
                "Only administrators and resellers can list recommendations"
            )
        response_data = [self._serialize_recommendation(r) for r in recommendations]
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _get_recommendation(self, recommendation_id):
        """Retrieve details of a specific recommendation"""
        recommendation = Recommendation.query.get_or_404(recommendation_id)
        claims = get_jwt()
        if not self._has_access(recommendation, claims):
            raise Forbidden("You do not have access to this recommendation")
        response_data = self._serialize_recommendation(recommendation)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _create_recommendation(self, data):
        """Create a new recommendation"""
        lot_id = data["lot_id"]
        date = data["date"]
        recommendation = data["recommendation"]
        rec = Recommendation(lot_id=lot_id, date=date, recommendation=recommendation)
        db.session.add(rec)
        db.session.commit()
        response_data = self._serialize_recommendation(rec)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=201, mimetype="application/json")

    def _update_recommendation(self, recommendation_id, data):
        """Update an existing recommendation"""
        recommendation = Recommendation.query.get_or_404(recommendation_id)
        if "date" in data:
            recommendation.date = data["date"]
        if "recommendation" in data:
            recommendation.recommendation = data["recommendation"]
        db.session.commit()
        response_data = self._serialize_recommendation(recommendation)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _delete_recommendation(self, recommendation_id):
        """Delete an existing recommendation"""
        recommendation = Recommendation.query.get_or_404(recommendation_id)
        db.session.delete(recommendation)
        db.session.commit()
        return jsonify({"message": "Recommendation deleted successfully"}), 200

    def _has_access(self, recommendation, claims):
        """Check if the current user has access to the recommendation"""
        return check_resource_access(recommendation, claims)

    def _serialize_recommendation(self, recommendation):
        """Serialize a Recommendation object to a dictionary"""
        return {
            "id": recommendation.id,
            "lot_id": recommendation.lot_id,
            "date": recommendation.date,
            "recommendation": recommendation.recommendation,
            "created_at": recommendation.created_at.isoformat(),
            "updated_at": recommendation.updated_at.isoformat(),
        }


class RecommendationGenerator(MethodView):
    """Genera y guarda un nuevo reporte de recomendación."""

    decorators = [jwt_required()]

    @check_permission(
        required_roles=["administrator", "reseller", "org_admin", "org_editor"]
    )
    def post(self):
        """
        Genera un reporte basado en los parámetros recibidos.
        Expected JSON: {"lot_id": int, "common_analysis_id": int, "objective_id": int, "title": str}
        """
        claims = get_jwt()
        author_name = claims.get("username", "Sistema")

        data = request.get_json()
        if not data or not all(
            k in data for k in ["lot_id", "common_analysis_id", "objective_id", "title"]
        ):
            raise BadRequest(
                "Faltan parámetros: lot_id, common_analysis_id, objective_id, title"
            )

        lot_id = data.get("lot_id")
        common_analysis_id = data.get("common_analysis_id")
        objective_id = data.get("objective_id")
        report_title = data.get("title")
        minimum_law_analyses_str = data.get("minimum_law_analyses")
        # Etiqueta de la referencia de comparación (agrovista): nombre del
        # lote A en modo lot_vs_lot o "Datos cultivo ideal <crop>" en modo
        # objetivo. Se persiste dentro del snapshot minimum_law_analyses
        # para que el informe pueda mostrar contra qué se comparó.
        comparison_label = data.get("comparison_label")
        if comparison_label is not None and not isinstance(comparison_label, str):
            raise BadRequest("comparison_label debe ser un string.")
        # New optional inputs for dose-per-ha (gap P1: foliar not supported yet).
        # yield_kg_per_ha is reserved for future use; current optimizer does
        # not require it because contributions/demands are already in % p/p.
        # application_mode drives the dose_unit: 'edaphic' (kg/ha | L/ha)
        # or 'foliar' (returns dose_per_ha=None, see compute_dose()).
        yield_kg_per_ha = data.get("yield_kg_per_ha")
        application_mode = data.get("application_mode", "edaphic")
        if application_mode not in ("edaphic", "foliar"):
            raise BadRequest("application_mode debe ser 'edaphic' o 'foliar'.")

        if not isinstance(lot_id, int):
            raise BadRequest("lot_id debe ser un entero.")
        if not isinstance(common_analysis_id, int):
            raise BadRequest("common_analysis_id debe ser un entero.")
        if not common_analysis_id:
            raise BadRequest("common_analysis_id no puede estar vacío.")
        if not isinstance(objective_id, int):
            raise BadRequest("objective_id debe ser un entero.")
        if not isinstance(report_title, str) or not report_title.strip():
            raise BadRequest("El título no puede estar vacío.")
        # Validación de los nuevos inputs opcionales para dosis por ha.
        if yield_kg_per_ha is not None and (
            not isinstance(yield_kg_per_ha, (int, float)) or yield_kg_per_ha < 0
        ):
            raise BadRequest(
                "yield_kg_per_ha debe ser un número no negativo (o null para omitir)."
            )
        # application_mode ya fue validado arriba (debe ser 'edaphic' o 'foliar').

        # --- Procesar CommonAnalysis ---
        common_analysis = CommonAnalysis.query.options(
            db.joinedload(CommonAnalysis.leaf_analysis)
            .joinedload(LeafAnalysis.nutrients)
            .joinedload(Nutrient.objectives),  # Preload Nutrient for objectives
            db.joinedload(CommonAnalysis.soil_analysis),
            db.joinedload(CommonAnalysis.lot),  # Para crop_id y farm access check
        ).get(common_analysis_id)

        if not common_analysis:
            raise NotFound(
                f"No se encontró CommonAnalysis con ID {common_analysis_id}."
            )

        if not common_analysis.leaf_analysis:
            raise NotFound(
                f"CommonAnalysis ID {common_analysis_id} no tiene un LeafAnalysis asociado."
            )

        # Verificar acceso al lote/finca
        lot = common_analysis.lot
        if not lot or not check_resource_access(lot.farm, claims):
            raise Forbidden("No tienes acceso a este lote/finca.")

        # 1. Niveles actuales (del LeafAnalysis)
        nutrientes_actuales_raw = {}
        # Acceder a los nutrientes a través de la relación cargada en common_analysis.leaf_analysis
        for nutrient_assoc in common_analysis.leaf_analysis.nutrients:
            # nutrient_assoc es una instancia de Nutrient, el valor está en la tabla de asociación
            # Necesitamos una forma de obtener el 'value' de la tabla leaf_analysis_nutrients
            # Esto requiere que el modelo LeafAnalysis.nutrients devuelva objetos que contengan el valor.
            # Asumimos que la relación está configurada para esto o se hace una subconsulta.
            # Por ahora, vamos a buscarlo directamente si no está en el objeto `nutrient_assoc`.
            # Esto es ineficiente y debería mejorarse con una carga adecuada en el modelo.

            stmt = db.select(db.column("value")).where(
                db.and_(
                    leaf_analysis_nutrients.c.leaf_analysis_id
                    == common_analysis.leaf_analysis.id,
                    leaf_analysis_nutrients.c.nutrient_id == nutrient_assoc.id,
                )
            )
            result = db.session.execute(stmt).scalar_one_or_none()
            if result is not None:
                nutrientes_actuales_raw[nutrient_assoc.name] = result
            else:
                current_app.logger.warning(
                    f"No se encontró valor para el nutriente {nutrient_assoc.name} en LeafAnalysis {common_analysis.leaf_analysis.id}"
                )

        if not nutrientes_actuales_raw:
            raise NotFound(
                f"LeafAnalysis ID {common_analysis.leaf_analysis.id} no tiene valores de nutrientes."
            )
        nutrientes_actuales = {
            k: Decimal(str(v)) for k, v in nutrientes_actuales_raw.items()
        }

        # --- Procesar Objective ---
        objective = Objective.query.options(
            db.joinedload(
                Objective.nutrients
            )  # Asegura que los nutrientes del objetivo están cargados
        ).get(objective_id)
        if not objective:
            raise NotFound(f"No se encontró Objective con ID {objective_id}.")

        crop_id = objective.crop_id  # Usar el crop_id del objetivo

        # 2. Demandas ideales (del Objective)
        demandas_ideales = {}
        # Los nutrientes y sus target_value están en la tabla de asociación objective_nutrients
        for nutrient_target in objective.nutrients:
            # Similar al caso anterior, necesitamos el target_value de la tabla de asociación
            stmt = db.select(db.column("target_value")).where(
                db.and_(
                    objective_nutrients.c.objective_id == objective.id,
                    objective_nutrients.c.nutrient_id == nutrient_target.id,
                )
            )
            target_value = db.session.execute(stmt).scalar_one_or_none()
            if target_value is not None:
                demandas_ideales[nutrient_target.name] = Decimal(str(target_value))
            else:
                current_app.logger.warning(
                    f"No se encontró target_value para el nutriente {nutrient_target.name} en Objective {objective.id}"
                )

        if not demandas_ideales:
            raise NotFound(
                f"El objetivo ID {objective_id} no tiene metas de nutrientes definidas."
            )

        # 3. Contribuciones de producto
        productos_contribuciones_data = contribuciones_de_producto()
        productos_precios_data = precios_de_producto()

        # Exclude products without valid price (they would appear as "free" and always be chosen)
        productos_contribuciones_data = {
            prod: contrib
            for prod, contrib in productos_contribuciones_data.items()
            if prod in productos_precios_data and productos_precios_data[prod] > 0
        }

        # 4. Coeficientes de variación obtenidos desde el modelo Nutrient
        coeficientes_variacion = {
            n.name: Decimal(str(n.cv)) if n.cv is not None else Decimal("0")
            for n in Nutrient.query.all()
        }

        # --- Instanciar y usar NutrientOptimizer ---
        try:
            optimizer = NutrientOptimizer(
                nutrientes_actuales,
                demandas_ideales,
                productos_contribuciones_data,
                productos_precios_data,
                coeficientes_variacion,
            )
            recomendacion_texto = optimizer.generar_recomendacion(lot_id=lot_id)
            limitante_nombre = optimizer.identificar_limitante()
        except ValueError as ve:
            if "No products available for optimization" in str(ve):
                current_app.logger.error(
                    f"ValueError en optimización para lote {lot_id} con objetivo {objective_id}: {str(ve)}",
                    exc_info=True,
                )
                raise BadRequest(
                    "No hay productos de fertilización configurados o disponibles que coincidan con los nutrientes requeridos. No se puede generar una recomendación."
                )
            # Re-raise other ValueErrors to be caught by the generic Exception handler or handled differently if needed
            raise
        except Exception as e:
            current_app.logger.error(
                f"Error en optimización para lote {lot_id} con objetivo {objective_id}: {str(e)}",
                exc_info=True,
            )
            raise BadRequest(
                f"Error al generar recomendación con optimizador: {str(e)}"
            )

        # --- Dose per ha: lectura directa de product_contributions ---
        # NO usamos optimizer.optimizar_productos() porque el linprog del
        # NutrientOptimizer requiere Nutrient.cv (coefs de variación)
        # poblados en la BD, y actualmente todos están en NULL → ajustes=0
        # → productos=[]. En su lugar leemos product_contributions
        # directamente y para cada nutriente con déficit elegimos el
        # producto más eficiente. La dosis a aplicar sale de la ficha
        # técnica (typical_dose_per_ha), NO de un cálculo déficit/contribution
        # (esa fórmula producía valores absurdos — ver bug fase 4).
        # El optimizer queda intacto para limitante_nombre y para el
        # texto legacy de automatic_recommendations.
        dose_rows: list[dict] = []
        try:
            all_products = Product.query.all()
            productos_para_dosis = compute_dose_from_contributions(
                productos_contribuciones_data,
                productos_precios_data,
                nutrientes_actuales,
                demandas_ideales,
                application_type_lookup={
                    p.name: p.application_type or "unknown" for p in all_products
                },
                density_lookup={p.name: p.density_kg_per_l for p in all_products},
                price_unit_lookup={
                    pp.product.name: pp.price_unit
                    for pp in ProductPrice.query.filter(
                        ProductPrice.end_date >= datetime.utcnow().date()
                    ).all()
                },
                typical_dose_per_ha_lookup={
                    p.name: p.dose_typical_kg_per_ha
                    for p in all_products
                    if p.dose_typical_kg_per_ha is not None
                },
                typical_dose_unit_lookup={
                    p.name: p.dose_typical_unit
                    for p in all_products
                    if p.dose_typical_kg_per_ha is not None
                },
                application_mode=application_mode,
            )
        except Exception as e:
            current_app.logger.warning(
                f"[recommendation:dose] compute_dose_from_contributions falló "
                f"para lote {lot_id}: {e}. Continuando sin dosis por ha."
            )
            productos_para_dosis = []

        # Lookup batch: una sola query para resolver product_id de los nombres
        productos_lookup: dict[str, Product] = {}
        if productos_para_dosis:
            nombres = [d["product_name"] for d in productos_para_dosis]
            productos_qs = Product.query.filter(Product.name.in_(nombres)).all()
            productos_lookup = {p.name: p for p in productos_qs}

        for dose in productos_para_dosis:
            prod = productos_lookup.get(dose["product_name"])
            if prod is None:
                continue
            dose_rows.append(
                {
                    "product": prod,
                    "product_name": dose["product_name"],
                    "dose_per_ha": dose["dose_per_ha"],
                    "dose_unit": dose["dose_unit"],
                    "cost_per_ha": dose["cost_per_ha"],
                    "application_mode": dose["application_mode"],
                    "application_type": dose["application_type"],
                }
            )

        # --- Sanity checks on the optimization result (C5) ---
        sanity_warnings = []

        # Check 1: Extreme discrepancy between actual and ideal (>40x suggests unit mismatch)
        for nutrient_name in nutrientes_actuales:
            actual = nutrientes_actuales.get(nutrient_name, Decimal("0"))
            ideal = demandas_ideales.get(nutrient_name, Decimal("0"))
            if ideal > 0 and actual > 0:
                ratio = max(actual, ideal) / min(actual, ideal)
                if ratio > 40:
                    sanity_warnings.append(
                        f"Discrepancia extrema en {nutrient_name}: actual={actual}, ideal={ideal} "
                        f"(relación {ratio:.0f}:1). Verifique que ambos usan las mismas unidades."
                    )

        # Check 2: No products with valid prices
        products_without_price = [
            prod
            for prod in productos_contribuciones_data
            if prod not in productos_precios_data
            or productos_precios_data.get(prod, 0) == 0
        ]
        if products_without_price:
            sanity_warnings.append(
                f"Productos sin precio vigente (se excluyen): {', '.join(products_without_price[:5])}"
            )

        # Check 3: Nutrient limitante con suficiencia > 100% (ningún nutriente es realmente limitante)
        limitante_pct = None
        if limitante_nombre and limitante_nombre in demandas_ideales:
            act = nutrientes_actuales.get(limitante_nombre, Decimal("0"))
            ideal = demandas_ideales[limitante_nombre]
            if ideal > 0:
                limitante_pct = float((act / ideal) * 100)
                if limitante_pct > 100:
                    sanity_warnings.append(
                        f"El nutriente '{limitante_nombre}' está al {limitante_pct:.0f}% del ideal. "
                        f"Ningún nutriente es realmente limitante. La recomendación puede ser innecesaria."
                    )

        # Log sanity warnings
        for warning in sanity_warnings:
            current_app.logger.warning(
                f"[recommendation:sanity] lote={lot_id}, {warning}"
            )

        # --- Preparar datos para guardar en Recommendation ---
        report_creator = ReportView()

        # Foliar details from the chosen common_analysis
        analysis_data_for_report = report_creator._build_analysis_data(
            common_analysis, objective_id=objective_id
        )
        foliar_details_json = json.dumps(
            analysis_data_for_report.get("foliar"), default=str
        )
        soil_details_json = json.dumps(
            analysis_data_for_report.get("soil"), default=str
        )

        # Optimal comparison from the objective
        # TODO: optimal_comparison es una idea incompleta, el objetivo es que eventualmente se
        # tenga una tabla de máx y min de cada nutriente para tener alertas e incluirlo en informes
        # Formato esperado: {'Nutriente': {'min': X, 'max': Y, 'ideal': Z, 'unit': 'unidad'}}

        optimal_comparison_data = {}
        for nutrient_name, ideal_value in demandas_ideales.items():
            # Encontrar el objeto Nutrient para obtener la unidad
            nutrient_obj = next(
                (n for n in objective.nutrients if n.name == nutrient_name), None
            )
            unit = nutrient_obj.unit if nutrient_obj else "%"  # Default unit
            optimal_comparison_data[nutrient_name] = {
                "min": float(ideal_value),  # O un rango si el objetivo lo define
                "max": float(ideal_value),
                "ideal": float(ideal_value),
                "unit": unit,
            }
        optimal_comparison_json = json.dumps(optimal_comparison_data, default=str)

        # --- Ley de Mínimos ---
        minimum_law_analyses_json = None
        if minimum_law_analyses_str:
            try:
                # 1. Parsear el JSON de la tabla
                resultados_tabla = json.loads(minimum_law_analyses_str)

                # 2. Calcular nutriente limitante
                demanda_total = sum(demandas_ideales.values())
                liebig = LeyLiebig(nutrientes_actuales, demanda_total)
                nutriente_limitante = liebig.calcular_nutriente_limite(
                    nutrientes_actuales
                )

                # 3. Formatear el JSON final
                final_analysis = {
                    "nutriente_limitante": nutriente_limitante,
                    "resultados": resultados_tabla,
                }
                if comparison_label and comparison_label.strip():
                    final_analysis["comparison_label"] = comparison_label.strip()
                minimum_law_analyses_json = json.dumps(final_analysis, default=str)

            except json.JSONDecodeError:
                current_app.logger.warning(
                    "Error al decodificar minimum_law_analyses_str"
                )
            except Exception as e:
                current_app.logger.error(f"Error procesando Ley de Mínimos: {e}")

        # --- Crear y guardar la Recommendation ---
        try:
            new_recommendation = Recommendation(
                lot_id=lot_id,
                crop_id=crop_id,
                date=common_analysis.date,
                author=author_name,
                title=report_title,
                limiting_nutrient_id=limitante_nombre,
                automatic_recommendations=recomendacion_texto,
                text_recommendations="",
                optimal_comparison=optimal_comparison_json,
                soil_analysis_details=soil_details_json,
                foliar_analysis_details=foliar_details_json,
                minimum_law_analyses=minimum_law_analyses_json,
                common_analysis_id=common_analysis_id,
                applied=False,
                active=True,
            )
            db.session.add(new_recommendation)
            db.session.flush()  # necesitamos new_recommendation.id para las FKs

            # Persistir filas de dosis (una por producto en la combinación)
            for dose in dose_rows:
                db.session.add(
                    RecommendationDose(
                        recommendation_id=new_recommendation.id,
                        product_id=dose["product"].id,
                        product_name=dose["product_name"],
                        dose_per_ha=dose["dose_per_ha"],
                        dose_unit=dose["dose_unit"],
                        cost_per_ha=dose["cost_per_ha"],
                        application_mode=dose["application_mode"],
                        application_type=dose["application_type"],
                    )
                )
            db.session.commit()

            return (
                jsonify(
                    {
                        "message": "Reporte generado con éxito",
                        "report_id": new_recommendation.id,
                    }
                ),
                201,
            )

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error guardando recomendación: {str(e)}", exc_info=True
            )
            raise InternalServerError("No se pudo guardar el reporte.")


class RecommendationFilterView(MethodView):
    """Filtra recomendaciones por finca o lote vía query params.

    Retorna la lista completa de recomendaciones con sus relaciones
    (lote, cultivo) pre-cargadas para el filtro indicado.

    :param farm_id: ID de finca (opcional, int)
    :param lot_id: ID de lote (opcional, int)
    :status 200: Lista JSON de recomendaciones filtradas
    :status 400: Parámetros inválidos
    """

    def get(self):
        """Retorna recomendaciones filtradas por finca o lote.

        :param farm_id: ID de finca (query string, opcional)
        :param lot_id: ID de lote (query string, opcional)
        :status 200: Lista de recomendaciones con lote y cultivo
        :status 400: farm_id o lot_id no son enteros válidos
        """
        try:
            farm_id = int(request.args.get("farm_id", 0))
            lot_id = int(request.args.get("lot_id", 0))

            # Query para filtrar las recomendaciones
            query = Recommendation.query.options(
                db.joinedload(Recommendation.lot), db.joinedload(Recommendation.crop)
            ).filter(
                Recommendation.lot_id == lot_id
                if lot_id
                else Recommendation.lot.has(farm_id=farm_id)
            )

            recommendations = query.all()

            # Convertir a lista para serializar
            recommendations_list = list(recommendations)

            return jsonify(
                [
                    {
                        "id": rec.id,
                        "lot_id": rec.lot_id,
                        "crop_id": rec.crop_id,
                        "date": rec.date.isoformat(),
                        "author": rec.author,
                        "title": rec.title,
                        "limiting_nutrient_id": rec.limiting_nutrient_id,
                        "automatic_recommendations": rec.automatic_recommendations,
                        "text_recommendations": rec.text_recommendations,
                        "optimal_comparison": rec.optimal_comparison,
                        "minimum_law_analyses": rec.minimum_law_analyses,
                        "soil_analysis_details": rec.soil_analysis_details,
                        "foliar_analysis_details": rec.foliar_analysis_details,
                        "applied": rec.applied,
                        "active": rec.active,
                        "created_at": rec.created_at.isoformat(),
                        "updated_at": rec.updated_at.isoformat(),
                        "lot": {
                            "id": rec.lot.id,
                            "name": rec.lot.name,
                            "farm_id": rec.lot.farm_id,
                        },
                        "crop": {"id": rec.crop.id, "name": rec.crop.name},
                    }
                    for rec in recommendations_list
                ]
            )

        except ValueError:
            return jsonify({"error": "Invalid farm_id or lot_id"}), 400
        except Exception as e:
            return jsonify({"error": str(e)}), 500


class DeleteRecommendationView(MethodView):
    """Soft-delete de una recomendación por ID.

    Verifica autenticación JWT, rol del usuario (admin/reseller/org_admin/
    org_editor) y acceso multi-tenant sobre la finca del lote asociado.
    """

    @jwt_required()
    def delete(self, report_id):
        """Elimina lógicamente (active=False) una recomendación.

        :param report_id: ID de la recomendación (vía URL)
        :status 200: Reporte eliminado exitosamente
        :status 403: Usuario sin permisos o sin acceso al recurso
        :status 404: Reporte no encontrado
        """
        # Verificar autenticación y permisos (ajusta según tu lógica)
        claims = get_jwt()  # Asume que tienes una función get_jwt() para obtener claims
        if not claims or not claims.get("rol") in [
            "administrator",
            "reseller",
            "org_admin",
            "org_editor",
        ]:
            return jsonify({"error": "No autorizado"}), 403

        # Buscar el reporte
        report = Recommendation.query.get(report_id)
        if not report:
            return jsonify({"error": "Reporte no encontrado"}), 404

        # Verificar acceso al recurso
        if not check_resource_access(report.lot.farm, claims):
            return jsonify({"error": "No tienes acceso a este reporte"}), 403

        try:
            # Eliminación lógica (soft delete)
            report.active = False
            db.session.commit()
            return jsonify({"message": "Reporte eliminado exitosamente"}), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500


class FollowUpView(MethodView):
    """Crea y lista FollowUpAnalysis para una NutrientApplication."""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, application_id: int):
        """Lista los seguimientos activos de una aplicación."""
        claims = get_jwt()
        app_obj = NutrientApplication.query.get_or_404(application_id)
        if not check_resource_access(app_obj.lot.farm, claims):
            raise Forbidden("Acceso denegado.")
        follow_ups = [fu for fu in app_obj.follow_ups if fu.active]
        return (
            jsonify(
                [
                    {
                        "id": fu.id,
                        "post_analysis_id": fu.post_analysis_id,
                        "weeks_after_application": fu.weeks_after_application,
                        "notes": fu.notes,
                        "created_at": fu.created_at.isoformat(),
                    }
                    for fu in follow_ups
                ]
            ),
            200,
        )

    @check_permission(required_roles=["administrator", "reseller"])
    def post(self, application_id: int):
        """
        Registra un análisis posterior como seguimiento de una aplicación.
        Expected JSON: {"post_analysis_id": int, "notes": str (opcional)}
        """
        claims = get_jwt()
        data = request.get_json()
        if not data or "post_analysis_id" not in data:
            raise BadRequest("Falta post_analysis_id.")

        app_obj = NutrientApplication.query.get_or_404(application_id)
        if not check_resource_access(app_obj.lot.farm, claims):
            raise Forbidden("Acceso denegado.")

        post_analysis = CommonAnalysis.query.get_or_404(data["post_analysis_id"])
        if post_analysis.lot_id != app_obj.lot_id:
            raise BadRequest(
                "El análisis no pertenece al mismo lote que la aplicación."
            )

        weeks = None
        if app_obj.applied_date and post_analysis.date:
            weeks = (post_analysis.date - app_obj.applied_date).days // 7

        fu = FollowUpAnalysis(
            nutrient_application_id=application_id,
            post_analysis_id=data["post_analysis_id"],
            weeks_after_application=weeks,
            notes=data.get("notes"),
        )
        db.session.add(fu)
        db.session.commit()
        return (
            jsonify(
                {
                    "id": fu.id,
                    "weeks_after_application": fu.weeks_after_application,
                }
            ),
            201,
        )


class FollowUpComparisonView(MethodView):
    """Devuelve la comparación nutriente a nutriente para un FollowUpAnalysis."""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, follow_up_id: int):
        claims = get_jwt()
        fu = FollowUpAnalysis.query.get_or_404(follow_up_id)
        if not check_resource_access(fu.organization, claims):
            raise Forbidden("Acceso denegado.")

        recommendation = fu.nutrient_application.recommendation
        pre_analysis_id = recommendation.common_analysis_id if recommendation else None
        if not pre_analysis_id:
            raise BadRequest(
                "La aplicación no tiene recomendación con análisis base vinculado."
            )

        result = compare_analyses(pre_analysis_id, fu.post_analysis_id)
        result["follow_up_id"] = fu.id
        result["recommendation_id"] = recommendation.id if recommendation else None
        return jsonify(result), 200


class LotEvolutionView(MethodView):
    """Serie temporal de CommonAnalysis de un lote con contexto de aplicación."""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, lot_id: int):
        from sqlalchemy.orm import joinedload

        claims = get_jwt()
        lot = Lot.query.get_or_404(lot_id)
        if not check_resource_access(lot.farm, claims):
            raise Forbidden("Acceso denegado.")

        analyses = (
            CommonAnalysis.query.options(joinedload(CommonAnalysis.leaf_analysis))
            .filter_by(lot_id=lot_id)
            .order_by(CommonAnalysis.date.asc())
            .all()
        )

        # Mapear qué análisis son "post" de alguna aplicación
        follow_ups = (
            FollowUpAnalysis.query.join(NutrientApplication)
            .filter(
                NutrientApplication.lot_id == lot_id,
                FollowUpAnalysis.active == True,  # noqa: E712
            )
            .all()
        )
        post_ids = {fu.post_analysis_id: fu for fu in follow_ups}

        # Mapear qué análisis son "pre" (base de una recomendación)
        recommendations = Recommendation.query.filter_by(
            lot_id=lot_id, active=True
        ).all()
        pre_ids = {
            r.common_analysis_id for r in recommendations if r.common_analysis_id
        }

        result = []
        for a in analyses:
            role = "unclassified"
            if a.id in pre_ids:
                role = "pre_application"
            if a.id in post_ids:
                role = "post_application"

            entry = {
                "analysis_id": a.id,
                "date": str(a.date),
                "role": role,
            }
            if a.id in post_ids:
                fu = post_ids[a.id]
                entry["follow_up_id"] = fu.id
                entry["weeks_after_application"] = fu.weeks_after_application
                entry["application_id"] = fu.nutrient_application_id

            result.append(entry)

        return jsonify({"lot_id": lot_id, "timeline": result}), 200
