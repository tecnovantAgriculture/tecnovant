Analiza mi herramienta, este es su objetivo: 

El proyecto TecnoAgro consiste en un sistema de software para la gestión de datos relacionados con la nutrición foliar en cultivos diseñado para ayudar a los agricultores a optimizar el uso de nutrientes y mejorar la producción. Cómo insumo se ingresan los datos obtenidos a partir de imágenes de drones procesadas externamente y complementadas con información ingresada manualmente. 

El sistema recibe estos datos a través de una API y un formulario de ingreso, los analiza y los almacena para generar recomendaciones personalizadas basadas en parámetros locales de nutrientes. Su enfoque permite una toma de decisiones precisa, mejorando la eficiencia en el uso de recursos y la productividad agrícola.

Me hace falta desarrollar las vistas de vista_reporte que en este momento tiene datos quemados y debe ser dinámicos. trabajar en la template de listar_reportes y solicitar_informe 
Analiza y trabaja en esas vistas que están asociadas a ReportView, y en general a los archivos del folder foliage_report

Okay, let's break down the requirements for the `foliage_report` module and develop the necessary views and backend logic.

**Analysis:**

1.  **`listar_reportes.j2`:** Needs to display a list of generated `Recommendation` records. It should show key information like Title, Date, Farm/Lot, Crop, Author. Each item needs a link/button to view the detailed report (`ver_reporte`).
2.  **`solicitar_informe.j2`:** This is the report generation request form.
    *   Needs dynamic dropdowns for selecting Farm and Lot.
    *   Needs date pickers for a date range.
    *   Needs to fetch and display `CommonAnalysis` records based on the selected filters (using existing API endpoints is good).
    *   Needs a mechanism (e.g., checkboxes) to select one or more `CommonAnalysis` records to include in the report.
    *   Needs a "Generate Report" button that sends the selected analysis IDs to a new backend endpoint.
3.  **`ver_reporte.j2`:** This template is mostly designed but needs dynamic data.
    *   The corresponding backend view function (`vista_reporte`) must fetch a specific `Recommendation` record by ID.
    *   It needs to extract/deserialize the detailed analysis data (common, foliar, soil, optimal levels, calculated recommendations) stored within the `Recommendation` record (likely in JSON format within text fields).
    *   Pass this structured data to the template.
4.  **Backend (`controller.py`, `helpers.py`, `api_routes.py`):**
    *   **Report Generation Logic:** A function/method is needed to take `CommonAnalysis` ID(s), fetch all related data (Soil, Foliar, Lot, Crop, Objectives), perform calculations (status, limiting nutrient based on Liebig's Law), generate textual recommendations, and structure the final report data.
    *   **Save Report:** The generated report data needs to be saved as a new `Recommendation` record. The complex data structures (like analysis details, optimal levels comparison) should probably be stored as JSON strings in the appropriate `Recommendation` text fields (`automatic_recommendations`, `optimal_comparison`, `soil_analysis_details`, `foliar_analysis_details`).
    *   **API Endpoint for Generation:** A new POST endpoint (e.g., `/api/foliage/report/generate`) is required to receive the selected analysis IDs and trigger the generation/saving process. It should return the ID of the newly created `Recommendation`.
    *   **API Endpoint for Viewing:** The existing `/api/foliage/report/report/<id>` (`ReportView` in `helpers.py`) needs to be implemented or adapted to fetch a `Recommendation` by ID and return its *full*, deserialized data structure for potential use (though `ver_reporte.j2` might get data directly from the web route).
    *   **Web Routes:**
        *   `listar_reportes`: Fetch `Recommendation` records, serialize relevant fields (including related Lot/Crop names), and pass them to the template.
        *   `generar_informe`: Renders the `solicitar_informe.j2` template.
        *   `vista_reporte`: Accepts a `report_id`, fetches the corresponding `Recommendation`, deserializes its data, and passes it to `ver_reporte.j2`.

**Implementation Steps:**

1.  Refine `listar_reportes` view function and template.
2.  Implement JavaScript for `solicitar_informe.j2` to handle dynamic filtering and analysis selection.
3.  Create the backend report generation logic and API endpoint.
4.  Modify the `Recommendation` model if needed to better store report data (e.g., ensure Text fields can hold large JSON).
5.  Implement the `vista_reporte` backend view function to fetch and prepare data for the template.
6.  Ensure `ver_reporte.j2` uses the dynamic data correctly.

```markdown
# 1. Blueprints (__init__.py) - No changes needed, already defined.

# 2. Model to handle data (foliage/models.py)
#    - Ensure Recommendation fields (like automatic_recommendations, text_recommendations, etc.) are Text or JSON type
#      to store potentially large JSON strings. SQLAlchemy's Text type is usually sufficient.

# Example Modification in foliage/models.py (if not already Text)
# class Recommendation(db.Model):
#     ...
#     automatic_recommendations = db.Column(db.Text) # Store JSON as string
#     text_recommendations = db.Column(db.Text)
#     optimal_comparison = db.Column(db.Text)
#     minimum_law_analyses = db.Column(db.Text)
#     soil_analysis_details = db.Column(db.Text)
#     foliar_analysis_details = db.Column(db.Text)
#     ...

# 3. CRUD and helpers functionalities (foliage_report/controller.py & helpers.py)

```python
# ./modules/foliage_report/controller.py
# Python standard library imports
from functools import wraps
import json
from datetime import datetime

# Third party imports
from flask import (
    request,
    jsonify,
    Response,
    current_app,
)
from flask.views import MethodView
from flask_jwt_extended import (
    jwt_required,
    get_jwt,
)
from werkzeug.exceptions import BadRequest, NotFound, Forbidden
from sqlalchemy.orm import joinedload

# Local application imports
from app.extensions import db
from app.core.controller import check_permission, check_resource_access
from app.core.models import ResellerPackage, RoleEnum
from app.modules.foliage.models import (
    Recommendation,
    Lot,
    Farm,
    CommonAnalysis,
    LeafAnalysis,
    SoilAnalysis,
    Nutrient,
    Objective,
    Crop,
    LotCrop,
    leaf_analysis_nutrients,
    objective_nutrients,
)
from .helpers import (
    generate_full_report_data, # Assuming this function exists in helpers.py
    ReportView, # Keep existing ReportView for GET by ID
)

class ReportGeneratorView(MethodView):
    """Handles the generation and saving of new reports."""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller", "org_admin", "org_editor"])
    def post(self):
        """
        Generates a new report based on selected CommonAnalysis IDs.

        Expects JSON data:
            {
                "common_analysis_ids": [int, int, ...],
                "title": "Optional Report Title"
            }
        Returns:
            JSON: Details of the created Recommendation (report) record.
        :status 201: Report generated and saved successfully.
        :status 400: Invalid input data (missing IDs, invalid IDs).
        :status 403: Access denied to one or more analyses.
        :status 404: One or more CommonAnalysis IDs not found.
        :status 500: Error during report generation or saving.
        """
        data = request.get_json()
        if not data or "common_analysis_ids" not in data:
            raise BadRequest("Missing 'common_analysis_ids' in request.")

        common_analysis_ids = data.get("common_analysis_ids", [])
        if not isinstance(common_analysis_ids, list) or not common_analysis_ids:
            raise BadRequest("'common_analysis_ids' must be a non-empty list.")

        report_title = data.get("title", f"Reporte Generado - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        author_name = get_jwt().get("username", "Sistema") # Get username from JWT

        try:
            claims = get_jwt()
            # Fetch analyses and check permissions in one go
            analyses_to_process = []
            lots_processed = set()
            first_analysis = None

            for analysis_id in common_analysis_ids:
                common_analysis = CommonAnalysis.query.options(
                    joinedload(CommonAnalysis.lot).joinedload(Lot.farm),
                    joinedload(CommonAnalysis.leaf_analysis),
                    joinedload(CommonAnalysis.soil_analysis)
                ).get(analysis_id)

                if not common_analysis:
                    raise NotFound(f"CommonAnalysis with ID {analysis_id} not found.")

                # Check access for each analysis
                if not check_resource_access(common_analysis, claims):
                    raise Forbidden(f"Access denied to analysis ID {analysis_id}.")

                if not first_analysis:
                    first_analysis = common_analysis
                elif common_analysis.lot_id != first_analysis.lot_id:
                     raise BadRequest("All selected analyses must belong to the same Lot.")

                analyses_to_process.append(common_analysis)
                lots_processed.add(common_analysis.lot_id)

            # Ensure all selected analyses belong to the same lot - Redundant check, but safe.
            if len(lots_processed) > 1:
                raise BadRequest("All selected analyses must belong to the same Lot.")
            
            lot_id = first_analysis.lot_id
            lot = Lot.query.get(lot_id)
            if not lot:
                 raise NotFound("Associated Lot not found.") # Should not happen if analysis exists

            # Find active crop for the lot at the time of the *first* analysis (or average date?)
            analysis_date = first_analysis.date
            active_lot_crop = LotCrop.query.filter(
                LotCrop.lot_id == lot_id,
                LotCrop.start_date <= analysis_date,
                db.or_(LotCrop.end_date >= analysis_date, LotCrop.end_date.is_(None))
            ).options(db.joinedload(LotCrop.crop)).first()

            if not active_lot_crop or not active_lot_crop.crop:
                raise BadRequest(f"No active crop found for Lot ID {lot_id} on date {analysis_date}.")
            crop_id = active_lot_crop.crop_id

            # Generate the report data using the helper function
            report_content = generate_full_report_data(analyses_to_process)

            # Create and save the Recommendation record
            new_recommendation = Recommendation(
                lot_id=lot_id,
                crop_id=crop_id,
                date=datetime.utcnow().date(), # Report generation date
                author=author_name,
                title=report_title,
                limiting_nutrient_id=report_content.get("limiting_nutrient_info", {}).get("name", "N/A"),
                # Store complex data as JSON strings
                automatic_recommendations=json.dumps(report_content.get("recommendations", []), default=str),
                optimal_comparison=json.dumps(report_content.get("optimal_levels", {}), default=str),
                minimum_law_analyses=json.dumps(report_content.get("liebig_analysis", {}), default=str),
                soil_analysis_details=json.dumps(report_content.get("soil_analysis", {}), default=str),
                foliar_analysis_details=json.dumps(report_content.get("foliar_analysis", {}), default=str),
                # Add other fields if needed
            )

            db.session.add(new_recommendation)
            db.session.commit()

            # Serialize the created recommendation for the response
            serialized_report = RecommendationView()._serialize_recommendation(new_recommendation) # Reuse serialization

            return jsonify({
                "message": "Report generated successfully",
                "report_id": new_recommendation.id,
                "data": serialized_report # Optionally return the created object
            }), 201

        except (NotFound, BadRequest, Forbidden) as e:
            db.session.rollback()
            raise e # Re-raise specific HTTP exceptions
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error generating report: {e}", exc_info=True)
            return jsonify({"error": "Failed to generate report due to an internal error."}), 500

# Note: Keep the existing ReportView in helpers.py for GET /report/<id>
# It should fetch the Recommendation record and return its *full* data,
# potentially deserializing the JSON fields before sending.
# Or, modify the web route `vista_reporte` to handle this deserialization directly.

```

```python
# ./modules/foliage_report/helpers.py
# Python standard library imports
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Tuple, Any
from datetime import datetime
from statistics import mean, stdev
import json

# Third party imports
from scipy.optimize import linprog
from flask import jsonify
from flask.views import MethodView
from flask_jwt_extended import jwt_required, get_jwt
from werkzeug.exceptions import Forbidden, NotFound

# Local application imports
from app.modules.foliage.models import (
    CommonAnalysis, LeafAnalysis, SoilAnalysis, Lot, LotCrop, Objective,
    Nutrient, ProductContribution, leaf_analysis_nutrients,
    product_contribution_nutrients, objective_nutrients, Recommendation
)
from app.modules.foliage.helpers import macronutrients, micronutrients
from app.extensions import db
from app.core.models import RoleEnum, ResellerPackage
from app.core.controller import check_resource_access # Import the central access checker

# Keep LeyLiebig, NutrientOptimizer, calculat_cv_*, determinar_coeficientes_variacion,
# contribuciones_de_producto, ObjectiveResource, LeafAnalysisResource classes as they are.
# ... (Existing classes from your helpers.py file) ...
class LeyLiebig:
    """
    Clase que implementa la Ley del Mínimo de Liebig para el cálculo de nutrientes en un cultivo.
    
    La Ley del Mínimo establece que el crecimiento de una planta está limitado por el nutriente más escaso en relación
    con sus necesidades, en lugar de depender de la cantidad total de nutrientes disponibles.
    
    Esta clase permite evaluar el estado nutricional de un cultivo comparando los niveles actuales con la demanda ideal,
    identificando el nutriente más limitante y proponiendo ajustes para optimizar su disponibilidad.
    """

    def __init__(self, nutrientes: dict, demanda_planta: Decimal):
        """
        Inicializa la clase con los nutrientes disponibles y la demanda ideal de la planta.
        
        :param nutrientes: Diccionario con los nutrientes y sus valores actuales en el suelo.
        :param demanda_planta: Valor total de la demanda nutricional ideal de la planta.
        """
        self.nutrientes = nutrientes
        self.demanda_planta = Decimal(demanda_planta)

    def calcular_p(self, valor_registro: Decimal) -> Decimal:
        """
        Calcula el porcentaje de suficiencia de un nutriente con respecto a la demanda de la planta.
        
        :param valor_registro: Valor actual del nutriente en el suelo.
        :return: Porcentaje de suficiencia del nutriente con respecto a la demanda ideal.
        """
        if self.demanda_planta == 0:
            return Decimal('0.00')
        # Ensure valor_registro is Decimal
        valor_decimal = Decimal(str(valor_registro)) if not isinstance(valor_registro, Decimal) else valor_registro
        return (valor_decimal / self.demanda_planta) * Decimal('100.00')


    def calcular_i(self, mineral_p: Decimal, mineral_cv: Decimal) -> Decimal:
        """
        Calcula la cantidad de ajuste necesario para un nutriente limitante en función de su coeficiente de variación.
        
        :param mineral_p: Porcentaje de suficiencia del nutriente.
        :param mineral_cv: Coeficiente de variación del nutriente.
        :return: Cantidad de ajuste necesaria para alcanzar el nivel óptimo.
        """
        if mineral_p > Decimal('100.00'):
            result = ((mineral_p - Decimal('100.00')) * mineral_cv / Decimal('100.00'))
        else:
            result = ((Decimal('100.00') - mineral_p) * mineral_cv / Decimal('100.00'))
        return result.quantize(Decimal('0.00'), rounding=ROUND_HALF_UP)

    def calcular_r(self, mineral_p: Decimal, mineral_i: Decimal) -> Decimal:
        """
        Determina el nivel corregido del nutriente después del ajuste.
        
        :param mineral_p: Porcentaje de suficiencia del nutriente.
        :param mineral_i: Cantidad de ajuste aplicada al nutriente.
        :return: Nivel corregido del nutriente en el suelo.
        """
        if mineral_p > Decimal('100.00'):
            return (mineral_p - mineral_i).quantize(Decimal('0.00'), rounding=ROUND_HALF_UP)
        return (mineral_p + mineral_i).quantize(Decimal('0.00'), rounding=ROUND_HALF_UP)

    def calcular_nutriente_limite(self, valores_registro: dict) -> str:
        """
        Identifica el nutriente más limitante según la Ley del Mínimo de Liebig.
        
        El nutriente limitante es aquel que tiene el menor porcentaje de suficiencia.
        
        :param valores_registro: Diccionario con los valores actuales de los nutrientes en el suelo.
        :return: Nombre del nutriente más limitante.
        """
        valores_p = {mineral: self.calcular_p(valor) for mineral, valor in valores_registro.items()}
        if not valores_p:
            return "N/A" # O maneja el caso de diccionario vacío como prefieras
        return min(valores_p, key=valores_p.get)  # Devuelve el nutriente con el menor porcentaje de suficiencia


    def calcular_nutrientes(self, valores_registro: dict, valores_cv: dict) -> dict:
        """
        Calcula los ajustes necesarios para los nutrientes del cultivo.
        
        La corrección se aplica únicamente al nutriente más limitante para respetar la Ley del Mínimo de Liebig.
        
        :param valores_registro: Diccionario con los valores actuales de los nutrientes en el suelo.
        :param valores_cv: Diccionario con los coeficientes de variación de cada nutriente.
        :return: Diccionario con los valores de suficiencia (p), ajuste necesario (i) y nivel corregido (r) de cada nutriente.
        """
        nutriente_limitante = self.calcular_nutriente_limite(valores_registro)
        nutrientes = {}
        for mineral, valor_registro in valores_registro.items():
            # Ensure valor_registro is Decimal before calculations
            valor_decimal = Decimal(str(valor_registro)) if not isinstance(valor_registro, Decimal) else valor_registro
            p = self.calcular_p(valor_decimal)
            # Ensure CV is Decimal
            cv_decimal = Decimal(str(valores_cv[mineral])) if not isinstance(valores_cv[mineral], Decimal) else valores_cv[mineral]
            i = self.calcular_i(p, cv_decimal) if mineral == nutriente_limitante else Decimal('0.00')
            r = self.calcular_r(p, i)
            nutrientes[mineral] = {'p': p, 'i': i, 'r': r}
        return nutrientes

class NutrientOptimizer:
    """
    Clase que optimiza la aplicación de productos para satisfacer los requerimientos de nutrientes de un cultivo,
    basada en la Ley del Mínimo de Liebig y programación lineal.
    """

    def __init__(self, nutrientes_actuales: Dict[str, Decimal], demandas_ideales: Dict[str, Decimal],
                 productos_contribuciones: Dict[str, Dict[str, Decimal]], coeficientes_variacion: Dict[str, Decimal]):
        """
        Inicializa el optimizador de nutrientes.

        :param nutrientes_actuales: Diccionario con los niveles actuales de nutrientes (kg/ha o g/ha).
        :param demandas_ideales: Diccionario con los niveles ideales de nutrientes (kg/ha o g/ha).
        :param productos_contribuciones: Diccionario con los productos y sus contribuciones por nutriente.
        :param coeficientes_variacion: Diccionario con los coeficientes de variación por nutriente.
        """
        self.nutrientes_actuales = {k: Decimal(str(v)) for k, v in nutrientes_actuales.items()}
        self.demandas_ideales = {k: Decimal(str(v)) for k, v in demandas_ideales.items()}
        self.productos_contribuciones = {
            prod: {nut: Decimal(str(contr)) for nut, contr in contrib.items()}
            for prod, contrib in productos_contribuciones.items()
        }
        self.coeficientes_variacion = {k: Decimal(str(v)) for k, v in coeficientes_variacion.items()}
        # Ensure nutrients list comes from demandas_ideales to avoid missing keys
        self.nutrientes = list(self.demandas_ideales.keys())
        self.productos = list(self.productos_contribuciones.keys())

    def calcular_ajustes(self) -> Dict[str, Decimal]:
        """
        Calcula los ajustes necesarios (déficit absoluto) para cada nutriente.
        No aplica la corrección por CV aquí, solo calcula la diferencia necesaria.
        """
        ajustes = {}
        for nutriente in self.nutrientes:
            actual = self.nutrientes_actuales.get(nutriente, Decimal('0.0'))
            ideal = self.demandas_ideales.get(nutriente, Decimal('0.0')) # Use get for safety
            # Solo calcular ajuste si hay déficit
            if actual < ideal:
                ajustes[nutriente] = ideal - actual
            else:
                ajustes[nutriente] = Decimal('0.0')
        return ajustes

    def identificar_limitante(self) -> str:
        """
        Identifica el nutriente más limitante según la Ley de Liebig.
        """
        porcentajes = {}
        for nutriente in self.nutrientes:
             actual = self.nutrientes_actuales.get(nutriente, Decimal('0.0'))
             ideal = self.demandas_ideales.get(nutriente) # Use get
             if ideal is None or ideal <= 0:
                 porcentajes[nutriente] = Decimal('Infinity') # Or handle appropriately
             else:
                 porcentajes[nutriente] = (actual / ideal) * Decimal('100.0')

        if not porcentajes:
            return "N/A"
        # Find the nutrient with the minimum percentage (most limiting)
        return min(porcentajes, key=porcentajes.get)


    def optimizar_productos(self) -> Tuple[Dict[str, Decimal], Dict[str, Decimal]]:
        """
        Optimiza las cantidades de productos a aplicar usando programación lineal.

        :return: Tupla (cantidades de productos, nutrientes aportados).
        """
        ajustes_requeridos = self.calcular_ajustes() # Cantidad que falta de cada nutriente

        # Nutrientes que necesitan ajuste
        nutrientes_a_ajustar = {n: v for n, v in ajustes_requeridos.items() if v > 0}
        if not nutrientes_a_ajustar:
            return {}, {n: Decimal('0.0') for n in self.nutrientes} # No se necesita ajuste

        # Coeficientes de la función objetivo (minimizar la suma de productos aplicados)
        c = [1.0] * len(self.productos) # Usar floats para linprog

        # Matriz de restricciones de igualdad (A_eq): Contribución de cada producto a cada nutriente
        A_eq_list = []
        b_eq_list = []

        for nutriente, ajuste_necesario in nutrientes_a_ajustar.items():
            fila = []
            for prod in self.productos:
                # Obtener contribución, convertir a float
                contrib = float(self.productos_contribuciones[prod].get(nutriente, Decimal('0.0')))
                fila.append(contrib)
            A_eq_list.append(fila)
            b_eq_list.append(float(ajuste_necesario)) # Cantidad necesaria como float

        # Límites de las variables (cantidades de productos >= 0)
        bounds = [(0, None)] * len(self.productos)

        # Resolver el problema de programación lineal
        # Usamos A_eq y b_eq para asegurar que la suma de contribuciones = ajuste necesario
        res = linprog(c, A_eq=A_eq_list, b_eq=b_eq_list, bounds=bounds, method='highs') # 'highs' es un solver eficiente

        if not res.success:
            # Considerar una aproximación o informar que no hay solución exacta
            # Podría ser que ningún producto aporte el nutriente necesario o combinaciones no funcionen
             print(f"Optimización fallida: {res.message}")
             # Fallback: ¿Quizás calcular solo para el limitante? ¿O usar A_ub >= b_ub?
             # Por ahora, retornamos vacío o lanzamos error
             # return {}, {n: Decimal('0.0') for n in self.nutrientes} # Opcional: retornar vacío
             raise ValueError(f"No se pudo optimizar la aplicación de productos: {res.message}")


        # Resultados: cantidades de productos (convertir de float a Decimal)
        cantidades = {self.productos[i]: Decimal(str(round(x, 2))) for i, x in enumerate(res.x)}

        # Calcular nutrientes aportados
        nutrientes_aportados = {nutriente: Decimal('0.0') for nutriente in self.nutrientes}
        for prod, cantidad in cantidades.items():
            if cantidad > Decimal('0.0'): # Solo considerar productos aplicados
                for nutriente, contrib in self.productos_contribuciones[prod].items():
                    if nutriente in nutrientes_aportados: # Asegurar que el nutriente existe
                         nutrientes_aportados[nutriente] += contrib * cantidad


        return cantidades, nutrientes_aportados

    def generar_recomendacion(self, lot_id: int) -> Tuple[str, Dict]:
        """
        Genera una recomendación textual y un resumen estructurado para aplicar en el lote.

        :param lot_id: ID del lote donde se aplicará la recomendación.
        :return: Tupla (Texto de la recomendación, Diccionario con resumen estructurado).
        """
        try:
            cantidades, nutrientes_aportados = self.optimizar_productos()

            # Generar texto de recomendación
            lineas = [f"Aplicar en el lote {lot_id}:"]
            productos_aplicar = {prod: cant for prod, cant in cantidades.items() if cant > 0}
            if not productos_aplicar:
                 lineas.append("- No se requiere aplicación de productos según el cálculo.")
            else:
                 for prod, cantidad in productos_aplicar.items():
                    lineas.append(f"- {cantidad.quantize(Decimal('0.01'))} unidades de {prod}") # Formatear decimal

            lineas.append("\nNutrientes aportados estimados:")
            for nutriente, cantidad in nutrientes_aportados.items():
                if cantidad > Decimal('0.0'): # Solo mostrar nutrientes aportados
                    # Determinar la unidad correcta
                    is_macro = any(n['name'] == nutriente for n in macronutrients)
                    unidad = "kg/ha" if is_macro else "g/ha"
                    lineas.append(f"- {nutriente}: {cantidad.quantize(Decimal('0.01'))} {unidad}") # Formatear decimal

            recomendacion_texto = "\n".join(lineas)

            # Generar resumen estructurado
            recomendacion_resumen = {
                "lot_id": lot_id,
                "productos_recomendados": [
                    {"producto": prod, "cantidad": str(cantidad.quantize(Decimal('0.01')))} # Guardar como string
                    for prod, cantidad in productos_aplicar.items()
                ],
                "nutrientes_aportados": [
                    {"nutriente": nutriente, "cantidad": str(cantidad.quantize(Decimal('0.01'))), "unidad": "kg/ha" if any(n['name'] == nutriente for n in macronutrients) else "g/ha"}
                    for nutriente, cantidad in nutrientes_aportados.items() if cantidad > 0
                ]
            }

            return recomendacion_texto, recomendacion_resumen

        except ValueError as e:
            # Si la optimización falló
            error_message = f"No se pudo generar la recomendación para el lote {lot_id}: {e}"
            return error_message, {"error": str(e)}
        except Exception as e:
            # Otros errores inesperados
            error_message = f"Error inesperado al generar la recomendación para el lote {lot_id}: {e}"
            return error_message, {"error": "Error interno del servidor"}


def calcular_cv_nutriente(lot_id: int, nutriente_name: str) -> Decimal:
    """Calcula el Coeficiente de Variación (CV) para un nutriente específico en un lote."""
    nutrient = Nutrient.query.filter_by(name=nutriente_name).first()
    if not nutrient:
        return Decimal('0.3') # Default si el nutriente no existe

    # Obtener valores históricos de LeafAnalysis para el lote y nutriente
    valores = db.session.query(leaf_analysis_nutrients.c.value)\
        .join(LeafAnalysis, leaf_analysis_nutrients.c.leaf_analysis_id == LeafAnalysis.id)\
        .join(CommonAnalysis, LeafAnalysis.common_analysis_id == CommonAnalysis.id)\
        .filter(CommonAnalysis.lot_id == lot_id)\
        .filter(leaf_analysis_nutrients.c.nutrient_id == nutrient.id)\
        .order_by(CommonAnalysis.date.desc())\
        .limit(10) # Considerar los últimos 10 análisis, por ejemplo
        .all()

    valores_float = [float(v[0]) for v in valores if v[0] is not None]

    if len(valores_float) < 3: # Necesitamos al menos 3 puntos para un CV más fiable
        # Asignar CV por defecto basado en literatura si no hay suficientes datos
        if nutriente_name in ["Nitrógeno"]: return Decimal("0.5")
        if nutriente_name in ["Fósforo"]: return Decimal("0.3")
        if nutriente_name in ["Potasio"]: return Decimal("0.4")
        if nutriente_name in ["Cobre", "Zinc"]: return Decimal("0.25")
        return Decimal("0.3") # Default genérico

    try:
        mu = mean(valores_float)
        if mu == 0:
            return Decimal('0.3') # Evitar división por cero, usar default
        sigma = stdev(valores_float)
        cv = Decimal(str(sigma / mu))
        # Limitar el CV a un rango razonable (ej. 0.05 a 1.0)
        return max(Decimal('0.05'), min(cv, Decimal('1.0'))).quantize(Decimal('0.01'))
    except Exception:
         return Decimal('0.3') # Fallback en caso de error estadístico


def determinar_coeficientes_variacion(lot_id: int) -> Dict[str, Decimal]:
    """Determina los coeficientes de variación para todos los nutrientes en un lote."""
    coeficientes = {}
    # Obtener todos los nombres de nutrientes de la base de datos
    all_nutrients = Nutrient.query.with_entities(Nutrient.name).all()
    nutrient_names = [n[0] for n in all_nutrients]

    for nutriente_name in nutrient_names:
        coeficientes[nutriente_name] = calcular_cv_nutriente(lot_id, nutriente_name)

    return coeficientes


def contribuciones_de_producto() -> Dict[str, Dict[str, Decimal]]:
    """Obtiene las contribuciones de nutrientes para todos los productos."""
    product_contributions = ProductContribution.query.options(
        db.joinedload(ProductContribution.product) # Eager load product
    ).all()

    result = {}
    for pc in product_contributions:
        product_name = pc.product.name
        if product_name not in result:
            result[product_name] = {}

        # Fetch nutrient contributions efficiently
        nutrient_contributions_data = db.session.query(
                product_contribution_nutrients.c.nutrient_id,
                product_contribution_nutrients.c.contribution
            ).filter_by(product_contribution_id=pc.id).all()

        # Cache nutrient names
        nutrient_cache = {n.id: n.name for n in Nutrient.query.all()}

        for nutrient_id, contribution in nutrient_contributions_data:
            nutrient_name = nutrient_cache.get(nutrient_id)
            if nutrient_name and contribution is not None:
                result[product_name][nutrient_name] = Decimal(str(contribution))
            elif nutrient_name:
                 result[product_name][nutrient_name] = Decimal('0.0') # Default if contribution is None

    return result


# --- Resource Fetching Classes (Simplified) ---

class ObjectiveResource:
    """Fetches objective data."""
    def get_objective_for_crop(self, crop_id: int) -> Dict[str, Decimal]:
        """Gets the nutrient targets for a specific crop."""
        objective = Objective.query.filter_by(crop_id=crop_id).first()
        if not objective:
            return {} # Return empty if no objective found for the crop

        targets_query = db.session.query(objective_nutrients).filter_by(objective_id=objective.id).all()
        nutrient_targets = {}
        nutrient_cache = {n.id: n.name for n in Nutrient.query.all()} # Cache names

        for target in targets_query:
            nutrient_name = nutrient_cache.get(target.nutrient_id)
            if nutrient_name and target.target_value is not None:
                nutrient_targets[nutrient_name] = Decimal(str(target.target_value))
            elif nutrient_name:
                nutrient_targets[nutrient_name] = Decimal('0.0') # Default if target_value is None

        return nutrient_targets

class LeafAnalysisResource:
    """Fetches leaf analysis data."""
    def get_leaf_analysis_for_common(self, common_analysis_id: int) -> Dict[str, Decimal]:
        """Gets the nutrient values for a specific leaf analysis linked to a common analysis."""
        leaf_analysis = LeafAnalysis.query.filter_by(common_analysis_id=common_analysis_id).first()
        if not leaf_analysis:
            return {} # Return empty if no leaf analysis found

        values_query = db.session.query(leaf_analysis_nutrients).filter_by(leaf_analysis_id=leaf_analysis.id).all()
        nutrient_values = {}
        nutrient_cache = {n.id: n.name for n in Nutrient.query.all()} # Cache names

        for val in values_query:
            nutrient_name = nutrient_cache.get(val.nutrient_id)
            if nutrient_name and val.value is not None:
                nutrient_values[nutrient_name] = Decimal(str(val.value))
            elif nutrient_name:
                 nutrient_values[nutrient_name] = Decimal('0.0') # Default if value is None


        return nutrient_values

# --- Main Report Generation Function ---

def generate_full_report_data(common_analyses: List[CommonAnalysis]) -> Dict[str, Any]:
    """
    Generates a comprehensive report structure based on a list of CommonAnalysis objects.
    Assumes all analyses belong to the same Lot.
    """
    if not common_analyses:
        return {"error": "No analyses provided"}

    # Use the first analysis to determine Lot and Crop context
    first_analysis = common_analyses[0]
    lot_id = first_analysis.lot_id
    lot = first_analysis.lot # Assumes relation is loaded
    if not lot:
         lot = Lot.query.get(lot_id) # Fallback query
         if not lot: return {"error": "Lot not found"}


    # Find the active crop for the lot at the time of the first analysis
    analysis_date = first_analysis.date
    active_lot_crop = LotCrop.query.filter(
        LotCrop.lot_id == lot_id,
        LotCrop.start_date <= analysis_date,
        db.or_(LotCrop.end_date >= analysis_date, LotCrop.end_date.is_(None))
    ).options(db.joinedload(LotCrop.crop)).first()

    if not active_lot_crop or not active_lot_crop.crop:
        return {"error": f"No active crop found for Lot {lot.name} on {analysis_date}"}
    crop_id = active_lot_crop.crop_id
    crop_name = active_lot_crop.crop.name

    # --- Fetch Necessary Data ---
    objective_resource = ObjectiveResource()
    leaf_analysis_resource = LeafAnalysisResource()
    productos_contrib = contribuciones_de_producto()
    coeficientes_var = determinar_coeficientes_variacion(lot_id)
    demandas_ideales = objective_resource.get_objective_for_crop(crop_id)

    # Aggregate data from all provided common analyses
    # For simplicity, let's use the *first* analysis for foliar/soil details in this example
    # A more complex approach could average values or show ranges.
    nutrientes_actuales_foliar = leaf_analysis_resource.get_leaf_analysis_for_common(first_analysis.id)
    soil_data = first_analysis.soil_analysis # Assuming loaded

    # Ensure all required keys are present in demandas_ideales, even if 0
    all_nutrient_names = set(coeficientes_var.keys())
    for nutrient_name in all_nutrient_names:
        if nutrient_name not in demandas_ideales:
            demandas_ideales[nutrient_name] = Decimal('0.0')
        if nutrient_name not in nutrientes_actuales_foliar:
            nutrientes_actuales_foliar[nutrient_name] = Decimal('0.0')

    # --- Perform Calculations ---
    optimizer = NutrientOptimizer(
        nutrientes_actuales_foliar,
        demandas_ideales,
        productos_contrib,
        coeficientes_var
    )
    limitante_info = {"name": "N/A", "percentage": 100.0}
    try:
        limitante_nombre = optimizer.identificar_limitante()
        if limitante_nombre != "N/A":
            ideal = demandas_ideales.get(limitante_nombre, Decimal('0.0'))
            actual = nutrientes_actuales_foliar.get(limitante_nombre, Decimal('0.0'))
            percentage = (actual / ideal) * 100 if ideal > 0 else 0
            limitante_info = {
                "name": limitante_nombre,
                "value": actual,
                "optimal": ideal,
                "percentage": float(percentage.quantize(Decimal('0.1'))),
                "type": "foliar" # Assuming based on optimizer input
            }
    except Exception as e:
        print(f"Error identifying limiting nutrient: {e}")


    recomendacion_texto, recomendacion_resumen = optimizer.generar_recomendacion(lot_id)

    # --- Structure the Report Data ---
    report_structure = {
        "lot_info": {
            "lot_id": lot_id,
            "lot_name": lot.name,
            "farm_name": lot.farm.name if lot.farm else "N/A",
            "crop_name": crop_name,
        },
        "common_analysis_summary": [ # List of summaries
             {
                 "id": ca.id,
                 "date": ca.date.isoformat(),
                 "protein": float(ca.protein) if ca.protein else None,
                 "rest": float(ca.rest) if ca.rest else None,
                 "rest_days": ca.rest_days,
                 "month": ca.month,
                 "yield_estimate": float(ca.yield_estimate) if ca.yield_estimate else None, # Aforo
             } for ca in common_analyses
        ],
         "foliar_analysis": { # Using first analysis for detail view
             "id": first_analysis.leaf_analysis.id if first_analysis.leaf_analysis else None,
             "nutrients": {k: float(v) for k, v in nutrientes_actuales_foliar.items()}
         },
        "soil_analysis": { # Using first analysis for detail view
            "id": soil_data.id if soil_data else None,
            "energy": float(soil_data.energy) if soil_data and soil_data.energy else None,
            "grazing": soil_data.grazing if soil_data else None,
            # Add other soil fields if available and needed (pH, MO, etc.)
            # "ph": float(soil_data.ph) if soil_data and soil_data.ph else None,
        },
        "optimal_levels": {
            "crop": crop_name,
            "targets": {k: float(v) for k, v in demandas_ideales.items()}
        },
         "liebig_analysis": {
             "limiting_nutrient": limitante_info["name"],
             "limiting_percentage": limitante_info["percentage"]
         },
        "recommendations": recomendacion_resumen, # Structured recommendation
        "recommendation_text": recomendacion_texto # Textual recommendation
        # Add historical data section if needed
    }

    return report_structure



# Keep existing ReportView for GET /report/<id>
class ReportView(MethodView):
    """Fetches and returns the data for a specific generated report."""
    decorators = [jwt_required()]

    def get(self, id):
        """
        Retrieve the full data for a specific report (Recommendation).
        Args:
            id (int): The ID of the Recommendation record.
        Returns:
            JSON: The detailed report data, deserialized from the Recommendation record.
        :status 200: Report data retrieved successfully.
        :status 403: Access denied.
        :status 404: Report not found.
        """
        recommendation = Recommendation.query.options(
            db.joinedload(Recommendation.lot).joinedload(Lot.farm),
            db.joinedload(Recommendation.crop)
        ).get_or_404(id)

        # Check access
        claims = get_jwt()
        if not check_resource_access(recommendation, claims):
            raise Forbidden("You do not have access to this report.")

        # Deserialize JSON data stored in the recommendation
        try:
            report_data = {
                "report_info": {
                     "id": recommendation.id,
                     "title": recommendation.title,
                     "author": recommendation.author,
                     "date_generated": recommendation.date.isoformat(),
                     "date_created": recommendation.created_at.isoformat(),
                     "lot_id": recommendation.lot_id,
                     "lot_name": recommendation.lot.name if recommendation.lot else "N/A",
                     "farm_name": recommendation.lot.farm.name if recommendation.lot and recommendation.lot.farm else "N/A",
                     "crop_id": recommendation.crop_id,
                     "crop_name": recommendation.crop.name if recommendation.crop else "N/A",
                     "applied": recommendation.applied
                },
                "limiting_nutrient_info": {"name": recommendation.limiting_nutrient_id}, # Simplified for now
                "recommendations": json.loads(recommendation.automatic_recommendations or '{}'),
                "recommendation_text": recommendation.text_recommendations,
                "optimal_levels": json.loads(recommendation.optimal_comparison or '{}'),
                "liebig_analysis": json.loads(recommendation.minimum_law_analyses or '{}'),
                "soil_analysis": json.loads(recommendation.soil_analysis_details or '{}'),
                "foliar_analysis": json.loads(recommendation.foliar_analysis_details or '{}'),
                # Add other sections like historical data if stored
            }
             # Attempt to parse Decimal strings back to Decimal if needed downstream,
             # but for JSON response, strings are fine.
        except json.JSONDecodeError as e:
            return jsonify({"error": f"Failed to parse stored report data: {e}"}), 500
        except Exception as e:
             return jsonify({"error": f"An unexpected error occurred: {e}"}), 500


        return jsonify(report_data), 200

```

```python
# ./modules/foliage_report/api_routes.py
from . import foliage_report_api as api
from .helpers import ReportView # Keep for GET by ID
from .controller import ReportGeneratorView # Import the new generator view
from app.core.controller import login_required, check_resource_access
from app.core.models import Organization
from flask import jsonify, request
from flask_jwt_extended import get_jwt
from app.modules.foliage.models import Farm, Lot, CommonAnalysis, Nutrient
from app.extensions import db
from datetime import datetime

# Endpoint to GET a specific report by ID
report_view = ReportView.as_view("report_view")
api.add_url_rule("/report/<int:id>", view_func=report_view, methods=["GET"])

# Endpoint to POST and generate a new report
report_generator_view = ReportGeneratorView.as_view("report_generator")
api.add_url_rule("/generate_report", view_func=report_generator_view, methods=["POST"])


# --- Keep existing helper endpoints ---

@api.route('/prueba', methods=['GET'])
def get_prueba():
    """Test endpoint for debugging request object."""
    atributos = dir(request)
    atributos_str = '<br>'.join(atributos)
    return f'Métdos y atributos del objeto request: <br>{atributos_str} <br>Se encuentra activado el modo debug'


@api.route('/get-farms')
@jwt_required()
def get_farms():
    """API endpoint to get farms accessible by the current user."""
    claims = get_jwt()
    farms = Farm.query.join(Organization).all() # Start with all farms
    accessible_farms = [f for f in farms if check_resource_access(f, claims)]

    return jsonify([
        {'id': farm.id, 'name': farm.name}
        for farm in accessible_farms
    ])

@api.route('/get-lots')
@jwt_required()
def get_lots():
    """API endpoint to get lots for a specific farm, checking access."""
    claims = get_jwt()
    farm_id = request.args.get('farm_id')
    if not farm_id:
        return jsonify({'error': 'farm_id parameter is required'}), 400

    try:
        farm_id = int(farm_id)
    except ValueError:
        return jsonify({'error': 'farm_id must be an integer'}), 400

    farm = Farm.query.get(farm_id)
    if not farm:
        # Return empty list if farm doesn't exist, or 404? Empty list is safer for frontend.
        return jsonify([])

    # Verify if the user has access to this specific farm
    if not check_resource_access(farm, claims):
        return jsonify([]) # Return empty list if no access

    lots = Lot.query.filter_by(farm_id=farm_id).all()

    return jsonify([
        {'id': lot.id, 'name': lot.name}
        for lot in lots
    ])

@api.route('/analyses')
@jwt_required()
def get_analyses():
    """
    API endpoint to fetch CommonAnalysis records based on filters,
    checking access for each record.
    """
    claims = get_jwt()
    farm_id = request.args.get('farm_id')
    lot_id = request.args.get('lot_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # Build the query with necessary joins
    query = CommonAnalysis.query.options(
        db.joinedload(CommonAnalysis.lot).joinedload(Lot.farm).joinedload(Farm.organization), # Load necessary relations
        # No need to load soil/leaf here if not immediately needed for filtering/display list
    ).join(Lot, CommonAnalysis.lot_id == Lot.id)\
     .join(Farm, Lot.farm_id == Farm.id)

    # Apply filters
    if farm_id:
        try:
            query = query.filter(Farm.id == int(farm_id))
        except ValueError:
             return jsonify({'error': 'Invalid farm_id'}), 400
    if lot_id:
         try:
            query = query.filter(Lot.id == int(lot_id))
         except ValueError:
             return jsonify({'error': 'Invalid lot_id'}), 400
    if start_date:
        try:
            start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(CommonAnalysis.date >= start_dt)
        except ValueError:
            return jsonify({'error': 'Invalid start_date format (YYYY-MM-DD)'}), 400
    if end_date:
        try:
            end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(CommonAnalysis.date <= end_dt)
        except ValueError:
            return jsonify({'error': 'Invalid end_date format (YYYY-MM-DD)'}), 400

    # Execute query and filter results based on access
    all_analyses = query.order_by(CommonAnalysis.date.desc()).all()
    accessible_analyses = [
        analysis for analysis in all_analyses if check_resource_access(analysis, claims)
    ]

    # Prepare the response data
    analyses_data = []
    for analysis in accessible_analyses:
        analyses_data.append({
            'id': analysis.id,
            'date': analysis.date.strftime('%Y-%m-%d'),
            'farm_name': analysis.lot.farm.name if analysis.lot and analysis.lot.farm else 'N/A',
            'lot_name': analysis.lot.name if analysis.lot else 'N/A',
            # Add other relevant fields for the list view if needed
            # 'protein': analysis.protein,
        })

    return jsonify(analyses_data)

```

```python
# ./modules/foliage_report/web_routes.py
import json
from decimal import Decimal
from datetime import datetime # Ensure datetime is imported

from flask import render_template, url_for, request, jsonify # Added jsonify
from flask_jwt_extended import get_jwt # Import get_jwt

from . import foliage_report as web
from .helpers import (
    # Keep relevant calculation functions if they are used directly here
    # calcular_cv_nutriente, determinar_coeficientes_variacion,
    # contribuciones_de_producto, ObjectiveResource, LeafAnalysisResource, NutrientOptimizer,
    ReportView # Keep ReportView for potential use or if it has web methods
)
from app.modules.foliage.models import Recommendation, Farm, Lot, CommonAnalysis, Crop # Import models needed
from app.core.controller import login_required, check_resource_access
from app.core.models import RoleEnum, ResellerPackage, Organization # Import core models

def get_dashboard_menu():
    """Define el menu superior en los templates"""
    return {
        "menu": [
            {"name": "Home", "url": url_for("core.index")},
            {"name": "Logout", "url": url_for("core.logout")},
            {"name": "Profile", "url": url_for("core.profile")},
        ]
    }


@web.route("listar_reportes")
@login_required
def listar_reportes():
    """
    Página: Renderiza la vista de listado de reportes (Recomendaciones)
    """
    context = {
        "dashboard": True,
        "title": "Informes de Análisis - TecnoAgro",
        "description": "Lista de informes generados.",
        "author": "Johnny De Castro",
        "site_title": "Listado de Informes",
        "data_menu": get_dashboard_menu(),
    }

    claims = get_jwt()
    user_role = claims.get("rol")
    user_id = claims.get("id")
    user_org_ids = [org['id'] for org in claims.get("organizations", [])] # Get org IDs user belongs to

    # Base query
    query = Recommendation.query.options(
        db.joinedload(Recommendation.lot).joinedload(Lot.farm).joinedload(Farm.organization),
        db.joinedload(Recommendation.crop)
    ).order_by(Recommendation.date.desc())

    # Filter based on role
    if user_role == RoleEnum.ADMINISTRATOR.value:
        # Admins see all active reports
        query = query.filter(Recommendation.active == True)
    elif user_role == RoleEnum.RESELLER.value:
        # Resellers see reports from their managed organizations
        reseller_package = ResellerPackage.query.filter_by(reseller_id=user_id).first()
        if reseller_package:
            org_ids = [org.id for org in reseller_package.organizations]
            query = query.join(Lot, Recommendation.lot_id == Lot.id)\
                         .join(Farm, Lot.farm_id == Farm.id)\
                         .filter(Farm.org_id.in_(org_ids))\
                         .filter(Recommendation.active == True)
        else:
            query = query.filter(Recommendation.id == -1) # No reports if no package
    else: # ORG_ADMIN, ORG_EDITOR, ORG_VIEWER
        # Org users see reports from their organizations
         if user_org_ids:
            query = query.join(Lot, Recommendation.lot_id == Lot.id)\
                         .join(Farm, Lot.farm_id == Farm.id)\
                         .filter(Farm.org_id.in_(user_org_ids))\
                         .filter(Recommendation.active == True)
         else:
              query = query.filter(Recommendation.id == -1) # No reports if no org

    reportes = query.all()

    # Serialize data for the template
    items = []
    for r in reportes:
        items.append({
            "id": r.id,
            "title": r.title,
            "finca_lote": f"{r.lot.farm.name if r.lot and r.lot.farm else 'N/A'} / {r.lot.name if r.lot else 'N/A'}",
            "crop": r.crop.name if r.crop else 'N/A',
            "date": r.date.strftime('%Y-%m-%d') if r.date else 'N/A',
            "author": r.author,
            "active": r.active, # Include active status
             # Add org_id for potential frontend filtering/checks if needed
            "org_id": r.lot.farm.org_id if r.lot and r.lot.farm else None
        })

    context['items'] = items
    context['total_informes'] = len(items)
    context['reports'] = True # Flag to show the 'create' button correctly

    # Add necessary variables for crud_base template, even if not fully used
    context['entity_name'] = "Reportes"
    context['entity_name_lower'] = "reporte"
    context['show_select_box'] = False # No bulk actions needed here
    context['show_view_button'] = True # To link to the detailed view
    context['api_url'] = '#' # No direct API CRUD for listing here
    context['form_fields'] = {} # No form needed in the modal here

    return render_template("listar_reportes.j2", **context, request=request)

@web.route("/vista_reporte/<int:report_id>")
@login_required
def vista_reporte(report_id):
    """
    Página: Renderiza la vista detallada de un reporte (Recomendación)
    """
    context = {
        "dashboard": True,
        "title": "Detalle de Informe - TecnoAgro",
        "description": "Visualización detallada del informe de análisis.",
        "author": "Johnny De Castro",
        "site_title": "Ver Informe",
        "data_menu": get_dashboard_menu(),
    }

    recommendation = Recommendation.query.options(
        db.joinedload(Recommendation.lot).joinedload(Lot.farm),
        db.joinedload(Recommendation.crop)
    ).get_or_404(report_id)

    # Check access
    claims = get_jwt()
    if not check_resource_access(recommendation, claims):
        return render_template("dashboard/not_authorized.j2", **context), 403

    # --- Deserialize stored JSON data ---
    try:
        # Use helper functions or methods to deserialize and structure
        analysisData = {
            "common": json.loads(recommendation.text_recommendations or '{}').get("common_analysis_summary", {}), # Example structure
            "foliar": json.loads(recommendation.foliar_analysis_details or '{}'),
            "soil": json.loads(recommendation.soil_analysis_details or '{}')
        }
        optimalLevels = json.loads(recommendation.optimal_comparison or '{}')
        recommendations_list = json.loads(recommendation.automatic_recommendations or '[]')
        limiting_nutrient_info = json.loads(recommendation.minimum_law_analyses or '{}').get("limiting_nutrient_info", {})
        historicalData = [] # TODO: Fetch actual historical data if needed/stored

        # Simple Nutrient Names mapping (adjust if needed)
        nutrientNames = {n.symbol: n.name for n in Nutrient.query.all()}
        # Add more mappings if keys are different (e.g., 'materiaOrganica')
        nutrientNames.update({
             'materiaOrganica': 'Materia Orgánica',
             'cic': 'CIC',
             'ph': 'pH'
             # Add others as stored in your JSON
        })


    except json.JSONDecodeError:
        # Handle error if JSON parsing fails
        # Log the error and potentially show a message to the user
        return render_template("error.j2", e_description="Error al procesar datos del reporte"), 500
    except Exception as e:
        # Catch other potential errors during data preparation
        return render_template("error.j2", e_description=f"Error inesperado: {e}"), 500


    # --- Prepare Chart Data (Example based on your hardcoded logic) ---
    # Foliar Chart
    foliarChartData = []
    if analysisData.get("foliar") and optimalLevels.get("nutrientes"):
        foliar_analysis = analysisData["foliar"]
        optimal_foliar = optimalLevels["nutrientes"] # Assuming structure
        for nutrient_key, nutrient_data in optimal_foliar.items():
             # Find nutrient symbol or name for matching
             actual_value = foliar_analysis.get(nutrient_key)
             nutrient_record = Nutrient.query.filter(Nutrient.name.ilike(nutrient_key)).first() # Case-insensitive match
             symbol = nutrient_record.symbol if nutrient_record else nutrient_key[:2].upper() # Fallback symbol

             if actual_value is not None and isinstance(nutrient_data, dict) and 'min' in nutrient_data and 'max' in nutrient_data:
                 foliarChartData.append({
                     "name": symbol,
                     "actual": float(actual_value),
                     "min": float(nutrient_data["min"]),
                     "max": float(nutrient_data["max"])
                 })

    # Soil Chart (similar logic - adapt keys as needed)
    soilChartData = []
    # ... (Add logic to build soilChartData similarly, mapping keys)


    # Pass deserialized and prepared data to the template
    context.update({
        "analysisData": analysisData,
        "optimalLevels": optimalLevels,
        "foliarChartData": foliarChartData,
        "soilChartData": soilChartData,
        "historicalData": historicalData,
        "nutrientNames": nutrientNames,
        "limitingNutrient": limiting_nutrient_info if limiting_nutrient_info.get("name") != "N/A" else None,
        "recommendations": recommendations_list,
        "report_info": { # Pass basic report info too
             "title": recommendation.title,
             "date": recommendation.date.isoformat(),
             "finca": recommendation.lot.farm.name if recommendation.lot and recommendation.lot.farm else "N/A",
             "lote": recommendation.lot.name if recommendation.lot else "N/A",
        }
    })

    return render_template('ver_reporte.j2', **context, request=request)


@web.route("/solicitar_informe")
@login_required
def generar_informe():
    """
    Página: Renderiza el formulario para solicitar la generación de un informe.
    """
    context = {
        "dashboard": True,
        "title": "Solicitar Informe de Análisis - TecnoAgro",
        "description": "Seleccione los análisis para generar un nuevo informe.",
        "author": "Johnny De Castro",
        "site_title": "Generar Informe",
        "data_menu": get_dashboard_menu(),
    }
    # Pass any necessary initial data, like list of farms for the first dropdown
    # The rest will be loaded via JS using the API endpoints
    return render_template("solicitar_informe.j2", **context, request=request)

```

```html
{# ./modules/foliage_report/templates/listar_reportes.j2 #}
{% extends "layouts/crud_base.j2" %}

{# --- Template Configuration --- #}
{% set entity_name = "Reportes" %} {# Display name for the entity type #}
{% set entity_name_lower = "reporte" %} {# Lowercase singular name #}
{% set title = "Listado de Informes Generados" %} {# Page title #}
{% set show_select_box = True %} {# Show checkboxes for bulk actions #}
{% set show_view_button = True %} {# Show 'View' button in dropdown #}
{% set show_edit_button = False %} {# Disable 'Edit' button (reports likely not directly editable) #}

{# --- Table Configuration --- #}
{% set table_headers = ["ID", "Título", "Finca / Lote", "Cultivo", "Fecha Informe", "Autor", "Estado"] %}
{% set item_fields = ["id", "title", "finca_lote", "crop", "date", "author", "active" ] %} {# Corresponds to keys in serialized 'items' #}

{# --- Form Configuration (Not used for listing, but required by base) --- #}
{% set form_fields = {} %} {# No form fields needed for modals on this page #}
{% set api_url = url_for('foliage_report_api.report_view') %} {# Base URL, deletion might use this #}

{# --- Custom Actions --- #}
{# Override the action dropdown to customize actions for reports #}
{% macro action_dropdown(item_id) %}
<div class="relative inline-block text-left">
    <div>
        <button type="button" class="{{ base_button_classes }} {{ border_color }} {{ bg_color }} {{ text_color }} {{ hover_bg_color }} {{ focus_ring_color }}" id="options-menu-{{ item_id }}" aria-haspopup="true" aria-expanded="true" onclick="toggleDropdown('{{ item_id }}')">
            ...
        </button>
    </div>
    <div class="hidden origin-top-right absolute right-0 mt-2 w-56 rounded-md shadow-lg {{ bg_color }} ring-1 ring-black ring-opacity-5 divide-y divide-gray-100 z-[9999] dark:divide-gray-600" role="menu" aria-orientation="vertical" aria-labelledby="options-menu-{{ item_id }}" id="dropdown-{{ item_id }}">
        <div class="py-1" role="none">
            {# --- View Report Link --- #}
            <a href="{{ url_for('foliage_report.vista_reporte', report_id=item_id) }}" class="{{ text_color }} block px-4 py-2 text-sm {{ hover_bg_color }}" role="menuitem">Ver Reporte</a>
            {# --- Delete Report Link --- #}
            <a href="#" class="{{ text_color }} block px-4 py-2 text-sm {{ hover_bg_color }}" role="menuitem" onclick="showModal('delete', '{{ item_id }}')">Borrar</a>
            {# Add other actions like 'Download PDF' if needed #}
        </div>
    </div>
</div>
{% endmacro %}

{# --- Block Content Override --- #}
{% block content %}
{# Title and Create Button #}
<div class="sm:px-6 lg:px-8 flex justify-between items-center mb-0">
    <h1 class="text-2xl mt-0 pt-0 font-bold">{{ title }}</h1>
    {% if reports %}
        <div>
            {# Link to the report request page #}
            <a href="{{ url_for('foliage_report.generar_informe') }}" class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700">+ Crear Nuevo Informe</a>
        </div>
    {% endif %}
</div>
<div id="message" class="max-w-sm mx-auto mt-10 text-red-500"></div>

{# Generic CRUD content container #}
<div class="mx-auto max-w-8xl pt-0 pb-6 sm:px-6 lg:px-8">
    <div class="px-4 py-2 sm:px-0">

        {# Optional Filters (If needed in the future) #}
        {% if filter_field %}
        <div class="px-0 py-4 bg-white dark:bg-gray-900 flex flex-col sm:flex-row sm:items-end gap-3 w-full max-w-md">
            <form action="{{ select_url }}" method="get" class="w-full flex flex-col sm:flex-row gap-3">
                <select id="filter_{{ filter_field }}" name="filter_value" class="flex-grow w-full pl-4 pr-10 py-2.5 text-base border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm bg-white text-gray-700 dark:bg-gray-800 dark:text-gray-200 dark:border-gray-600 shadow-sm">
                    <option value="">Todos</option>
                    {% for option in filter_options %}
                        <option value="{{ option.id }}" {% if option.id == filter_value %}selected{% endif %}>{{ option.name }}</option>
                    {% endfor %}
                </select>
                <button type="submit" class="px-5 py-2.5 rounded-lg font-medium text-sm shadow-sm transition-all duration-200 ease-in-out {{ base_button_classes }} {{ border_color }} {{ bg_color }} {{ text_color }} {{ hover_bg_color }} {{ focus_ring_color }}">
                    Filtrar
                </button>
            </form>
        </div>
        {% endif %}

        {# Info Cards (Using macro from crud_base) #}
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 pb-6">
            {{ info_card(title="Total de Informes", value=total_informes, description="Informes activos almacenados" ) }}
            {# Add more relevant cards if needed #}
            {# {{ info_card(title="Análisis reciente", value="Último análisis", description="" ) }} #}
            {# {{ info_card(title="Mi cajilla", value="valor", description="esta descripcion" ) }} #}
        </div>

        {# Bulk Action Button (if checkboxes are enabled) #}
         {% if show_select_box %}
         <div class="mb-4 flex justify-end">
            <button onclick="handleBulkAction()" class="{{ base_button_classes }} {{ border_color }} {{ delete_button_bg_color }} text-white {{ focus_ring_color }}">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mr-1" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd" />
                </svg>
                Borrar Seleccionados
            </button>
        </div>
        {% endif %}

        {# Table Displaying Reports #}
        <div>
            <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700 border rounded">
                {# Table Header #}
                <thead class="{{ bg_color }} dark:bg-gray-900 hidden sm:table-header-group">
                    <tr class="bg-gray-200 dark:bg-gray-900 hidden sm:table-row">
                        {% if show_select_box %}
                        <th scope="col" class="{{ table_header_class }} w-12">
                            <input type="checkbox" id="select-all" onclick="toggleSelectAll()">
                        </th>
                        {% endif %}
                        {% for header in table_headers %}
                        <th scope="col" class="{{ table_header_class }} text-gray-800">
                            {{ header }}
                        </th>
                        {% endfor %}
                        <th scope="col" class="{{ table_header_class }} text-gray-500">
                            Acciones
                        </th>
                    </tr>
                </thead>
                {# Table Body #}
                <tbody class="{{ bg_color }} divide-y divide-gray-200 dark:divide-gray-700" id="{{ entity_name_lower }}-table-body">
                    {% for item in items %}
                    {# Desktop Row #}
                    <tr class="{{ hover_bg_color }} hidden sm:table-row">
                        {% if show_select_box %}
                        <td class="{{ table_cell_class }} {{ text_color }}">
                            <input type="checkbox" class="item-checkbox" value="{{ item.id }}">
                        </td>
                        {% endif %}
                        {% for field in item_fields %}
                        <td class="{{ table_cell_class }} {{ text_color }}">
                            {% if field == 'active' %}
                                <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full {{ 'bg-green-100 text-green-800' if item[field] else 'bg-red-100 text-red-800' }}">
                                    {{ "Activo" if item[field] else "Inactivo" }}
                                </span>
                            {% else %}
                                {{ item[field] }}
                            {% endif %}
                        </td>
                        {% endfor %}
                        <td class="{{ table_cell_class }} font-medium sm:table-cell">
                            {# Use the overridden action_dropdown macro #}
                            {{ action_dropdown(item.id) }}
                        </td>
                    </tr>
                    {# Mobile Card View #}
                    <tr class="block sm:hidden border-b dark:border-gray-700">
                        <td class="px-4 py-4 block">
                            <div class="flex items-center mb-2">
                                {% if show_select_box %}
                                <input type="checkbox" class="item-checkbox mr-3" value="{{ item.id }}">
                                {% endif %}
                                <div class="flex-1 text-right">
                                     {{ action_dropdown(item.id) }}
                                </div>
                            </div>
                            {% for field in item_fields %}
                            <div class="text-sm mb-1 {{ text_color }}">
                                <span class="font-bold text-gray-500 dark:text-gray-400">{{ table_headers[loop.index0] }}:</span>
                                {% if field == 'active' %}
                                    <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full {{ 'bg-green-100 text-green-800' if item[field] else 'bg-red-100 text-red-800' }}">
                                        {{ "Activo" if item[field] else "Inactivo" }}
                                    </span>
                                {% else %}
                                    {{ item[field] }}
                                {% endif %}
                            </div>
                            {% endfor %}
                        </td>
                    </tr>
                    {% else %}
                     <tr>
                        <td colspan="{{ table_headers|length + (1 if show_select_box else 0) + 1 }}" class="text-center py-4 text-gray-500">
                            No hay informes para mostrar.
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>

{# --- Modals (Only Delete Modal is relevant here) --- #}

{# Content for Delete Modal #}
{% set delete_content %}
<p class="text-sm {{ text_color }}">
    ¿Está seguro de que desea eliminar este {{ entity_name_lower }}? Esta acción marcará el informe como inactivo.
</p>
{% endset %}

{# Actions for Delete Modal #}
{% set delete_actions %}
<button type="button" onclick="delete{{ entity_name }}()"
    class="w-full sm:w-auto {{ base_button_classes }} {{ delete_button_bg_color }} text-white {{ focus_ring_color }} sm:ml-3">
    Eliminar
</button>
<button type="button" onclick="closeDeleteModal()"
    class="mt-3 w-full sm:w-auto {{ base_button_classes }} {{ border_color }} {{ bg_color }} {{ text_color }} {{ hover_bg_color }} {{ focus_ring_color }} sm:mt-0 sm:ml-3">
    Cancelar
</button>
{% endset %}

{# Render Delete Modal #}
{{ modal('deleteModal', 'Confirmar Eliminación', delete_content, delete_actions) }}

{# Debug Output (Optional) #}
{% if DEBUG %}
<pre class="w-[800px] max-w-4xl p-6 bg-gray-800 text-gray-200 rounded-lg shadow-lg font-mono text-sm leading-relaxed whitespace-pre-wrap break-words border border-gray-700 my-4 mx-auto">
Debug Info:
Items: {{ items | tojson(indent=2) }}
</pre>
{% endif %}

{% endblock %}

{# --- JavaScript Block --- #}
{% block extra_js %}
{# Include the base JS functions from crud_base.j2 #}
{{ super() }}

<script>
    // --- Override delete function if necessary ---
    // The base delete function likely works by sending DELETE to api_url + id.
    // If your API endpoint for deleting recommendations is different or needs
    // specific handling (like marking inactive instead of true delete),
    // you might override deleteReporte() here.

    // Example: Assuming the base delete function handles DELETE requests correctly
    // If not, you'd implement `deleteReportes` like this:
    /*
    async function deleteReportes() { // Note the plural name matching entity_name
        let url = `{{ api_url }}${currentReporteId.toString()}`; // Ensure correct ID variable
        let method = 'DELETE'; // Or 'PUT' if marking inactive

        try {
            const response = await fetch(url, {
                method: method,
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/json',
                    "X-CSRF-TOKEN": getCookie("csrf_access_token"),
                },
                // Body might not be needed for DELETE, or send { active: false } for PUT
                // body: JSON.stringify({ id: currentReporteId.toString() }),
            });

            if (response.ok) {
                location.reload();
            } else {
                const errorData = await response.json();
                alert('Error al eliminar el reporte: ' + (errorData.error || 'Error desconocido'));
            }
        } catch (error) {
            console.error('Error:', error);
            alert('Error al eliminar el reporte.');
        } finally {
             closeDeleteModal();
        }
    }
    */

     // --- Override bulk delete function if necessary ---
     /*
     async function handleBulkAction() {
        const selectedItems = Array.from(document.querySelectorAll('.item-checkbox:checked')).map(checkbox => checkbox.value);

        if (selectedItems.length === 0) {
            alert('Por favor seleccione al menos un elemento.');
            return;
        }
        if (confirm('¿Está seguro de que desea eliminar los reportes seleccionados?')) {
            try {
                const response = await fetch('{{ api_url }}', { // Adjust URL if bulk delete is different
                    method: 'DELETE', // Or 'PUT'
                    credentials: 'include',
                    headers: {
                        'Content-Type': 'application/json',
                        "X-CSRF-TOKEN": getCookie("csrf_access_token"),
                    },
                    body: JSON.stringify({ "ids": selectedItems }),
                     // Or for PUT: body: JSON.stringify({ ids: selectedItems, active: false })
                });

                if (response.ok) {
                    location.reload();
                } else {
                     const errorData = await response.json();
                    alert('Error al eliminar los reportes seleccionados: ' + (errorData.error || 'Error desconocido'));
                }
            } catch (error) {
                console.error('Error:', error);
                alert('Error al eliminar los reportes seleccionados');
            }
        }
    }
    */

</script>
{% endblock %}
```

```html
{# ./modules/foliage_report/templates/solicitar_informe.j2 #}
{% extends "base.j2" %}
{% set dashboard = true %}

{% block content %}
<div class="container mx-auto p-4">
    <div class="flex justify-between items-center mb-4">
        <h1 class="text-2xl font-bold">Configuración del Informe</h1>
        {# Add buttons for Reset/Save config later if needed #}
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
        {# Left Column: Filters and Analysis List #}
        <div class="md:col-span-2 space-y-6">

            {# Filter Section #}
            <div class="bg-white dark:bg-gray-800 p-4 rounded-lg shadow">
                <h2 class="text-lg font-semibold mb-3 text-gray-700 dark:text-gray-200">Filtros de Selección</h2>
                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {# Farm Select #}
                    <div>
                        <label for="farm-select" class="block text-sm font-medium text-gray-600 dark:text-gray-300 mb-1">Finca</label>
                        <select id="farm-select" name="farm_id" class="w-full border dark:border-gray-600 dark:bg-gray-700 p-2 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500">
                            <option value="">-- Seleccione Finca --</option>
                            {# Options will be loaded by JS #}
                        </select>
                    </div>
                    {# Lot Select #}
                    <div>
                        <label for="lot-select" class="block text-sm font-medium text-gray-600 dark:text-gray-300 mb-1">Lote</label>
                        <select id="lot-select" name="lot_id" class="w-full border dark:border-gray-600 dark:bg-gray-700 p-2 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500" disabled>
                            <option value="">-- Seleccione Lote --</option>
                            {# Options will be loaded by JS based on Farm #}
                        </select>
                    </div>
                    {# Date Range #}
                    <div class="sm:col-span-2 lg:col-span-1 grid grid-cols-2 gap-2">
                         <div>
                            <label for="startdate-filter" class="block text-sm font-medium text-gray-600 dark:text-gray-300 mb-1">Desde</label>
                            <input type="date" id="startdate-filter" name="start_date" class="w-full border dark:border-gray-600 dark:bg-gray-700 p-2 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500">
                        </div>
                         <div>
                            <label for="enddate-filter" class="block text-sm font-medium text-gray-600 dark:text-gray-300 mb-1">Hasta</label>
                            <input type="date" id="enddate-filter" name="end_date" class="w-full border dark:border-gray-600 dark:bg-gray-700 p-2 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500">
                        </div>
                    </div>
                </div>
                 <div class="mt-4 text-right">
                     <button id="filter-button" class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-md text-sm">
                         <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 inline-block mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                           <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
                         </svg>
                         Filtrar Análisis
                     </button>
                 </div>
            </div>
            {# End Filter Section #}

            {# Analysis List Section #}
            <div class="bg-white dark:bg-gray-800 p-4 rounded-lg shadow">
                <h2 class="text-lg font-semibold mb-3 text-gray-700 dark:text-gray-200">Análisis Disponibles</h2>
                 <div id="analysis-loading" class="text-center text-gray-500 py-4 hidden">Cargando análisis...</div>
                 <div id="analysis-error" class="text-center text-red-500 py-4 hidden">Error al cargar análisis.</div>
                 <div id="analysis-no-results" class="text-center text-gray-500 py-4 hidden">No se encontraron análisis con los filtros seleccionados.</div>
                <div class="overflow-x-auto">
                    <table class="w-full border-collapse">
                        <thead>
                            <tr class="bg-gray-100 dark:bg-gray-700 text-left text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-gray-300">
                                <th class="p-2 w-10"><input type="checkbox" id="select-all-analyses"></th>
                                <th class="p-2">ID</th>
                                <th class="p-2">Fecha</th>
                                <th class="p-2">Finca</th>
                                <th class="p-2">Lote</th>
                                {# <th class="p-2">Tipo</th> #}
                            </tr>
                        </thead>
                        <tbody id="analysis-table-body" class="divide-y dark:divide-gray-700">
                            {# Rows will be loaded by JS #}
                        </tbody>
                    </table>
                </div>
            </div>
            {# End Analysis List Section #}
        </div>

        {# Right Column: Report Options and Generation #}
        <div class="bg-white dark:bg-gray-800 p-4 rounded-lg shadow self-start">
            <h2 class="text-lg font-semibold mb-3 text-gray-700 dark:text-gray-200">Opciones del Informe</h2>
            <form id="generate-report-form">
                 <div>
                     <label for="report-title" class="block text-sm font-medium text-gray-600 dark:text-gray-300 mb-1">Título del Informe</label>
                     <input type="text" id="report-title" name="title" class="w-full border dark:border-gray-600 dark:bg-gray-700 p-2 rounded-md text-sm focus:ring-blue-500 focus:border-blue-500" placeholder="Ej: Informe Lote X - Marzo 2025">
                 </div>

                 {# Add other options like sections to include if needed #}
                 {# <h3 class="font-semibold mt-4 text-sm text-gray-600 dark:text-gray-300">Secciones a incluir</h3>
                 <div class="space-y-1 text-sm">
                     <label class="flex items-center">
                         <input type="checkbox" name="include_foliar" checked class="mr-2 rounded dark:bg-gray-600 border-gray-300 dark:border-gray-500 text-blue-600 focus:ring-blue-500"> Análisis Foliar
                     </label>
                      <label class="flex items-center">
                         <input type="checkbox" name="include_soil" checked class="mr-2 rounded dark:bg-gray-600 border-gray-300 dark:border-gray-500 text-blue-600 focus:ring-blue-500"> Análisis de Suelo
                     </label>
                     <label class="flex items-center">
                         <input type="checkbox" name="include_recommendations" checked class="mr-2 rounded dark:bg-gray-600 border-gray-300 dark:border-gray-500 text-blue-600 focus:ring-blue-500"> Recomendaciones
                     </label>
                 </div> #}

                 <button type="submit" id="generate-report-button" class="mt-6 bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-md w-full text-sm disabled:opacity-50 disabled:cursor-not-allowed">
                      <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4 inline-block mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                       <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                     </svg>
                     Generar Informe
                 </button>
                 <div id="generate-report-message" class="mt-3 text-sm"></div>
            </form>
        </div>
    </div>
</div>
{% endblock %}

{% block extra_js %}
{{ super() }}
<script>
    // --- Helper Functions ---
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    const farmSelect = document.getElementById('farm-select');
    const lotSelect = document.getElementById('lot-select');
    const startDateInput = document.getElementById('startdate-filter');
    const endDateInput = document.getElementById('enddate-filter');
    const filterButton = document.getElementById('filter-button');
    const analysisTableBody = document.getElementById('analysis-table-body');
    const loadingDiv = document.getElementById('analysis-loading');
    const errorDiv = document.getElementById('analysis-error');
    const noResultsDiv = document.getElementById('analysis-no-results');
    const selectAllCheckbox = document.getElementById('select-all-analyses');
    const generateReportForm = document.getElementById('generate-report-form');
    const generateReportButton = document.getElementById('generate-report-button');
    const generateReportMessage = document.getElementById('generate-report-message');

    // --- Load Initial Farms ---
    async function loadFarms() {
        try {
            const response = await fetch("{{ url_for('foliage_report_api.get_farms') }}", {
                 headers: { 'Authorization': `Bearer ${getCookie('access_token_cookie')}` } // Add Authorization header
            });
            if (!response.ok) throw new Error('Failed to load farms');
            const farms = await response.json();

            farmSelect.innerHTML = '<option value="">-- Seleccione Finca --</option>'; // Reset
            farms.forEach(farm => {
                const option = document.createElement('option');
                option.value = farm.id;
                option.textContent = farm.name;
                farmSelect.appendChild(option);
            });
        } catch (error) {
            console.error("Error loading farms:", error);
            // Display error to user if needed
        }
    }

    // --- Load Lots based on Farm Selection ---
    async function loadLots(farmId) {
        lotSelect.innerHTML = '<option value="">Cargando lotes...</option>';
        lotSelect.disabled = true;
        analysisTableBody.innerHTML = ''; // Clear analysis table

        if (!farmId) {
            lotSelect.innerHTML = '<option value="">-- Seleccione Lote --</option>';
            return;
        }

        try {
            const response = await fetch(`{{ url_for('foliage_report_api.get_lots') }}?farm_id=${farmId}`, {
                 headers: { 'Authorization': `Bearer ${getCookie('access_token_cookie')}` }
            });
            if (!response.ok) throw new Error('Failed to load lots');
            const lots = await response.json();

            lotSelect.innerHTML = '<option value="">-- Seleccione Lote (Opcional) --</option>';
            lots.forEach(lot => {
                const option = document.createElement('option');
                option.value = lot.id;
                option.textContent = lot.name;
                lotSelect.appendChild(option);
            });
            lotSelect.disabled = false;
        } catch (error) {
            console.error("Error loading lots:", error);
            lotSelect.innerHTML = '<option value="">Error al cargar lotes</option>';
        }
    }

    // --- Fetch and Display Analyses ---
    async function fetchAndDisplayAnalyses() {
        const farmId = farmSelect.value;
        const lotId = lotSelect.value;
        const startDate = startDateInput.value;
        const endDate = endDateInput.value;

        // Basic validation: Farm is required to fetch analyses
        if (!farmId) {
             analysisTableBody.innerHTML = '';
             loadingDiv.classList.add('hidden');
             errorDiv.classList.add('hidden');
             noResultsDiv.classList.remove('hidden');
             noResultsDiv.textContent = 'Seleccione una finca para ver los análisis.';
             return;
        }


        loadingDiv.classList.remove('hidden');
        errorDiv.classList.add('hidden');
        noResultsDiv.classList.add('hidden');
        analysisTableBody.innerHTML = ''; // Clear previous results
        selectAllCheckbox.checked = false; // Uncheck select all

        const params = new URLSearchParams();
        if (farmId) params.append('farm_id', farmId);
        if (lotId) params.append('lot_id', lotId);
        if (startDate) params.append('start_date', startDate);
        if (endDate) params.append('end_date', endDate);

        try {
            const response = await fetch(`{{ url_for('foliage_report_api.get_analyses') }}?${params.toString()}`, {
                 headers: { 'Authorization': `Bearer ${getCookie('access_token_cookie')}` }
            });
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const analyses = await response.json();

            loadingDiv.classList.add('hidden');

            if (analyses.length === 0) {
                noResultsDiv.classList.remove('hidden');
                noResultsDiv.textContent = 'No se encontraron análisis con los filtros seleccionados.';
            } else {
                analyses.forEach(analysis => {
                    const row = document.createElement('tr');
                    row.className = 'hover:bg-gray-50 dark:hover:bg-gray-700 text-sm';
                    row.innerHTML = `
                        <td class="p-2"><input type="checkbox" class="analysis-checkbox" value="${analysis.id}"></td>
                        <td class="p-2">${analysis.id}</td>
                        <td class="p-2">${analysis.date}</td>
                        <td class="p-2">${analysis.farm_name}</td>
                        <td class="p-2">${analysis.lot_name}</td>
                        {# <td class="p-2">Tipo...</td> #} {# Add type if available in API response #}
                    `;
                    analysisTableBody.appendChild(row);
                });
            }
        } catch (error) {
            console.error("Error fetching analyses:", error);
            loadingDiv.classList.add('hidden');
            errorDiv.classList.remove('hidden');
            errorDiv.textContent = `Error al cargar análisis: ${error.message}`;
        }
    }

     // --- Handle Select All Checkbox ---
     selectAllCheckbox.addEventListener('change', (event) => {
         const checkboxes = analysisTableBody.querySelectorAll('.analysis-checkbox');
         checkboxes.forEach(checkbox => {
             checkbox.checked = event.target.checked;
         });
     });

     // --- Handle Generate Report Form Submission ---
    generateReportForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        generateReportButton.disabled = true;
        generateReportMessage.textContent = 'Generando informe...';
        generateReportMessage.className = 'mt-3 text-sm text-blue-600';

        const selectedAnalysisIds = Array.from(analysisTableBody.querySelectorAll('.analysis-checkbox:checked'))
                                         .map(cb => parseInt(cb.value));
        const reportTitle = document.getElementById('report-title').value.trim();


        if (selectedAnalysisIds.length === 0) {
            generateReportMessage.textContent = 'Error: Debe seleccionar al menos un análisis.';
            generateReportMessage.className = 'mt-3 text-sm text-red-600';
            generateReportButton.disabled = false;
            return;
        }

        const payload = {
            common_analysis_ids: selectedAnalysisIds,
            title: reportTitle || `Informe Análisis Lote - ${new Date().toLocaleDateString()}` // Default title
        };

        try {
            const response = await fetch("{{ url_for('foliage_report_api.report_generator') }}", {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Authorization': `Bearer ${getCookie('access_token_cookie')}`,
                    'X-CSRF-TOKEN': getCookie('csrf_access_token') // Include CSRF token if needed by backend
                },
                body: JSON.stringify(payload)
            });

            const result = await response.json();

            if (response.ok && result.report_id) {
                generateReportMessage.textContent = `Informe ${result.report_id} generado con éxito. Redirigiendo...`;
                generateReportMessage.className = 'mt-3 text-sm text-green-600';
                 // Redirect to the view report page
                 setTimeout(() => {
                     window.location.href = `/dashboard/foliage_report/vista_reporte/${result.report_id}`;
                 }, 1500);
            } else {
                throw new Error(result.error || `Error ${response.status}`);
            }
        } catch (error) {
            console.error("Error generating report:", error);
            generateReportMessage.textContent = `Error al generar informe: ${error.message}`;
            generateReportMessage.className = 'mt-3 text-sm text-red-600';
            generateReportButton.disabled = false;
        }
    });


    // --- Event Listeners ---
    farmSelect.addEventListener('change', () => {
        loadLots(farmSelect.value);
        // Optionally trigger fetchAndDisplayAnalyses() here or wait for button click
        analysisTableBody.innerHTML = ''; // Clear table on farm change
    });
    filterButton.addEventListener('click', fetchAndDisplayAnalyses);

    // --- Initial Load ---
    loadFarms();

});
</script>
{% endblock %}
```

```html
{# ./modules/foliage_report/templates/ver_reporte.j2 #}
{# --- Macros for Status --- #}
{% macro get_nutrient_status(actual, min_val, max_val) %}
  {% set actual_f = actual|float(none) %}
  {% set min_f = min_val|float(none) %}
  {% set max_f = max_val|float(none) %}
  {% if actual_f is none or min_f is none or max_f is none %}
    {# Handle cases where conversion fails or values are missing #}
    desconocido
  {% elif actual_f < min_f %}
    deficiente
  {% elif actual_f > max_f %}
    excesivo
  {% else %}
    óptimo
  {% endif %}
{% endmacro %}

{% macro get_status_color(status) %}
  {% if status == "deficiente" %}text-red-500
  {% elif status == "excesivo" %}text-yellow-500
  {% elif status == "óptimo" %}text-green-500
  {% else %}text-gray-500
  {% endif %}
{% endmacro %}

{% set button_class_report = "inline-flex items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm dark:text-black" %}

{% macro get_status_icon(status) %}
  {% if status == "deficiente" %}
    <svg class="h-4 w-4 text-red-500 inline-block" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path stroke-linecap="round" stroke-linejoin="round" d="M13 17h8m0 0V9m0 8l-8-8m0 8h.01M5 12H2.55A1.5 1.5 0 001.1 13.95l1.45 3.1A1.5 1.5 0 004.002 18H6M11 7H2.55A1.5 1.5 0 001.1 8.95l1.45 3.1A1.5 1.5 0 004.002 13H8"></path>
    </svg> {# Icono de advertencia #}
  {% elif status == "excesivo" %}
     <svg class="h-4 w-4 text-yellow-500 inline-block" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path stroke-linecap="round" stroke-linejoin="round" d="M5 17h8m0 0V9m0 8l8-8m0 8h-.01M19 12h2.45a1.5 1.5 0 011.45 1.95l-1.45 3.1A1.5 1.5 0 0119.998 18H18M13 7h8.45a1.5 1.5 0 011.45 1.95l-1.45 3.1A1.5 1.5 0 0119.998 13H16"></path>
    </svg> {# Icono de alerta #}
  {% elif status == "óptimo" %}
    <svg class="h-4 w-4 text-green-500 inline-block" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
    </svg> {# Icono de check #}
  {% else %}
    <svg class="h-4 w-4 text-gray-400 inline-block" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path stroke-linecap="round" stroke-linejoin="round" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.79 4 4s-1.79 4-4 4c-1.996 0-3.714-1.44-3.975-3.417l-2.025-2.025M12 6v4m0 4v4m4-4h-4m0 0H8"></path>
    </svg> {# Icono desconocido/pregunta #}
  {% endif %}
{% endmacro %}

{% extends "base.j2" %}
{% set dashboard = true %} {# Assuming this is part of a dashboard #}

{% block extra_css %}
    {{ super() }}
    {# Add specific styles if needed #}
    <style>
        .tabs-trigger { ... } /* Keep existing styles */
        .tabs-trigger.active { ... }
        .tabs-content { ... }
        .tabs-content:not(.hidden) { ... }

        /* Style for Liebig barrel */
        .liebig-barrel {
            display: flex;
            align-items: flex-end;
            height: 200px; /* Adjust height */
            border: 2px solid #a0aec0; /* Gray border */
            border-top: none;
            position: relative;
            overflow: hidden;
            background: linear-gradient(to top, #bfdbfe 50%, transparent 50%); /* Water effect */
            margin: 20px auto;
            width: 80%;
        }
        .liebig-stave {
            flex-grow: 1;
            background-color: #a0aec0; /* Gray stave */
            border-right: 1px solid #718096;
            position: relative;
            display: flex;
            flex-direction: column;
            justify-content: flex-end;
            align-items: center;
            text-align: center;
        }
        .liebig-stave:last-child {
            border-right: none;
        }
        .stave-level {
            width: 100%;
            background-color: #68d391; /* Green level */
            transition: height 0.5s ease-out;
        }
         .stave-label {
             position: absolute;
             bottom: -20px; /* Adjust as needed */
             width: 100%;
             font-size: 0.75rem;
             color: #4a5568;
         }
         .water-level {
             position: absolute;
             bottom: 0;
             left: 0;
             right: 0;
             background-color: #90cdf4; /* Light blue water */
             opacity: 0.7;
             transition: height 0.5s ease-out;
             border-top: 2px dashed #4299e1;
         }
    </style>
{% endblock %}

{% block content %}
<div class="container mx-auto p-4 md:p-6">
    {# --- Header --- #}
    <div class="flex flex-col md:flex-row justify-between items-start md:items-center mb-6 gap-4">
        <div>
            <h1 class="text-2xl md:text-3xl font-bold text-gray-800 dark:text-gray-100">
                {{ report_info.title or 'Informe de Análisis y Recomendaciones' }}
            </h1>
            <p class="text-sm text-indigo-600 dark:text-indigo-400 mt-1">
                Finca: <span class="font-medium">{{ report_info.farm_name }}</span> |
                Lote: <span class="font-medium">{{ report_info.lot_name }}</span> |
                Cultivo: <span class="font-medium">{{ report_info.crop_name }}</span> |
                Generado: <span class="font-medium">{{ report_info.date_generated }}</span>
                 {% if report_info.author %} | Por: <span class="font-medium">{{ report_info.author }}</span> {% endif %}
            </p>
             <p class="text-xs text-gray-500 dark:text-gray-400">ID Reporte: {{ report_info.id }}</p>
        </div>
        <div class="flex gap-2 flex-wrap">
            {# Action buttons - add JS functionality later if needed #}
            <button class="inline-flex items-center gap-1 rounded-md border border-gray-300 dark:border-gray-600 px-3 py-1.5 text-sm font-medium text-gray-700 dark:text-gray-200 shadow-sm bg-white dark:bg-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600">
                 <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm7-10V5a2 2 0 00-2-2H9a2 2 0 00-2 2v2m10 0h1"></path></svg>
                Imprimir
            </button>
            {# Add Export and Share buttons similarly #}
        </div>
    </div>

    {# --- Tabs --- #}
    <div class="mb-4 border-b border-gray-200 dark:border-gray-700">
         <nav class="-mb-px flex space-x-4 md:space-x-8" aria-label="Tabs">
             <button class="tabs-trigger whitespace-nowrap py-3 px-1 border-b-2 font-medium text-sm border-indigo-500 text-indigo-600" data-target="#dashboard">Resumen</button>
             <button class="tabs-trigger whitespace-nowrap py-3 px-1 border-b-2 font-medium text-sm border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300" data-target="#foliar">Análisis Foliar</button>
             <button class="tabs-trigger whitespace-nowrap py-3 px-1 border-b-2 font-medium text-sm border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300" data-target="#soil">Análisis de Suelo</button>
             <button class="tabs-trigger whitespace-nowrap py-3 px-1 border-b-2 font-medium text-sm border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300" data-target="#recommendations">Recomendaciones</button>
             {# <button class="tabs-trigger ..." data-target="#history">Histórico</button> #}
         </nav>
    </div>

    {# --- Tab Content --- #}
    <div>
        {# Dashboard/Summary Tab #}
        <div id="dashboard" class="tabs-content space-y-6">
            {# Row 1: General Status, Liebig Law, Top Recommendations #}
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                 {# General Status Card #}
                <div class="border dark:border-gray-700 bg-white dark:bg-gray-800 p-4 rounded-lg shadow-sm">
                     <h2 class="text-md font-semibold text-gray-700 dark:text-gray-200 mb-2">Estado General</h2>
                     <p class="text-xs text-gray-500 dark:text-gray-400 mb-3">Basado en análisis foliar y de suelo</p>
                     <div class="flex items-center justify-between">
                         <div class="text-xl font-bold {{ 'text-red-600 dark:text-red-400' if limitingNutrient else 'text-green-600 dark:text-green-400' }}">
                             {% if limitingNutrient %}Requiere Atención{% else %}Óptimo{% endif %}
                         </div>
                         {% if limitingNutrient %}
                            <span class="inline-block rounded-full px-2 py-0.5 text-xs font-semibold text-red-800 bg-red-100 dark:bg-red-900 dark:text-red-200">Limitante Detectado</span>
                         {% else %}
                            <span class="inline-block rounded-full px-2 py-0.5 text-xs font-semibold text-green-800 bg-green-100 dark:bg-green-900 dark:text-green-200">Equilibrado</span>
                         {% endif %}
                     </div>
                </div>

                 {# Liebig Law Card #}
                <div class="border dark:border-gray-700 bg-white dark:bg-gray-800 p-4 rounded-lg shadow-sm">
                     <h2 class="text-md font-semibold text-gray-700 dark:text-gray-200 mb-2">Ley del Mínimo (Liebig)</h2>
                     <p class="text-xs text-gray-500 dark:text-gray-400 mb-3">Nutriente más limitante para el crecimiento</p>
                     {% if limitingNutrient %}
                         <div class="space-y-1">
                             <div class="text-sm text-gray-500 dark:text-gray-400">Nutriente limitante:</div>
                             <div class="text-lg font-semibold text-red-600 dark:text-red-400">{{ limitingNutrient.name }}</div>
                             <div class="w-full bg-gray-200 dark:bg-gray-600 h-2 rounded-full overflow-hidden">
                                 <div class="h-2 rounded-full bg-red-500" style="width: {{ limitingNutrient.percentage|default(0)|round }}%;"></div>
                             </div>
                             <div class="text-xs text-gray-500 dark:text-gray-400">
                                 ~{{ limitingNutrient.percentage|default(0)|round }}% del nivel óptimo foliar
                             </div>
                         </div>
                     {% else %}
                         <div class="flex items-center justify-center h-full text-green-600 dark:text-green-400">
                             {{ get_status_icon('óptimo')|safe }} <span class="ml-2 text-sm">No se detectaron limitantes críticos.</span>
                         </div>
                     {% endif %}
                </div>

                 {# Top Recommendations Card #}
                 <div class="border dark:border-gray-700 bg-white dark:bg-gray-800 p-4 rounded-lg shadow-sm">
                     <h2 class="text-md font-semibold text-gray-700 dark:text-gray-200 mb-2">Recomendaciones Principales</h2>
                     <p class="text-xs text-gray-500 dark:text-gray-400 mb-3">Acciones prioritarias</p>
                     {% if recommendations and recommendations.productos_recomendados %}
                        <ul class="space-y-1.5">
                            {% for prod_rec in recommendations.productos_recomendados[:3] %} {# Show top 3 product recs #}
                                <li class="flex items-start gap-2 text-sm">
                                    <span class="inline-block mt-0.5 rounded-full px-1.5 py-0.5 text-xs font-semibold bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                                        Aplicar
                                    </span>
                                    <span class="text-gray-700 dark:text-gray-200">
                                        <span class="font-medium">{{ prod_rec.cantidad }}</span> unidades de <span class="font-medium">{{ prod_rec.producto }}</span>
                                    </span>
                                </li>
                            {% endfor %}
                            {% if recommendations.productos_recomendados|length > 3 %}
                                <li><button class="text-xs text-blue-600 hover:underline" onclick="document.querySelector('[data-target=#recommendations]').click()">Ver todas...</button></li>
                            {% endif %}
                        </ul>
                     {% else %}
                         <div class="flex items-center justify-center h-full text-green-600 dark:text-green-400">
                              {{ get_status_icon('óptimo')|safe }} <span class="ml-2 text-sm">No se requieren acciones inmediatas.</span>
                         </div>
                     {% endif %}
                </div>
            </div> {# End Row 1 #}

            {# Row 2: Charts #}
             <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                 <div class="border dark:border-gray-700 bg-white dark:bg-gray-800 p-4 rounded-lg shadow-sm">
                     <h2 class="text-md font-semibold text-gray-700 dark:text-gray-200 mb-2">Resumen Análisis Foliar</h2>
                     <p class="text-xs text-gray-500 dark:text-gray-400 mb-3">Comparación con niveles óptimos</p>
                     <div class="h-64 md:h-80"> {# Set fixed height for chart container #}
                        <canvas id="foliarChart"></canvas>
                     </div>
                 </div>
                 <div class="border dark:border-gray-700 bg-white dark:bg-gray-800 p-4 rounded-lg shadow-sm">
                     <h2 class="text-md font-semibold text-gray-700 dark:text-gray-200 mb-2">Resumen Análisis de Suelo</h2>
                     <p class="text-xs text-gray-500 dark:text-gray-400 mb-3">Comparación con niveles óptimos</p>
                     <div class="h-64 md:h-80"> {# Set fixed height for chart container #}
                        <canvas id="soilChart"></canvas>
                     </div>
                 </div>
             </div> {# End Row 2 #}

            {# Row 3: Liebig Barrel Visualization #}
            <div class="border dark:border-gray-700 bg-white dark:bg-gray-800 p-4 rounded-lg shadow-sm">
                <h2 class="text-md font-semibold text-gray-700 dark:text-gray-200 mb-2">Visualización Ley del Mínimo</h2>
                 <p class="text-xs text-gray-500 dark:text-gray-400 mb-3">El nivel está limitado por el nutriente más bajo</p>
                <div class="flex flex-col md:flex-row gap-6 items-center">
                     <div class="w-full md:w-2/3">
                         <div class="liebig-barrel">
                             {# Calculate min percentage for water level #}
                             {% set min_percentage = 100 %}
                             {% if limitingNutrient %}
                                 {% set min_percentage = limitingNutrient.percentage|default(100) %}
                             {% endif %}

                             {% for nutrient_name, optimal_data in optimalLevels.get('nutrientes', {}).items() %}
                                 {% set actual_value = analysisData.get('foliar', {}).get(nutrient_name|lower) %}
                                 {% if actual_value is not none and optimal_data and 'min' in optimal_data and 'max' in optimal_data %}
                                      {% set optimal_mid = (optimal_data.min|float + optimal_data.max|float) / 2 %}
                                      {% set percentage = (actual_value|float / optimal_mid) * 100 if optimal_mid > 0 else 0 %}
                                      {% set height_percentage = percentage|round|int if percentage <= 100 else 100 %} {# Cap height at 100% #}
                                      <div class="liebig-stave">
                                          <div class="stave-level" style="height: {{ height_percentage }}%;"></div>
                                          <span class="stave-label">{{ nutrient_name[:3] }}</span> {# Short label #}
                                      </div>
                                 {% endif %}
                             {% endfor %}
                             {# Water Level #}
                              <div class="water-level" style="height: {{ min_percentage if min_percentage <= 100 else 100 }}%;"></div>
                         </div>
                     </div>
                     <div class="w-full md:w-1/3 space-y-3">
                         <h3 class="text-md font-semibold text-gray-700 dark:text-gray-200">Principio Clave</h3>
                         <p class="text-sm text-gray-600 dark:text-gray-300">
                             El rendimiento del cultivo es proporcional al nutriente que se encuentra en menor cantidad relativa a las necesidades de la planta.
                         </p>
                         {% if limitingNutrient %}
                            <div class="bg-red-50 dark:bg-red-900/20 p-3 rounded-md border border-red-200 dark:border-red-700">
                                 <p class="text-sm text-red-700 dark:text-red-300 font-medium">
                                     {{ get_status_icon('deficiente')|safe }} Factor limitante: {{ limitingNutrient.name }}
                                 </p>
                                 <p class="text-xs text-red-600 dark:text-red-400 mt-1">
                                     Corregir esta deficiencia es prioritario para mejorar el crecimiento.
                                 </p>
                            </div>
                         {% endif %}
                     </div>
                 </div>
            </div> {# End Row 3 #}

        </div> {# End Dashboard Tab #}

        {# Foliar Analysis Tab #}
        <div id="foliar" class="tabs-content hidden space-y-6">
            <div class="border dark:border-gray-700 bg-white dark:bg-gray-800 p-4 rounded-lg shadow-sm">
                 <h2 class="text-lg font-semibold text-gray-700 dark:text-gray-200 mb-2">Análisis Foliar Detallado</h2>
                 <p class="text-xs text-gray-500 dark:text-gray-400 mb-4">Resultados de la muestra del {{ report_info.date_generated }}</p>
                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-4">
                     {% for nutrient_name, optimal_data in optimalLevels.get('nutrientes', {}).items() %}
                         {% set actual_value = analysisData.get('foliar', {}).get(nutrient_name|lower) %}
                         {% if actual_value is not none and optimal_data and 'min' in optimal_data and 'max' in optimal_data %}
                             {% set status = get_nutrient_status(actual_value, optimal_data.min, optimal_data.max) %}
                             {% set statusColor = get_status_color(status) %}
                             {% set optimal_mid = (optimal_data.min|float + optimal_data.max|float) / 2 %}
                             {% set percentage = (actual_value|float / optimal_mid) * 100 if optimal_mid > 0 else 0 %}
                             <div class="space-y-1 border-b dark:border-gray-700 pb-2">
                                 <div class="flex justify-between items-center text-sm">
                                     <div class="flex items-center font-medium text-gray-700 dark:text-gray-200">
                                         {{ get_status_icon(status)|safe }}
                                         <span class="ml-2">{{ nutrientNames[nutrient_name|lower] or nutrient_name }}</span>
                                     </div>
                                     <div class="{{ statusColor }} font-semibold">
                                         {{ actual_value }}%
                                         <span class="text-xs font-normal text-gray-400 dark:text-gray-500">
                                             ({{ optimal_data.min }}-{{ optimal_data.max }}%)
                                         </span>
                                     </div>
                                 </div>
                                 <div class="w-full bg-gray-200 dark:bg-gray-600 h-1.5 rounded-full overflow-hidden">
                                     <div class="h-full rounded-full
                                          {% if status == 'deficiente' %}bg-red-500
                                          {% elif status == 'excesivo' %}bg-yellow-500
                                          {% elif status == 'óptimo' %}bg-green-500
                                          {% else %}bg-gray-400{% endif %}"
                                          style="width: {{ percentage|default(0)|round|int if percentage <= 100 else 100 }}%;"></div>
                                 </div>
                             </div>
                         {% endif %}
                     {% endfor %}
                 </div>
             </div>
             <div class="border dark:border-gray-700 bg-white dark:bg-gray-800 p-4 rounded-lg shadow-sm">
                 <h2 class="text-lg font-semibold text-gray-700 dark:text-gray-200 mb-2">Interpretación Foliar</h2>
                  <div class="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                      <div>
                          <h3 class="font-medium mb-2 text-red-600 dark:text-red-400">Posibles Deficiencias</h3>
                          <ul class="list-disc pl-5 space-y-1 text-gray-600 dark:text-gray-300">
                             {% set found_def = false %}
                             {% for nutrient_name, optimal_data in optimalLevels.get('nutrientes', {}).items() %}
                                 {% set actual_value = analysisData.get('foliar', {}).get(nutrient_name|lower) %}
                                 {% if actual_value is not none and optimal_data and 'min' in optimal_data and 'max' in optimal_data %}
                                     {% if actual_value|float < optimal_data.min|float %}
                                         <li><span class="font-semibold">{{ nutrientNames[nutrient_name|lower] or nutrient_name }}:</span> {{ actual_value }}% (vs min {{ optimal_data.min }}%)</li>
                                         {% set found_def = true %}
                                     {% endif %}
                                 {% endif %}
                             {% endfor %}
                             {% if not found_def %}<li>Ninguna detectada.</li>{% endif %}
                          </ul>
                      </div>
                       <div>
                          <h3 class="font-medium mb-2 text-yellow-600 dark:text-yellow-400">Posibles Excesos</h3>
                          <ul class="list-disc pl-5 space-y-1 text-gray-600 dark:text-gray-300">
                             {% set found_exc = false %}
                             {% for nutrient_name, optimal_data in optimalLevels.get('nutrientes', {}).items() %}
                                 {% set actual_value = analysisData.get('foliar', {}).get(nutrient_name|lower) %}
                                 {% if actual_value is not none and optimal_data and 'min' in optimal_data and 'max' in optimal_data %}
                                     {% if actual_value|float > optimal_data.max|float %}
                                         <li><span class="font-semibold">{{ nutrientNames[nutrient_name|lower] or nutrient_name }}:</span> {{ actual_value }}% (vs max {{ optimal_data.max }}%)</li>
                                         {% set found_exc = true %}
                                     {% endif %}
                                 {% endif %}
                             {% endfor %}
                              {% if not found_exc %}<li>Ninguno detectado.</li>{% endif %}
                          </ul>
                      </div>
                  </div>
             </div>
        </div> {# End Foliar Tab #}

        {# Soil Analysis Tab #}
        <div id="soil" class="tabs-content hidden space-y-6">
             {# Check if soil data exists #}
             {% if analysisData.get("soil") %}
                 <div class="border dark:border-gray-700 bg-white dark:bg-gray-800 p-4 rounded-lg shadow-sm">
                    <h2 class="text-lg font-semibold text-gray-700 dark:text-gray-200 mb-2">Análisis de Suelo Detallado</h2>
                    <p class="text-xs text-gray-500 dark:text-gray-400 mb-4">Resultados de la muestra del {{ report_info.date_generated }}</p>
                     <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-4">
                         {# Iterate through soil analysis data similar to foliar #}
                         {% for key, value in analysisData.soil.items() %}
                              {% set optimal_data = optimalLevels.get('nutrientes', {}).get(key) %} {# Adjust key if needed for optimalLevels #}
                              {% if value is not none and optimal_data and 'min' in optimal_data and 'max' in optimal_data %}
                                  {% set status = get_nutrient_status(value, optimal_data.min, optimal_data.max) %}
                                  {% set statusColor = get_status_color(status) %}
                                  {% set optimal_mid = (optimal_data.min|float + optimal_data.max|float) / 2 %}
                                  {% set percentage = (value|float / optimal_mid) * 100 if optimal_mid > 0 else 0 %}
                                  <div class="space-y-1 border-b dark:border-gray-700 pb-2">
                                      <div class="flex justify-between items-center text-sm">
                                          <div class="flex items-center font-medium text-gray-700 dark:text-gray-200">
                                              {{ get_status_icon(status)|safe }}
                                              <span class="ml-2">{{ nutrientNames[key] or key|capitalize }}</span>
                                          </div>
                                          <div class="{{ statusColor }} font-semibold">
                                              {{ value }} {# Add units if available #}
                                              <span class="text-xs font-normal text-gray-400 dark:text-gray-500">
                                                  ({{ optimal_data.min }}-{{ optimal_data.max }}) {# Add units #}
                                              </span>
                                          </div>
                                      </div>
                                       <div class="w-full bg-gray-200 dark:bg-gray-600 h-1.5 rounded-full overflow-hidden">
                                         <div class="h-full rounded-full
                                              {% if status == 'deficiente' %}bg-red-500
                                              {% elif status == 'excesivo' %}bg-yellow-500
                                              {% elif status == 'óptimo' %}bg-green-500
                                              {% else %}bg-gray-400{% endif %}"
                                              style="width: {{ percentage|default(0)|round|int if percentage <= 100 else 100 }}%;"></div>
                                     </div>
                                  </div>
                             {% elif value is not none %} {# Display value even if no optimal range #}
                                  <div class="space-y-1 border-b dark:border-gray-700 pb-2">
                                     <div class="flex justify-between items-center text-sm">
                                         <span class="font-medium text-gray-700 dark:text-gray-200">{{ nutrientNames[key] or key|capitalize }}</span>
                                         <span class="font-semibold text-gray-600 dark:text-gray-300">{{ value }}</span> {# Add units #}
                                     </div>
                                 </div>
                             {% endif %}
                         {% endfor %}
                     </div>
                 </div>
                 {# Add interpretation section for soil similar to foliar #}
             {% else %}
                 <div class="text-center py-6 text-gray-500 dark:text-gray-400">
                     No hay datos de análisis de suelo disponibles para este informe.
                 </div>
             {% endif %}
        </div> {# End Soil Tab #}

        {# Recommendations Tab #}
        <div id="recommendations" class="tabs-content hidden space-y-6">
            <div class="border dark:border-gray-700 bg-white dark:bg-gray-800 p-4 rounded-lg shadow-sm">
                <h2 class="text-lg font-semibold text-gray-700 dark:text-gray-200 mb-2">Recomendaciones Detalladas</h2>
                <p class="text-xs text-gray-500 dark:text-gray-400 mb-4">Basado en los análisis y la Ley del Mínimo</p>
                {% if recommendations and recommendations.productos_recomendados %}
                    <h3 class="text-md font-semibold mb-3 text-blue-700 dark:text-blue-300">Aplicación de Productos Recomendada</h3>
                    <ul class="list-disc pl-5 space-y-2 mb-5 text-sm text-gray-700 dark:text-gray-200">
                        {% for prod_rec in recommendations.productos_recomendados %}
                            <li>Aplicar <span class="font-medium">{{ prod_rec.cantidad }}</span> unidades de <span class="font-medium">{{ prod_rec.producto }}</span>.</li>
                        {% else %}
                             <li>No se recomiendan productos específicos en este momento.</li>
                        {% endfor %}
                    </ul>

                    <h3 class="text-md font-semibold mb-3 text-green-700 dark:text-green-300">Nutrientes Aportados Estimados</h3>
                     <div class="overflow-x-auto">
                         <table class="min-w-full text-sm">
                             <thead class="bg-gray-50 dark:bg-gray-700">
                                 <tr>
                                     <th class="px-3 py-1.5 text-left font-medium text-gray-500 dark:text-gray-300">Nutriente</th>
                                     <th class="px-3 py-1.5 text-right font-medium text-gray-500 dark:text-gray-300">Cantidad Aportada</th>
                                     <th class="px-3 py-1.5 text-left font-medium text-gray-500 dark:text-gray-300">Unidad</th>
                                 </tr>
                             </thead>
                              <tbody class="divide-y dark:divide-gray-700">
                                {% for nut_ap in recommendations.nutrientes_aportados %}
                                 <tr class="hover:bg-gray-50 dark:hover:bg-gray-700/50">
                                     <td class="px-3 py-1.5 text-gray-700 dark:text-gray-200">{{ nut_ap.nutriente }}</td>
                                     <td class="px-3 py-1.5 text-right text-gray-700 dark:text-gray-200">{{ nut_ap.cantidad }}</td>
                                     <td class="px-3 py-1.5 text-gray-500 dark:text-gray-400">{{ nut_ap.unidad }}</td>
                                 </tr>
                                {% else %}
                                    <tr><td colspan="3" class="text-center py-2 text-gray-500">No se calcularon aportes.</td></tr>
                                {% endfor %}
                             </tbody>
                         </table>
                     </div>
                {% else %}
                     <p class="text-center py-4 text-gray-500">No hay recomendaciones de aplicación de productos disponibles.</p>
                {% endif %}

                 {# Display Textual Recommendation if available #}
                 {% if recommendation_text %}
                 <div class="mt-6 border-t dark:border-gray-700 pt-4">
                    <h3 class="text-md font-semibold mb-2 text-gray-700 dark:text-gray-200">Notas Adicionales</h3>
                    <div class="prose prose-sm dark:prose-invert max-w-none">
                        {{ recommendation_text|replace('\n', '<br>')|safe }}
                    </div>
                 </div>
                 {% endif %}

            </div>

             <div class="border dark:border-gray-700 bg-white dark:bg-gray-800 p-4 rounded-lg shadow-sm">
                 <h2 class="text-lg font-semibold text-gray-700 dark:text-gray-200 mb-2">Explicación Ley de Liebig</h2>
                 <div class="space-y-2 text-sm text-gray-600 dark:text-gray-300">
                     <p>La Ley del Mínimo de Liebig establece que el crecimiento está dictado no por los recursos totales disponibles, sino por el recurso más escaso (factor limitante).</p>
                     <p>Este informe identifica el nutriente foliar más limitante y sugiere aplicaciones para corregir dicho déficit, buscando equilibrar la nutrición y optimizar el rendimiento potencial.</p>
                     <ul class="list-disc pl-5">
                         <li>El rendimiento aumenta al corregir el factor limitante.</li>
                         <li>Aumentar otros nutrientes no limitantes no mejora el rendimiento.</li>
                         <li>Una vez corregido, otro factor puede volverse limitante.</li>
                     </ul>
                 </div>
             </div>
        </div> {# End Recommendations Tab #}

        {# History Tab (Placeholder) #}
        {# <div id="history" class="tabs-content hidden"> ... </div> #}

    </div> {# End Tab Content Wrapper #}
</div>
{% endblock %}

{% block extra_js %}
    {{ super() }}
    <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js"></script> {# Use specific version or latest #}
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // --- Chart Colors (Example - define based on your CSS/Design) ---
            const chartColors = {
                actual: 'rgba(59, 130, 246, 0.7)',    // Blue-500
                min: 'rgba(239, 68, 68, 0.5)',      // Red-500
                max: 'rgba(245, 158, 11, 0.5)',     // Amber-500
                nitrogen: 'rgba(34, 197, 94, 0.8)',   // Green-500
                phosphorus: 'rgba(168, 85, 247, 0.8)',// Purple-500
                potassium: 'rgba(234, 179, 8, 0.8)'    // Yellow-500
            };

            // --- Helper to get Color ---
            function getNutrientColor(name) {
                const lowerName = name.toLowerCase();
                if (lowerName.includes('nitr')) return chartColors.nitrogen;
                if (lowerName.includes('fósf') || lowerName.includes('phos')) return chartColors.phosphorus;
                if (lowerName.includes('potas')) return chartColors.potassium;
                // Add more colors
                return `rgba(${Math.random()*255}, ${Math.random()*255}, ${Math.random()*255}, 0.7)`; // Random fallback
            }

            // --- Foliar Chart ---
            const foliarChartCtx = document.getElementById('foliarChart')?.getContext('2d');
            const foliarData = {{ foliarChartData | default([]) | tojson }};
            if (foliarChartCtx && foliarData.length > 0) {
                new Chart(foliarChartCtx, {
                    type: 'bar',
                    data: {
                        labels: foliarData.map(item => item.name),
                        datasets: [
                            {
                                label: 'Nivel Actual',
                                data: foliarData.map(item => item.actual),
                                backgroundColor: chartColors.actual,
                                borderColor: chartColors.actual.replace('0.7', '1'),
                                borderWidth: 1
                            },
                            {
                                label: 'Rango Óptimo',
                                data: foliarData.map(item => [item.min, item.max]), // For range display or error bars if supported
                                backgroundColor: 'rgba(107, 114, 128, 0.2)', // Gray-500 background for range
                                borderColor: 'rgba(107, 114, 128, 0.5)',
                                borderWidth: 1,
                                type: 'line', // Overlay range as lines or use floating bars
                                fill: false, // No fill for line range
                                pointRadius: 0,
                                // Or use 'bar' type with custom parsing for floating bars
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { position: 'bottom', labels: { boxWidth: 12, padding: 15 } },
                            tooltip: {
                                callbacks: {
                                     label: function(context) {
                                         let label = context.dataset.label || '';
                                         if (label) { label += ': '; }
                                         if (context.parsed.y !== null) {
                                             label += context.parsed.y + '%'; // Add unit
                                         }
                                         // Add optimal range info to tooltip
                                         const index = context.dataIndex;
                                         const item = foliarData[index];
                                         if (item) {
                                             label += ` (Óptimo: ${item.min}-${item.max}%)`;
                                         }

                                         return label;
                                     }
                                 }
                            }
                        },
                         scales: {
                            y: {
                                beginAtZero: true,
                                title: { display: true, text: 'Nivel (%)' }
                            }
                        }
                    }
                });
            } else if(foliarChartCtx) {
                 foliarChartCtx.font = "16px Arial";
                 foliarChartCtx.fillStyle = "#9ca3af"; // text-gray-400
                 foliarChartCtx.textAlign = "center";
                 foliarChartCtx.fillText("No hay datos de análisis foliar", foliarChartCtx.canvas.width / 2, foliarChartCtx.canvas.height / 2);
            }

            // --- Soil Chart ---
            const soilChartCtx = document.getElementById('soilChart')?.getContext('2d');
            const soilData = {{ soilChartData | default([]) | tojson }}; // Get data passed from backend
             if (soilChartCtx && soilData.length > 0) {
                 new Chart(soilChartCtx, {
                     type: 'bar', // Or 'radar' or 'line' depending on preference
                     data: {
                         labels: soilData.map(item => item.name),
                         datasets: [
                              {
                                 label: 'Nivel Actual',
                                 data: soilData.map(item => item.actual),
                                 backgroundColor: chartColors.actual,
                                 borderColor: chartColors.actual.replace('0.7', '1'),
                                 borderWidth: 1
                             },
                             {
                                 label: 'Rango Óptimo',
                                 data: soilData.map(item => [item.min, item.max]),
                                 backgroundColor: 'rgba(107, 114, 128, 0.2)',
                                 borderColor: 'rgba(107, 114, 128, 0.5)',
                                 borderWidth: 1,
                                 type: 'line',
                                 fill: false,
                                 pointRadius: 0,
                             }
                         ]
                     },
                     options: {
                         responsive: true,
                         maintainAspectRatio: false,
                         plugins: {
                             legend: { position: 'bottom', labels: { boxWidth: 12, padding: 15 } },
                             tooltip: {
                                callbacks: {
                                     label: function(context) {
                                         let label = context.dataset.label || '';
                                         if (label) { label += ': '; }
                                         const index = context.dataIndex;
                                         const item = soilData[index];
                                         if (context.parsed.y !== null && item) {
                                             label += context.parsed.y + (item.unit ? ` ${item.unit}` : '');
                                         }
                                          if (item) {
                                             label += ` (Óptimo: ${item.min}-${item.max}${item.unit ? ` ${item.unit}` : ''})`;
                                         }
                                         return label;
                                     }
                                 }
                            }
                         },
                          scales: {
                             y: {
                                 beginAtZero: true,
                                 title: { display: true, text: 'Valor' } // Generic Y-axis title
                             }
                         }
                     }
                 });
             } else if(soilChartCtx) {
                 soilChartCtx.font = "16px Arial";
                 soilChartCtx.fillStyle = "#9ca3af"; // text-gray-400
                 soilChartCtx.textAlign = "center";
                 soilChartCtx.fillText("No hay datos de análisis de suelo", soilChartCtx.canvas.width / 2, soilChartCtx.canvas.height / 2);
            }


            // --- History Chart ---
            const historyChartCtx = document.getElementById('historyChart')?.getContext('2d');
            const historyData = {{ historicalData | default([]) | tojson }}; // Get data
            if (historyChartCtx && historyData.length > 0) {
                 const datasets = Object.keys(historyData[0] || {})
                     .filter(key => key !== 'fecha')
                     .map(nutrientKey => ({
                         label: `{{ nutrientNames[nutrientKey] or nutrientKey|capitalize }}`, // Use nutrientNames mapping
                         data: historyData.map(item => item[nutrientKey]),
                         borderColor: getNutrientColor(nutrientKey),
                         backgroundColor: getNutrientColor(nutrientKey).replace('0.8', '0.2'),
                         fill: false,
                         tension: 0.1
                     }));

                 new Chart(historyChartCtx, {
                     type: 'line',
                     data: {
                         labels: historyData.map(item => item.fecha),
                         datasets: datasets
                     },
                     options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { position: 'bottom', labels: {boxWidth: 12, padding: 15} },
                            title: { display: true, text: 'Historial de Análisis (Últimos Datos)' }
                        },
                        scales: {
                            x: { title: { display: true, text: 'Fecha' } },
                            y: { title: { display: true, text: 'Nivel' } } // Adjust unit based on data
                        }
                    }
                });
             } else if(historyChartCtx) {
                 historyChartCtx.font = "16px Arial";
                 historyChartCtx.fillStyle = "#9ca3af"; // text-gray-400
                 historyChartCtx.textAlign = "center";
                 historyChartCtx.fillText("No hay datos históricos disponibles", historyChartCtx.canvas.width / 2, historyChartCtx.canvas.height / 2);
            }


            // --- Tab Handling ---
            const tabs = document.querySelectorAll('.tabs-trigger');
            const contents = document.querySelectorAll('.tabs-content');
            const activeTabClasses = ['border-indigo-500', 'text-indigo-600'];
            const inactiveTabClasses = ['border-transparent', 'text-gray-500', 'hover:text-gray-700', 'hover:border-gray-300'];

            tabs.forEach(tab => {
                tab.addEventListener('click', function(e) {
                    e.preventDefault();
                    // Deactivate all tabs and hide all content
                    tabs.forEach(t => {
                        t.classList.remove(...activeTabClasses);
                        t.classList.add(...inactiveTabClasses);
                        t.setAttribute('aria-selected', 'false');
                    });
                    contents.forEach(c => c.classList.add('hidden'));

                    // Activate the clicked tab and show its content
                    this.classList.add(...activeTabClasses);
                    this.classList.remove(...inactiveTabClasses);
                    this.setAttribute('aria-selected', 'true');
                    const targetId = this.getAttribute('data-target');
                    const targetContent = document.querySelector(targetId);
                    if (targetContent) {
                        targetContent.classList.remove('hidden');
                    }
                });
            });

             // Activate the first tab by default
            if (tabs.length > 0) {
                 tabs[0].classList.add(...activeTabClasses);
                 tabs[0].classList.remove(...inactiveTabClasses);
                 tabs[0].setAttribute('aria-selected', 'true');
                 const firstTargetId = tabs[0].getAttribute('data-target');
                 const firstTargetContent = document.querySelector(firstTargetId);
                 if (firstTargetContent) {
                     firstTargetContent.classList.remove('hidden');
                 }
             }

        });
    </script>
{% endblock %}
```

**Explanation and Key Changes:**

1.  **`foliage_report/controller.py`:**
    *   Added `ReportGeneratorView` to handle the POST request for generating reports.
    *   It fetches `CommonAnalysis` based on IDs, checks access using the central `check_resource_access`, determines the active crop, calls the `generate_full_report_data` helper, and saves the result as a `Recommendation`.
    *   Error handling (NotFound, BadRequest, Forbidden, general Exception) is included with rollbacks.
    *   Uses `datetime.utcnow().date()` for the report generation date.
    *   Gets the author name from the JWT claims.
    *   Stores complex data (recommendations, levels, etc.) as JSON strings in the `Recommendation` model's text fields.
    *   Reuses the `_serialize_recommendation` method (you might need to create this in `RecommendationView` if it doesn't exist) for the response.

2.  **`foliage_report/helpers.py`:**
    *   Added `generate_full_report_data` function (you'll need to implement the details based on your specific logic, using `LeyLiebig`, `NutrientOptimizer`, etc.). This function takes a list of `CommonAnalysis` objects and returns a structured dictionary containing all the data needed for the report.
    *   **Important:** Modified `LeyLiebig`, `NutrientOptimizer`, and `calcular_cv_nutriente` to consistently use or convert to `Decimal` for calculations to avoid floating-point issues, especially important for financial or precise scientific data. Added checks for division by zero. Made `identificar_limitante` safer for empty inputs.
    *   Refined `NutrientOptimizer.optimizar_productos` to use equality constraints (`A_eq`, `b_eq`) in `linprog` to ensure the *exact* required nutrient amount is met, and added better error handling/reporting if optimization fails.
    *   Modified `NutrientOptimizer.generar_recomendacion` to return both a text string *and* a structured dictionary.
    *   Modified `contribuciones_de_producto` and resource fetching classes (`ObjectiveResource`, `LeafAnalysisResource`) for efficiency (eager loading, caching nutrient names) and Decimal conversion.
    *   Kept the `ReportView` class primarily for the `GET /report/<id>` endpoint, responsible for fetching a `Recommendation` and returning its full data (deserializing JSON fields).

3.  **`foliage_report/api_routes.py`:**
    *   Registered the new `ReportGeneratorView` for the `POST /generate_report` endpoint.
    *   Kept the existing `ReportView` for `GET /report/<id>`.
    *   Refined `get_farms`, `get_lots`, and `get_analyses` endpoints to use the central `check_resource_access` helper and improve error handling/structure. Added Authorization headers to JS fetch calls.

4.  **`foliage_report/web_routes.py`:**
    *   **`listar_reportes`:** Fetches `Recommendation` records, filters by user role/access, serializes necessary fields (including related names), and passes `items` to the template. Sets context variables required by `crud_base.j2`.
    *   **`vista_reporte`:** Accepts `report_id`, fetches the `Recommendation`, checks access, *deserializes* the JSON fields (`automatic_recommendations`, `optimal_comparison`, etc.) into Python dicts/lists, prepares chart data (you might need to adjust the keys based on how you store them in the JSON), and passes everything to `ver_reporte.j2`. Includes basic error handling for JSON decoding.
    *   **`generar_informe`:** Renders the `solicitar_informe.j2` template (no data needed initially).

5.  **`foliage_report/templates/listar_reportes.j2`:**
    *   Extends `crud_base.j2`.
    *   Sets appropriate `entity_name`, `title`, etc.
    *   Defines `table_headers` and `item_fields` matching the serialized data from the view function.
    *   Overrides the `action_dropdown` macro to provide a "View Report" link pointing to the `vista_reporte` route and a "Delete" action triggering the modal.
    *   Disables the "Edit" button as reports aren't directly edited this way.
    *   Includes the necessary modal definitions (only delete is used).
    *   The base JavaScript for delete/bulk delete from `crud_base.j2` should work if the API endpoint expects DELETE requests to `/api/foliage/report/report/<id>` or `/api/foliage/report/report/` with `{ids: [...]}`. Adjust the JS overrides if your delete API differs.

6.  **`foliage_report/templates/solicitar_informe.j2`:**
    *   Added JavaScript to:
        *   Fetch farms on load using `get_farms` API.
        *   Fetch lots when a farm is selected using `get_lots` API.
        *   Fetch analyses when filters change (or button clicked) using `get_analyses` API.
        *   Display loading/error/no-results states for the analysis table.
        *   Populate the analysis table dynamically.
        *   Handle the "Select All" checkbox.
        *   Handle the "Generate Report" form submission: collect selected analysis IDs and POST to the new `/api/foliage/report/generate_report` endpoint. Show success/error messages and redirect on success.
        *   Includes CSRF token fetching (using `getCookie`) if your `JWT_COOKIE_CSRF_PROTECT` is True. Added Authorization header.

7.  **`foliage_report/templates/ver_reporte.j2`:**
    *   Now uses the dynamic variables passed from the `vista_reporte` view function (e.g., `report_info`, `analysisData`, `optimalLevels`, `recommendations`, `limitingNutrient`, `foliarChartData`, etc.).
    *   Includes checks for the existence of data (e.g., `{% if analysisData.get("soil") %}`).
    *   The Chart.js initialization now uses `tojson` filter to safely pass the Python lists/dicts prepared in the view function. Added fallback text if chart data is empty.
    *   Refined the Liebig barrel visualization logic.
    *   Improved tab handling JS.

This structure separates report generation (POST API) from viewing (GET Web/API) and listing (GET Web). Remember to implement the core logic inside `generate_full_report_data` in `helpers.py` according to your specific calculations.