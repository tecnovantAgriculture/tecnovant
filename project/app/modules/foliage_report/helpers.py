# Python standard library imports
import json
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from statistics import mean, stdev
from typing import Dict, Tuple

from flask import current_app

# Third party imports
from scipy.optimize import linprog

from app.extensions import db
from app.modules.foliage.helpers import macronutrients, micronutrients

# Local application imports
from app.modules.foliage.models import (  # Lot,  # unused; LotCrop,  # unused; Recommendation,  # unused
    CommonAnalysis,
    LeafAnalysis,
    Nutrient,
    Objective,
    ProductContribution,
    ProductPrice,
    leaf_analysis_nutrients,
    objective_nutrients,
    product_contribution_nutrients,
)


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
            return Decimal("0.00")
        return (Decimal(valor_registro) / self.demanda_planta) * Decimal("100.00")

    def calcular_i(self, mineral_p: Decimal, mineral_cv: Decimal) -> Decimal:
        """
        Calcula la cantidad de ajuste necesario para un nutriente limitante en función de su coeficiente de variación.

        :param mineral_p: Porcentaje de suficiencia del nutriente.
        :param mineral_cv: Coeficiente de variación del nutriente.
        :return: Cantidad de ajuste necesaria para alcanzar el nivel óptimo.
        """
        if mineral_p > Decimal("100.00"):
            result = (mineral_p - Decimal("100.00")) * mineral_cv / Decimal("100.00")
        else:
            result = (Decimal("100.00") - mineral_p) * mineral_cv / Decimal("100.00")
        return result.quantize(Decimal("0.00"), rounding=ROUND_HALF_UP)

    def calcular_r(self, mineral_p: Decimal, mineral_i: Decimal) -> Decimal:
        """
        Determina el nivel corregido del nutriente después del ajuste.

        :param mineral_p: Porcentaje de suficiencia del nutriente.
        :param mineral_i: Cantidad de ajuste aplicada al nutriente.
        :return: Nivel corregido del nutriente en el suelo.
        """
        if mineral_p > Decimal("100.00"):
            return (mineral_p - mineral_i).quantize(
                Decimal("0.00"), rounding=ROUND_HALF_UP
            )
        return (mineral_p + mineral_i).quantize(Decimal("0.00"), rounding=ROUND_HALF_UP)

    def calcular_nutriente_limite(self, valores_registro: dict) -> str:
        """
        Identifica el nutriente más limitante según la Ley del Mínimo de Liebig.

        El nutriente limitante es aquel que tiene el menor porcentaje de suficiencia.

        :param valores_registro: Diccionario con los valores actuales de los nutrientes en el suelo.
        :return: Nombre del nutriente más limitante.
        """
        valores_p = {
            mineral: self.calcular_p(valor)
            for mineral, valor in valores_registro.items()
        }
        return min(
            valores_p, key=valores_p.get
        )  # Devuelve el nutriente con el menor porcentaje de suficiencia

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
            p = self.calcular_p(valor_registro)
            i = (
                self.calcular_i(p, valores_cv[mineral])
                if mineral == nutriente_limitante
                else Decimal("0.00")
            )
            r = self.calcular_r(p, i)
            nutrientes[mineral] = {"p": p, "i": i, "r": r}
        return nutrientes


class NutrientOptimizer:
    """


    Clase que optimiza la aplicación de productos para satisfacer los requerimientos de nutrientes de un cultivo,
    basada en la Ley del Mínimo de Liebig y programación lineal.
    """

    def __init__(
        self,
        nutrientes_actuales: Dict[str, Decimal],
        demandas_ideales: Dict[str, Decimal],
        productos_contribuciones: Dict[str, Dict[str, Decimal]],
        productos_precios: Dict[str, Decimal],
        coeficientes_variacion: Dict[str, Decimal],
    ):
        """
        Inicializa el optimizador de nutrientes.

        :param nutrientes_actuales: Diccionario con los niveles actuales de nutrientes (kg/ha o g/ha).
        :param demandas_ideales: Diccionario con los niveles ideales de nutrientes (kg/ha o g/ha).
        :param productos_contribuciones: Diccionario con los productos y sus contribuciones por nutriente.
        :param productos_precios: Diccionario con los precios de los productos.
        :param coeficientes_variacion: Diccionario con los coeficientes de variación por nutriente.
        """
        self.nutrientes_actuales = nutrientes_actuales
        self.demandas_ideales = demandas_ideales
        self.productos_contribuciones = productos_contribuciones
        self.productos_precios = productos_precios
        self.coeficientes_variacion = coeficientes_variacion
        self.nutrientes = list(demandas_ideales.keys())
        self.productos = list(productos_contribuciones.keys())

    def calcular_ajustes(self) -> Dict[str, Decimal]:
        """
        Calcula los ajustes necesarios para cada nutriente usando la Ley de Liebig adaptada.
        """
        ajustes = {}
        for nutriente in self.nutrientes:
            actual = self.nutrientes_actuales.get(nutriente, Decimal("0.0"))
            ideal = self.demandas_ideales[nutriente]
            if actual < ideal:
                p = (actual / ideal) * Decimal("100.0") if ideal > 0 else Decimal("0.0")
                i = (
                    (Decimal("100.0") - p)
                    * self.coeficientes_variacion[nutriente]
                    / Decimal("100.0")
                ).quantize(Decimal("0.00"), rounding=ROUND_HALF_UP)
                ajustes[nutriente] = (ideal - actual) * i  # Cantidad absoluta a ajustar
            else:
                ajustes[nutriente] = Decimal("0.0")
        return ajustes

    def identificar_limitante(self) -> str:
        """
        Identifica el nutriente más limitante según la Ley de Liebig.
        """
        porcentajes = {
            nutriente: (
                (
                    self.nutrientes_actuales.get(nutriente, Decimal("0.0"))
                    / self.demandas_ideales[nutriente]
                )
                * Decimal("100.0")
                if self.demandas_ideales[nutriente] > 0
                else Decimal("0.0")
            )
            for nutriente in self.nutrientes
        }
        return min(porcentajes, key=porcentajes.get)

    def _solucion_heuristica(
        self, ajustes_positivos: Dict[str, Decimal]
    ) -> Dict[str, Decimal]:
        """Solución heurística cuando la optimización falla"""
        print("Aplicando solución heurística...")
        cantidades = {prod: Decimal("0.0") for prod in self.productos}

        for nutriente, requerido in ajustes_positivos.items():
            # Encontrar el producto más eficiente para este nutriente
            mejor_producto = None
            mejor_eficiencia = Decimal("0.0")

            for prod in self.productos:
                contrib = self.productos_contribuciones[prod].get(
                    nutriente, Decimal("0.0")
                )
                if contrib > mejor_eficiencia:
                    mejor_eficiencia = contrib
                    mejor_producto = prod

            if mejor_producto and mejor_eficiencia > 0:
                cantidad_necesaria = requerido / mejor_eficiencia
                cantidades[mejor_producto] = max(
                    cantidades[mejor_producto], cantidad_necesaria
                )
                print(
                    f"Heurística: {mejor_producto} = {cantidad_necesaria} para {nutriente}"
                )

        return cantidades

    def optimizar_productos(self) -> Tuple[Dict[str, Decimal], Dict[str, Decimal]]:
        try:
            print("Iniciando optimización de productos...")
            if not self.productos:
                raise ValueError(
                    "No products available for optimization. Cannot generate recommendation."
                )

            ajustes = self.calcular_ajustes()
            print("Ajustes calculados:", ajustes)

            # Filtrar solo ajustes positivos (nutrientes que necesitan ser agregados)
            ajustes_positivos = {k: v for k, v in ajustes.items() if v > 0}

            if not ajustes_positivos:
                print("No hay nutrientes que necesiten ser agregados.")
                return {prod: Decimal("0.0") for prod in self.productos}, {
                    nutriente: Decimal("0.0") for nutriente in self.nutrientes
                }

            print(f"Nutrientes a optimizar: {list(ajustes_positivos.keys())}")

            # Verificar que hay productos que pueden aportar los nutrientes necesarios
            productos_utiles = set()
            for nutriente in ajustes_positivos:
                for prod in self.productos:
                    if (
                        self.productos_contribuciones[prod].get(
                            nutriente, Decimal("0.0")
                        )
                        > 0
                    ):
                        productos_utiles.add(prod)

            if not productos_utiles:
                print("No hay productos que puedan aportar los nutrientes necesarios.")
                raise ValueError(
                    "Los productos disponibles no pueden satisfacer los requerimientos nutricionales."
                )

            print(f"Productos útiles: {list(productos_utiles)}")

            # Coeficientes de la función objetivo (minimizar el costo total de productos)
            print("Definiendo función objetivo...")
            c = [
                float(self.productos_precios.get(prod, 0)) for prod in self.productos
            ]  # Usar precios de productos
            print("Coeficientes de la función objetivo (costos):", c)

            # Matriz de restricciones de desigualdad (A_ub * x >= b_ub)
            # Para linprog necesitamos A_ub * x <= b_ub, así que usamos -A_ub * x <= -b_ub
            print("Definiendo restricciones de desigualdad...")
            A_ub = []
            b_ub = []

            for nutriente in ajustes_positivos:
                print(f"Restricción para {nutriente}:")
                fila = []
                for prod in self.productos:
                    contrib = self.productos_contribuciones[prod].get(
                        nutriente, Decimal("0.0")
                    )
                    fila.append(-float(contrib))  # Negativo para convertir >= en <=

                # Solo agregar restricción si al menos un producto puede aportar este nutriente
                if any(val < 0 for val in fila):  # Al menos una contribución positiva
                    A_ub.append(fila)
                    b_ub.append(
                        -float(ajustes_positivos[nutriente])
                    )  # Negativo para convertir >= en <=
                    print(f"Coeficientes de la restricción: {fila}")
                    print(f"Valor de la restricción: {b_ub[-1]}")
                else:
                    print(f"Advertencia: No hay productos que aporten {nutriente}")

            if not A_ub:
                print("No se pudieron formar restricciones válidas")
                cantidades = self._solucion_heuristica(ajustes_positivos)
            else:
                print("Matriz de restricciones:", A_ub)
                print("Valores de las restricciones:", b_ub)

                # Límites (cantidades >= 0)
                print("Definiendo límites...")
                bounds = [(0, None)] * len(self.productos)
                print("Límites:", bounds)

                # Resolver optimización
                print("Resolviendo problema de programación lineal...")
                res = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")
                print("Resultado de la optimización:", res)

                if not res.success:
                    print("Error en la optimización:", res.message)
                    print("Intentando con método alternativo...")

                    # Intentar con método alternativo
                    res = linprog(
                        c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="interior-point"
                    )

                    if not res.success:
                        print("Error con método alternativo:", res.message)

                        # Como último recurso, intentar relajar las restricciones
                        print("Intentando con restricciones relajadas...")
                        # Reducir los requerimientos en un 20%
                        b_ub_relajado = [b * 0.8 for b in b_ub]
                        res = linprog(
                            c,
                            A_ub=A_ub,
                            b_ub=b_ub_relajado,
                            bounds=bounds,
                            method="highs",
                        )

                        if not res.success:
                            print(f"Optimización falló completamente: {res.message}")
                            cantidades = self._solucion_heuristica(ajustes_positivos)
                        else:
                            cantidades = self._procesar_resultado_optimizacion(res)
                    else:
                        cantidades = self._procesar_resultado_optimizacion(res)
                else:
                    cantidades = self._procesar_resultado_optimizacion(res)

            print("Cantidades de productos:", cantidades)

            # Calcular nutrientes aportados
            print("Calculando nutrientes aportados...")
            nutrientes_aportados = {
                nutriente: Decimal("0.0") for nutriente in self.nutrientes
            }
            for prod, cantidad in cantidades.items():
                if cantidad > 0:
                    for nutriente, contrib in self.productos_contribuciones[
                        prod
                    ].items():
                        nutrientes_aportados[nutriente] += contrib * cantidad

            print("Nutrientes aportados:", nutrientes_aportados)

            # Verificar que se cumplan los requerimientos mínimos
            print("Verificando cumplimiento de requerimientos...")
            for nutriente, requerido in ajustes_positivos.items():
                aportado = nutrientes_aportados.get(nutriente, Decimal("0.0"))
                cumplimiento = (
                    (aportado / requerido * 100) if requerido > 0 else Decimal("100.0")
                )
                print(
                    f"{nutriente}: Requerido={requerido}, Aportado={aportado}, Cumplimiento={cumplimiento:.1f}%"
                )

            return cantidades, nutrientes_aportados

        except Exception as e:
            print("Error en la optimización:", str(e))
            import traceback

            traceback.print_exc()
            raise

    def _procesar_resultado_optimizacion(self, res) -> Dict[str, Decimal]:
        """Procesa el resultado de la optimización lineal"""
        # Verificar que la solución no sea trivial (todos ceros)
        if all(x < 1e-6 for x in res.x):
            print("La solución es trivial (todos los valores son cero)")
            return {prod: Decimal("0.0") for prod in self.productos}

        # Resultados: cantidades de productos
        print("Calculando cantidades de productos...")
        cantidades = {}
        for i, x in enumerate(res.x):
            if x > 1e-6:  # Solo incluir cantidades significativas
                cantidades[self.productos[i]] = Decimal(str(round(x, 2)))
            else:
                cantidades[self.productos[i]] = Decimal("0.0")

        return cantidades

    def generar_recomendacion(self, lot_id: int) -> str:
        """
        Genera una recomendación para aplicar en el lote.

        :param lot_id: ID del lote donde se aplicará la recomendación.
        :return: Texto de la recomendación.
        """
        try:
            cantidades, nutrientes_aportados = self.optimizar_productos()

            lineas = [f"Recomendación para el lote {lot_id}:"]

            # Solo mostrar productos con cantidades significativas
            productos_aplicar = {
                prod: cant for prod, cant in cantidades.items() if cant > 0
            }

            if not productos_aplicar:
                lineas.append(
                    "- La funcionalidad de recomendación automática de fertilización "
                    "aún no está completamente implementada."
                )
                lineas.append(
                    "- Las recomendaciones de aplicación deberán ser proporcionadas "
                    "por el ingeniero agrónomo responsable, con base en el análisis "
                    "foliar, las metas del cultivo y las condiciones locales del terreno."
                )
            else:
                for prod, cantidad in productos_aplicar.items():
                    lineas.append(f"- {cantidad} unidades de {prod}")

            lineas.append("\nNutrientes aportados:")
            for nutriente, cantidad in nutrientes_aportados.items():
                if cantidad > 0:  # Solo mostrar nutrientes con aporte significativo
                    # Asumiendo que tienes acceso a macronutrients, sino puedes ajustar esta lógica
                    unidad = "kg/ha"  # Puedes ajustar esto según tu lógica de negocio
                    lineas.append(f"- {nutriente}: {cantidad} {unidad}")

            return "\n".join(lineas)

        except Exception as e:
            print(f"Error generando recomendación: {str(e)}")
            return f"Error al generar recomendación para el lote {lot_id}: {str(e)}"


class RecommendationError(Exception):
    """Raised when dose computation cannot be performed for a product."""


def compute_dose(
    product_name: str,
    cantidad: Decimal,
    price: Decimal,
    application_type: str,
    density_kg_per_l,
    price_unit: str,
    application_mode: str = "edaphic",
):
    """Compute per-hectare dose and cost for a single product in a recommendation.

    The function is pure: it does not touch the DB and does not mutate
    products / product_prices. It receives a quantity already resolved by
    the optimizer (in the unit of the price: kg if price_unit='kg', L if
    'L') and returns a dict ready to persist as a RecommendationDose row.

    Args:
        product_name: Display name of the product.
        cantidad: Quantity of product from the optimizer, in the unit of
            ``price`` (kg if powder, L if liquid).
        price: Unit price (COP per ``price_unit``).
        application_type: One of 'powder', 'liquid', 'unknown'.
        density_kg_per_l: Product density in kg/L. Required for liquids;
            ignored for powders (where it must be None).
        price_unit: 'kg' (COP/kg) or 'L' (COP/L). Must match the
            application_type semantics.
        application_mode: 'edaphic' (kg/ha or L/ha) or 'foliar'
            (unsupported in this phase - returns dose_per_ha=None).

    Returns:
        dict with keys: product, dose_per_ha, dose_unit, cost_per_ha,
        application_mode, application_type.

    Raises:
        RecommendationError: if ``application_type`` is 'unknown' or if
            a liquid product is missing ``density_kg_per_l``.
    """
    if application_type == "unknown":
        raise RecommendationError(
            f"Producto '{product_name}' sin application_type definido"
        )

    if application_mode == "foliar":
        # Gap P1 documentado: foliar necesita caldo_L_por_ha. Por ahora
        # devolvemos dose_per_ha=None y dejamos que la UI lo muestre.
        return {
            "product": product_name,
            "dose_per_ha": None,
            "dose_unit": None,
            "cost_per_ha": float(cantidad) * float(price),
            "application_mode": "foliar",
            "application_type": application_type,
        }

    # application_mode == 'edaphic' (default)
    if application_type == "powder":
        # density_kg_per_l must be None for powders (validation handled by
        # caller / seed; defensive check here for runtime safety).
        dose_per_ha = float(cantidad)
        cost_per_ha = dose_per_ha * float(price)
        return {
            "product": product_name,
            "dose_per_ha": dose_per_ha,
            "dose_unit": "kg/ha",
            "cost_per_ha": cost_per_ha,
            "application_mode": "edaphic",
            "application_type": "powder",
        }

    if application_type == "liquid":
        if density_kg_per_l is None:
            raise RecommendationError(
                f"Producto líquido '{product_name}' sin density_kg_per_l"
            )
        # cantidad está en L (porque price_unit='L' para líquidos).
        # dosis_L_per_ha = cantidad (1 ha como unidad de superficie);
        # conversión a kg sólo si la UI lo pide.
        dose_per_ha = float(cantidad)
        cost_per_ha = dose_per_ha * float(price)
        return {
            "product": product_name,
            "dose_per_ha": dose_per_ha,
            "dose_unit": "L/ha",
            "cost_per_ha": cost_per_ha,
            "application_mode": "edaphic",
            "application_type": "liquid",
        }

    raise RecommendationError(
        f"application_type inválido '{application_type}' para '{product_name}'"
    )


def compute_dose_from_contributions(
    productos_contribuciones: Dict[str, Dict[str, Decimal]],
    productos_precios: Dict[str, Decimal],
    nutrientes_actuales: Dict[str, Decimal],
    demandas_ideales: Dict[str, Decimal],
    application_type_lookup: Dict[str, str],
    density_lookup,
    price_unit_lookup: Dict[str, str],
    typical_dose_per_ha_lookup: Dict[str, Decimal],
    typical_dose_unit_lookup: Dict[str, str],
    application_mode: str = "edaphic",
    deficiency_threshold: float = 0.8,
):
    """Select deficient nutrients and recommend one product per nutrient.

    The application dose for each product comes from the technical
    sheet (``typical_dose_per_ha_lookup``), NOT from a deficit /
    contribution calculation. The latter was the source of the fase-4
    bug (e.g. 833 kg/ha of a 6% N powder when the foliar analysis was
    3.188% vs ideal 3.39%): the % foliar deficit was being divided by
    the % p/p contribution with no dimensional check.

    Algorithm:
      1. For each nutrient with ``actual < ideal * threshold``
         (default 80% of target), mark as deficient.
      2. For each deficient nutrient, find the most efficient product
         in the catalogue: highest ``contribution`` for that nutrient
         (tiebreak: lowest cost at the typical dose).
      3. Recommend that product with its ``typical_dose_per_ha``
         (no further math; the agronomist applies the recommended
         dose range from the technical sheet).
      4. Persist one row per product via ``compute_dose()``.

    Args:
        productos_contribuciones: {product_name: {nutrient_name: Decimal}}
            Values are FRACTIONS in pct_p_p (e.g. 0.33 = 33% K in Kn32).
        productos_precios: {product_name: Decimal} (COP per price_unit).
        nutrientes_actuales: {nutrient_name: Decimal} from LeafAnalysis.
        demandas_ideales: {nutrient_name: Decimal} from Objective.
        application_type_lookup: {product_name: 'powder'|'liquid'|'unknown'}.
        density_lookup: {product_name: Decimal|None} kg/L (liquids only).
        price_unit_lookup: {product_name: 'kg'|'L'}.
        typical_dose_per_ha_lookup: {product_name: Decimal} from
            products.dose_typical_kg_per_ha (in dose_typical_unit units).
        typical_dose_unit_lookup: {product_name: 'kg_per_ha'|'L_per_ha'}.
        application_mode: 'edaphic' (default) or 'foliar' (gap P1).
        deficiency_threshold: nutrient is deficient if
            actual/ideal < threshold. 0.8 = "below 80% of target".

    Returns:
        list of dicts ready to persist as RecommendationDose rows:
        [{product_id, product_name, dose_per_ha, dose_unit, cost_per_ha,
          application_mode, application_type, deficiencies_covered}, ...]

    Products with application_type='unknown' or NULL typical_dose are
    skipped (logged as warning).
    """
    # 1) Identificar nutrientes deficientes (umbral: actual/ideal < threshold)
    deficient_nutrients = []
    for nutrient, ideal in demandas_ideales.items():
        if ideal <= 0:
            continue
        actual = nutrientes_actuales.get(nutrient, Decimal("0"))
        if actual < ideal * Decimal(str(deficiency_threshold)):
            deficient_nutrients.append(nutrient)
    if not deficient_nutrients:
        return []

    # 2) Para cada nutriente deficiente, elegir el producto más eficiente.
    #    Eficiencia = contribution (fracción, mayor = más eficiente).
    #    Desempate: menor costo típico (precio × typical_dose).
    #    Solo consideramos productos con application_type conocido y
    #    typical_dose_per_ha > 0 (ficha técnica disponible).
    product_to_nutrients: Dict[str, list[str]] = {}
    product_dose: Dict[str, Decimal] = {}  # en la unidad del price
    nutrients_uncovered: list[str] = []

    for nutrient in deficient_nutrients:
        candidatos = []
        for product_name, contribs in productos_contribuciones.items():
            contrib = contribs.get(nutrient, Decimal("0"))
            if contrib <= 0:
                continue
            app_type = application_type_lookup.get(product_name, "unknown")
            if app_type not in ("powder", "liquid"):
                continue
            typical = typical_dose_per_ha_lookup.get(product_name)
            if typical is None or typical <= 0:
                continue
            price = productos_precios.get(product_name, Decimal("0"))
            if price <= 0:
                continue
            # Costo típico total = price (COP/price_unit) × typical_dose
            # (en unidades del producto, == price_unit en este caller).
            # Es comparable entre powder y liquid porque ambos precios
            # están en su unidad de venta.
            cost_typical = float(price) * float(typical)
            candidatos.append((product_name, float(contrib), cost_typical))

        if not candidatos:
            nutrients_uncovered.append(nutrient)
            continue

        # Mayor contribution; desempate por menor costo típico
        candidatos.sort(key=lambda x: (-x[1], x[2]))
        product_name, _contrib, _cost = candidatos[0]
        # El producto se queda con su typical_dose (sin modificar)
        product_to_nutrients.setdefault(product_name, []).append(nutrient)
        product_dose[product_name] = typical_dose_per_ha_lookup[product_name]

    if nutrients_uncovered:
        import logging

        logging.getLogger(__name__).warning(
            f"[dose:contributions] sin producto con contribution+dose para "
            f"nutrientes: {nutrients_uncovered}"
        )

    # 3) Materializar cada producto via compute_dose() puro.
    out = []
    for product_name, _nutrients in product_to_nutrients.items():
        if product_dose[product_name] <= 0:
            continue
        price = productos_precios.get(product_name, Decimal("0"))
        try:
            dose = compute_dose(
                product_name=product_name,
                cantidad=product_dose[product_name],
                price=price,
                application_type=application_type_lookup.get(product_name, "unknown"),
                density_kg_per_l=density_lookup.get(product_name),
                price_unit=price_unit_lookup.get(product_name, "kg"),
                application_mode=application_mode,
            )
        except RecommendationError as e:
            current_app.logger.info(f"[dose:contributions] {product_name} omitido: {e}")
            continue
        out.append(
            {
                "product_name": product_name,
                "dose_per_ha": dose["dose_per_ha"],
                "dose_unit": dose["dose_unit"],
                "cost_per_ha": dose["cost_per_ha"],
                "application_mode": dose["application_mode"],
                "application_type": dose["application_type"],
            }
        )
    return out


def compute_nano_dose_rows(
    mineral_balance: Dict[str, object],
    symbol_to_name: Dict[str, str],
    productos_contribuciones: Dict[str, Dict[str, Decimal]],
    productos_precios: Dict[str, Decimal],
    price_unit_lookup: Dict[str, str],
    *,
    digits: int = 2,
) -> Dict[str, object]:
    """Cost the mineral-balance deficits with the nano product line.

    For every deficit in ``mineral_balance`` (output of
    ``compute_mineral_balance``), compare the catalogue products that
    contribute the deficient nutrient (only the nano line has
    ``ProductContribution`` rows) and keep the one that covers the
    requirement at the lowest cost. The dose follows the FRM_Balance
    nano convention — deficit kg/ha divided by the product grade
    expressed as a percent number (contribution × 100), the same math
    behind the table's ``nano_kg`` row but using the real grade of the
    selected product instead of the fixed N16/P11/K19 constants.

    Greedy per nutrient; when one product wins several nutrients the
    rows consolidate into one with the max dose (the larger dose covers
    the smaller requirements of the same product).

    Args:
        mineral_balance: ``{"entries": [...], "total_kg_ha": ...}`` where
            each entry has ``name`` (nutrient symbol) and
            ``difference_kg`` (deficit ≤ 0 in kg/ha, or None).
        symbol_to_name: Nutrient symbol → catalogue name (the keys used
            by ``productos_contribuciones``).
        productos_contribuciones: {product_name: {nutrient_name: Decimal}}
            fractions p/p (0.17 = 17%).
        productos_precios: {product_name: Decimal} COP per price unit.
        price_unit_lookup: {product_name: 'kg' | 'L'}.
        digits: rounding for doses and costs.

    Returns:
        ``{"rows": [...], "total_cost_per_ha": float|None,
        "uncovered": [symbols]}``. Each row:
        ``{product_name, nutrients (symbols), contribution_pct,
        dose_kg_ha, cost_per_ha, price_unit, approx}`` — ``approx`` is
        True when the price is per litre (cost assumes 1 kg ≈ 1 L).
        ``nutrient_grades`` maps each nutrient symbol to the contribution
        percentage (grade) of the cheapest product that covers it, for
        use in the per‑nutrient mineral-balance table.
    """
    entries = mineral_balance.get("entries") or []
    by_product: Dict[str, Dict[str, object]] = {}
    uncovered: list[str] = []
    nutrient_grades: Dict[str, float] = {}

    for entry in entries:
        diff = entry.get("difference_kg")
        if diff is None or diff >= 0:
            continue
        deficit = abs(float(diff))
        symbol = str(entry.get("name") or "")
        nutrient_name = symbol_to_name.get(symbol)
        if not nutrient_name:
            uncovered.append(symbol)
            continue

        best = None  # (cost, dose, product_name, contribution)
        for product_name, contribs in productos_contribuciones.items():
            contrib = float(contribs.get(nutrient_name, 0))
            if contrib <= 0:
                continue
            price = float(productos_precios.get(product_name, 0))
            if price <= 0:
                continue
            dose = deficit / (contrib * 100)
            cost = dose * price
            if best is None or cost < best[0]:
                best = (cost, dose, product_name, contrib)

        if best is None:
            uncovered.append(symbol)
            continue

        cost, dose, product_name, contrib = best
        nutrient_grades[symbol] = round(contrib * 100, 1)
        row = by_product.get(product_name)
        if row is None or dose > row["dose_kg_ha"]:
            price_unit = price_unit_lookup.get(product_name, "kg")
            by_product[product_name] = {
                "product_name": product_name,
                "nutrients": (row["nutrients"] if row else []) + [symbol],
                "contribution_pct": contrib * 100,
                "dose_kg_ha": dose,
                "cost_per_ha": cost,
                "price_unit": price_unit,
                "approx": price_unit == "L",
            }
        else:
            row["nutrients"].append(symbol)

    rows = []
    total_cost = 0.0
    for row in by_product.values():
        row["contribution_pct"] = round(row["contribution_pct"], 1)
        row["dose_kg_ha"] = round(row["dose_kg_ha"], digits)
        row["cost_per_ha"] = round(row["cost_per_ha"], digits)
        total_cost += row["cost_per_ha"]
        rows.append(row)

    return {
        "rows": rows,
        "total_cost_per_ha": round(total_cost, digits) if rows else None,
        "uncovered": uncovered,
        "nutrient_grades": nutrient_grades,
    }


# # # Datos de ejemplo basados en los nutrientes proporcionados
# macronutrients = [
#     {"name": "Nitrógeno", "symbol": "N", "unit": "kg/ha", "category": "MACRONUTRIENT"},
#     {"name": "Fósforo", "symbol": "P", "unit": "kg/ha", "category": "MACRONUTRIENT"},
#     {"name": "Potasio", "symbol": "K", "unit": "kg/ha", "category": "MACRONUTRIENT"},
#     {"name": "Calcio", "symbol": "Ca", "unit": "kg/ha", "category": "MACRONUTRIENT"},
#     {"name": "Magnesio", "symbol": "Mg", "unit": "kg/ha", "category": "MACRONUTRIENT"},
#     {"name": "Azufre", "symbol": "S", "unit": "kg/ha", "category": "MACRONUTRIENT"},
# ]

# micronutrients = [
#     {"name": "Cobre", "symbol": "Cu", "unit": "g/ha", "category": "MICRONUTRIENT"},
#     {"name": "Zinc", "symbol": "Zn", "unit": "g/ha", "category": "MICRONUTRIENT"},
#     {"name": "Manganeso", "symbol": "Mn", "unit": "g/ha", "category": "MICRONUTRIENT"},
#     {"name": "Boro", "symbol": "B", "unit": "g/ha", "category": "MICRONUTRIENT"},
#     {"name": "Molibdeno", "symbol": "Mo", "unit": "g/ha", "category": "MICRONUTRIENT"},
#     {"name": "Cloro", "symbol": "Cl", "unit": "g/ha", "category": "MICRONUTRIENT"},
#     {"name": "Hierro", "symbol": "Fe", "unit": "g/ha", "category": "MICRONUTRIENT"},
#     {"name": "Silicio", "symbol": "Si", "unit": "kg/ha", "category": "MICRONUTRIENT"},
# ]

# # Ejemplo de uso
# nutrientes_actuales = {
#     "Nitrógeno": Decimal("50.0"),  # kg/ha
#     "Fósforo": Decimal("20.0"),    # kg/ha
#     "Potasio": Decimal("80.0"),    # kg/ha
#     "Cobre": Decimal("100.0"),     # g/ha
#     "Zinc": Decimal("50.0")        # g/ha
# }

# demandas_ideales = {
#     "Nitrógeno": Decimal("100.0"),  # kg/ha
#     "Fósforo": Decimal("50.0"),     # kg/ha
#     "Potasio": Decimal("90.0"),     # kg/ha
#     "Cobre": Decimal("150.0"),      # g/ha
#     "Zinc": Decimal("80.0")         # g/ha
# }

# productos_contribuciones = {
#     "Fertilizante A": {"Nitrógeno": Decimal("10.0"), "Fósforo": Decimal("5.0"), "Potasio": Decimal("2.0")},
#     "Fertilizante B": {"Nitrógeno": Decimal("5.0"), "Fósforo": Decimal("15.0"), "Cobre": Decimal("20.0")},
#     "Fertilizante C": {"Zinc": Decimal("30.0"), "Cobre": Decimal("10.0")}
# }

# coeficientes_variacion = {
#     "Nitrógeno": Decimal("0.5"),
#     "Fósforo": Decimal("0.3"),
#     "Potasio": Decimal("0.4"),
#     "Cobre": Decimal("0.2"),
#     "Zinc": Decimal("0.25")
# }

# # Instanciar y usar la clase
# optimizador = NutrientOptimizer(nutrientes_actuales, demandas_ideales, productos_contribuciones, coeficientes_variacion)
# limitante = optimizador.identificar_limitante()
# print(f"Nutriente limitante: {limitante}")

# recomendacion = optimizador.generar_recomendacion(lot_id=1)
# print(recomendacion)


def calcular_cv_nutriente(lot_id, nutriente_name):
    """Determinar los Coeficientes de Variación"""
    # Find the nutrient first - may not exist
    nutrient = Nutrient.query.filter_by(name=nutriente_name).first()
    if nutrient is None:
        return Decimal("0.5")  # Default if nutrient doesn't exist

    valores = (
        db.session.query(leaf_analysis_nutrients.c.value)
        .join(LeafAnalysis)
        .join(CommonAnalysis)
        .filter(
            CommonAnalysis.lot_id == lot_id,
            leaf_analysis_nutrients.c.nutrient_id == nutrient.id,
        )
        .all()
    )
    valores = [v[0] for v in valores]
    if len(valores) < 2:
        return Decimal("0.5")  # Valor por defecto si no hay suficientes datos
    mu = mean(valores)
    # Guard against division by zero (all values are 0)
    if mu == 0:
        return Decimal("0.5")
    sigma = stdev(valores)
    return Decimal(str(sigma / mu)).quantize(Decimal("0.01"))


# ejemplo.
# cv_nitrogeno = calcular_cv_nutriente(lot_id=1, nutriente_name="Nitrógeno")
# print(f"CV Nitrógeno: {cv_nitrogeno}")

# Calculo por ajuste dinámico.
# Datos históricos: Calcula el CV estadístico si hay suficientes análisis previos.
# Valores por defecto: Usa estándares agrícolas si no hay datos.
# Ajuste dinámico: Permite que un usuario (ej., agrónomo) modifique los CV según observaciones locales.


def determinar_coeficientes_variacion(lot_id: int) -> Dict[str, Decimal]:
    coeficientes = {}
    nutrientes = [n["name"] for n in macronutrients + micronutrients]
    for nutriente in nutrientes:
        cv = calcular_cv_nutriente(lot_id, nutriente)
        if cv == Decimal("0.5"):  # Valor por defecto si no hay datos
            # Asignar valores basados en literatura
            if nutriente in ["Nitrógeno"]:
                cv = Decimal("0.5")
            elif nutriente in ["Fósforo"]:
                cv = Decimal("0.3")
            elif nutriente in ["Potasio"]:
                cv = Decimal("0.4")
            elif nutriente in ["Cobre", "Zinc"]:
                cv = Decimal("0.25")
            else:
                cv = Decimal("0.3")  # Default genérico
        coeficientes[nutriente] = cv
    return coeficientes


def contribuciones_de_producto():
    """Contribuciones de producto"""
    product_contributions = ProductContribution.query.all()

    result = {}

    for pc in product_contributions:
        product_name = pc.product.name

        if product_name not in result:
            result[product_name] = {}

        nutrient_contributions = (
            db.session.query(product_contribution_nutrients)
            .filter_by(product_contribution_id=pc.id)
            .all()
        )

        for contribution in nutrient_contributions:
            nutrient = Nutrient.query.get(contribution.nutrient_id)
            result[product_name][nutrient.name] = Decimal(
                str(contribution.contribution)
            )

    return result


def precios_de_producto():
    """Precios de producto"""
    product_prices = ProductPrice.query.filter(
        ProductPrice.start_date <= datetime.now(),
        ProductPrice.end_date >= datetime.now(),
    ).all()

    result = {}
    for pp in product_prices:
        result[pp.product.name] = Decimal(str(pp.price))

    return result


##################################################################
class ObjectiveResource:
    def get_objective_list(self):
        objectives = Objective.query.all()
        crop_data = self._process_objectives_by_crop(objectives)
        return CropResponse(crop_data)

    def _serialize_objective(self, objective):
        """Serialize an Objective object to a dictionary (unchanged from your code)"""
        nutrient_targets = (
            db.session.query(objective_nutrients)
            .filter_by(objective_id=objective.id)
            .all()
        )
        nutrient_targets_dict = [
            {
                "nutrient_id": target.nutrient_id,
                "target_value": Decimal(str(target.target_value)),  # Convert to Decimal
                "nutrient_name": Nutrient.query.get(target.nutrient_id).name,
                "nutrient_symbol": Nutrient.query.get(target.nutrient_id).symbol,
                "nutrient_unit": Nutrient.query.get(target.nutrient_id).unit,
            }
            for target in nutrient_targets
        ]
        return {
            "id": objective.id,
            "crop_id": objective.crop_id,
            "crop_name": objective.crop.name,
            "target_value": Decimal(str(objective.target_value)),
            "protein": Decimal(str(objective.protein)),
            "rest": Decimal(str(objective.rest)),
            "created_at": objective.created_at.isoformat(),
            "updated_at": objective.updated_at.isoformat(),
            "nutrient_targets": nutrient_targets_dict,
        }

    def _process_objectives_by_crop(self, objectives):
        """Process objectives into a dictionary grouped by crop name with multiple objectives"""
        crop_dict = {}
        for obj in objectives:
            serialized = self._serialize_objective(obj)
            crop_name = serialized["crop_name"].lower()  # e.g., 'arroz', 'papa'

            # Initialize crop entry as a list if not present
            if crop_name not in crop_dict:
                crop_dict[crop_name] = []

            # Simplify nutrient targets into a dict for easier access
            nutrient_dict = {
                target["nutrient_name"]: target["target_value"]
                for target in serialized["nutrient_targets"]
            }
            # Add objective data to the crop's list
            crop_dict[crop_name].append(
                {
                    "id": serialized["id"],
                    "created_at": serialized["created_at"],
                    "updated_at": serialized["updated_at"],
                    "nutrients": nutrient_dict,
                }
            )

        return crop_dict


class CropResponse:
    """Custom response class to allow accessing crop data like response.arroz"""

    def __init__(self, crop_data):
        self.crop_data = crop_data
        # Dynamically set attributes for each crop
        for crop_name in crop_data:
            setattr(self, crop_name, CropObjectives(crop_data[crop_name]))

    def get_json(self):
        """Return the full crop data as JSON"""
        return json.dumps(self.crop_data, ensure_ascii=False, indent=4, default=str)


class CropObjectives:
    """Class to handle multiple objectives for a single crop"""

    def __init__(self, objectives):
        self.objectives = objectives  # List of objectives for this crop

    def get(self, index=None, id=None):
        """Access a specific objective by index or id"""
        if id is not None:
            for obj in self.objectives:
                if obj["id"] == id:
                    return CropData(obj["nutrients"])
            raise ValueError(f"No objective found with id {id}")
        if index is not None:
            if 0 <= index < len(self.objectives):
                return CropData(self.objectives[index]["nutrients"])
            raise IndexError(
                f"Index {index} out of range for {len(self.objectives)} objectives"
            )
        # Default: return the most recent objective (based on updated_at)
        sorted_objectives = sorted(
            self.objectives, key=lambda x: x["updated_at"], reverse=True
        )
        return CropData(sorted_objectives[0]["nutrients"])

    def all(self):
        """Return all objectives as a list of CropData objects"""
        return [CropData(obj["nutrients"]) for obj in self.objectives]

    def get_json(self):
        """Return all objectives as JSON"""
        return json.dumps(self.objectives, ensure_ascii=False, indent=4, default=str)


class CropData:
    """Helper class to represent nutrient data for a single objective"""

    def __init__(self, nutrient_data):
        self.nutrient_data = nutrient_data

    def get_json(self):
        """Return nutrient data as JSON"""
        return json.dumps(self.nutrient_data, ensure_ascii=False, indent=4, default=str)

    def __str__(self):
        """String representation for printing"""
        return str({k: str(v) for k, v in self.nutrient_data.items()})


########################################################

# leaf_analyses


class LeafAnalysisResource:
    def get_leaf_analysis_list(self):
        leaf_analyses = LeafAnalysis.query.all()

        # Process leaf analyses into a structure grouped by common_analysis_id
        analysis_data = self._process_leaf_analyses_by_common_id(leaf_analyses)
        return LeafAnalysisResponse(analysis_data)

    def _serialize_leaf_analysis(self, leaf_analysis):
        """Serializa un objeto LeafAnalysis a un diccionario."""
        nutrient_values = (
            db.session.query(leaf_analysis_nutrients)
            .filter_by(leaf_analysis_id=leaf_analysis.id)
            .all()
        )
        nutrient_values_dict = [
            {
                "nutrient_id": nv.nutrient_id,
                "value": Decimal(str(nv.value)),  # Convert to Decimal
                "nutrient_name": Nutrient.query.get(nv.nutrient_id).name,
                "nutrient_symbol": Nutrient.query.get(nv.nutrient_id).symbol,
                "nutrient_unit": Nutrient.query.get(nv.nutrient_id).unit,
            }
            for nv in nutrient_values
        ]
        return {
            "id": leaf_analysis.id,
            "common_analysis_id": leaf_analysis.common_analysis_id,
            "created_at": leaf_analysis.created_at.isoformat(),
            "updated_at": leaf_analysis.updated_at.isoformat(),
            "nutrient_values": nutrient_values_dict,
        }

    def _process_leaf_analyses_by_common_id(self, leaf_analyses):
        """Process leaf analyses into a dictionary grouped by common_analysis_id."""
        analysis_dict = {}
        for leaf_analysis in leaf_analyses:
            serialized = self._serialize_leaf_analysis(leaf_analysis)
            common_id = str(
                serialized["common_analysis_id"]
            )  # Convert to string for attribute access

            # Initialize entry as a list if not present
            if common_id not in analysis_dict:
                analysis_dict[common_id] = []

            # Simplify nutrient values into a dict
            nutrient_dict = {
                nutrient["nutrient_name"]: nutrient["value"]
                for nutrient in serialized["nutrient_values"]
            }
            # Add analysis data to the common_analysis_id's list
            analysis_dict[common_id].append(
                {
                    "id": serialized["id"],
                    "created_at": serialized["created_at"],
                    "updated_at": serialized["updated_at"],
                    "nutrients": nutrient_dict,
                }
            )

        return analysis_dict


class LeafAnalysisResponse:
    """Custom response class to allow accessing leaf analyses like response.common_analysis_id.<id>"""

    def __init__(self, analysis_data):
        self.analysis_data = analysis_data
        # Dynamically create a nested object for common_analysis_id
        self.common_analysis_id = CommonAnalysisContainer(analysis_data)

    def get_json(self):
        """Return the full analysis data as JSON"""
        return json.dumps(self.analysis_data, ensure_ascii=False, indent=4, default=str)


class CommonAnalysisContainer:
    """Container for accessing leaf analyses by common_analysis_id"""

    def __init__(self, analysis_data):
        self.analysis_data = analysis_data
        # Dynamically set attributes for each common_analysis_id
        for common_id in analysis_data:
            setattr(self, common_id, LeafAnalyses(self.analysis_data[common_id]))


class LeafAnalyses:
    """Class to handle multiple leaf analyses for a single common_analysis_id"""

    def __init__(self, analyses):
        self.analyses = analyses  # List of leaf analyses for this common_analysis_id

    def get(self, index=None, id=None):
        """Access a specific leaf analysis by index or id"""
        if id is not None:
            for analysis in self.analyses:
                if analysis["id"] == id:
                    return LeafAnalysisData(analysis["nutrients"])
            raise ValueError(f"No leaf analysis found with id {id}")
        if index is not None:
            if 0 <= index < len(self.analyses):
                return LeafAnalysisData(self.analyses[index]["nutrients"])
            raise IndexError(
                f"Index {index} out of range for {len(self.analyses)} analyses"
            )
        # Default: return the most recent analysis (based on updated_at)
        sorted_analyses = sorted(
            self.analyses, key=lambda x: x["updated_at"], reverse=True
        )
        return LeafAnalysisData(sorted_analyses[0]["nutrients"])

    def all(self):
        """Return all analyses as a list of LeafAnalysisData objects"""
        return [LeafAnalysisData(analysis["nutrients"]) for analysis in self.analyses]

    def get_json(self):
        """Return all analyses as JSON"""
        return json.dumps(self.analyses, ensure_ascii=False, indent=4, default=str)


class LeafAnalysisData:
    """Helper class to represent nutrient data for a single leaf analysis"""

    def __init__(self, nutrient_data):
        self.nutrient_data = nutrient_data

    def get_json(self):
        """Return nutrient data as JSON"""
        return json.dumps(self.nutrient_data, ensure_ascii=False, indent=4, default=str)

    def __str__(self):
        """String representation for printing"""
        return str({k: str(v) for k, v in self.nutrient_data.items()})


#  Título	Finca / Lote	Cultivo	Fecha	Tipo	Autor
"""
Reportes, incluirán los datos completos de un análisis completo común (CommonAnalysis)
ahí se identificará el análisis de suelo (SoilAnalysis) y foliar (LeafAnalysis, debe incluir los nutrientes relacionados de la tabla leaf_analysis_nutrients ) relacionados con el ID del CommonAnalysis, esto deben presentarse así (Nota, los datos y listado de nutriente deben obtenerse de los registrados en el modelo Nutrient):


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

optimalLevels se obtendrá a partir del tipo de cultivo, este se comparará con los tipos de cultivo registrados en Crops y sus valores de nutrientes registrados en objective_nutrients (Nota, los datos y listado de nutriente deben obtenerse de los registrados en el modelo Nutrient)
    optimalLevels = {
        VALOR OBJETIVO	PROTEÍNA	DESCANSO
        "info": {
            "cultivo": "papa",
            "valor_obj": "10",
            "proteina": "8",
            "descanso": "5",

        }
        "nutrientes": {
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
    }

    foliarChartData = [
        {"name": "N", "actual": analysisData["foliar"]["nitrogeno"], "min": optimalLevels["foliar"]["nitrogeno"]["min"], "max": optimalLevels["foliar"]["nitrogeno"]["max"]},
        {"name": "P", "actual": analysisData["foliar"]["fosforo"], "min": optimalLevels["foliar"]["fosforo"]["min"], "max": optimalLevels["foliar"]["fosforo"]["max"]},
        {"name": "K", "actual": analysisData["foliar"]["potasio"], "min": optimalLevels["foliar"]["potasio"]["min"], "max": optimalLevels["foliar"]["potasio"]["max"]},
        {"name": "Ca", "actual": analysisData["foliar"]["calcio"], "min": optimalLevels["foliar"]["calcio"]["min"], "max": optimalLevels["foliar"]["calcio"]["max"]},
        {"name": "Mg", "actual": analysisData["foliar"]["magnesio"], "min": optimalLevels["foliar"]["magnesio"]["min"], "max": optimalLevels["foliar"]["magnesio"]["max"]},
        {"name": "S", "actual": analysisData["foliar"]["azufre"], "min": optimalLevels["foliar"]["azufre"]["min"], "max": optimalLevels["foliar"]["azufre"]["max"]},
    ]

    soilChartData = [
        {"name": "pH", "actual": analysisData["soil"]["ph"], "min": optimalLevels["soil"]["ph"]["min"], "max": optimalLevels["soil"]["ph"]["max"], "unit": ""},
        {"name": "M.O.", "actual": analysisData["soil"]["materiaOrganica"], "min": optimalLevels["soil"]["materiaOrganica"]["min"], "max": optimalLevels["soil"]["materiaOrganica"]["max"], "unit": "%"},
        {"name": "N", "actual": analysisData["soil"]["nitrogeno"], "min": optimalLevels["soil"]["nitrogeno"]["min"], "max": optimalLevels["soil"]["nitrogeno"]["max"], "unit": "%"},
        {"name": "P", "actual": analysisData["soil"]["fosforo"], "min": optimalLevels["soil"]["fosforo"]["min"], "max": optimalLevels["soil"]["fosforo"]["max"], "unit": "ppm"},
        {"name": "K", "actual": analysisData["soil"]["potasio"], "min": optimalLevels["soil"]["potasio"]["min"], "max": optimalLevels["soil"]["potasio"]["max"], "unit": "ppm"},
        {"name": "CIC", "actual": analysisData["soil"]["cic"], "min": optimalLevels["soil"]["cic"]["min"], "max": optimalLevels["soil"]["cic"]["max"], "unit": "meq/100g"},
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
            nutrientName = nutrientNames[limitingNutrient["name"]] or limitingNutrient["name"]
            recommendations.append({
                "title": f"Corregir deficiencia de {nutrientName}",
                "description": f"El {nutrientName} es el nutriente limitante según la Ley de Liebig. Está al limitingNutrient['percentage']% del nivel óptimo.",
                "priority": "alta",
                "action": "Aplicar fertilizante foliar rico en {nutrientName}" if limitingNutrient["type"] == "foliar" else f"Incorporar {nutrientName} al suelo mediante fertilización",
            })

        phStatus = getNutrientStatus(analysisData["soil"]["ph"], optimalLevels["soil"]["ph"]["min"], optimalLevels["soil"]["ph"]["max"])
        if phStatus != "óptimo":
            recommendations.append({
                "title": "Corregir acidez del suelo" if phStatus == "deficiente" else "Reducir alcalinidad del suelo",
                "description": f"El pH actual ({analysisData['soil']['ph']}) está {'por debajo' if phStatus == 'deficiente' else 'por encima'} del rango óptimo.",
                "priority": "media",
                "action": "Aplicar cal agrícola para elevar el pH" if phStatus == "deficiente" else "Aplicar azufre elemental o materia orgánica para reducir el pH",
            })

        moStatus = getNutrientStatus(analysisData["soil"]["materiaOrganica"], optimalLevels["soil"]["materiaOrganica"]["min"], optimalLevels["soil"]["materiaOrganica"]["max"])
        if moStatus == "deficiente":
            recommendations.append({
                "title": "Aumentar materia orgánica",
                "description": f"El nivel de materia orgánica ({analysisData['soil']['materiaOrganica']}%) está por debajo del óptimo.",
                "priority": "media",
                "action": "Incorporar compost, estiércol bien descompuesto o abonos verdes",
            })

        return recommendations

    limitingNutrient = findLimitingNutrient()
    recommendations = generateRecommendations()
"""


def compare_analyses(pre_analysis_id: int, post_analysis_id: int) -> dict:
    """
    Compara dos CommonAnalysis del mismo lote nutriente a nutriente.

    Retorna delta absoluto, delta pct y veredicto usando Nutrient.cv como
    umbral de significancia. El veredicto es uno de:
        "improved"   | delta_pct > cv_threshold
        "worsened"   | delta_pct < -cv_threshold
        "unchanged"  | |delta_pct| <= cv_threshold
        "incomplete" | falta valor pre o post

    Args:
        pre_analysis_id (int): ID del CommonAnalysis base (pre-aplicación).
        post_analysis_id (int): ID del CommonAnalysis posterior.

    Returns:
        dict: Estructura con lot_id, fechas, days_elapsed, nutrients map
              (por nombre) y summary con conteo de veredictos.

    Raises:
        ValueError: Si alguno de los análisis no existe o son de lotes
                    distintos.
    """
    from sqlalchemy.orm import joinedload

    pre = CommonAnalysis.query.options(
        joinedload(CommonAnalysis.leaf_analysis).joinedload(LeafAnalysis.nutrients)
    ).get(pre_analysis_id)
    post = CommonAnalysis.query.options(
        joinedload(CommonAnalysis.leaf_analysis).joinedload(LeafAnalysis.nutrients)
    ).get(post_analysis_id)

    if not pre or not post:
        raise ValueError("CommonAnalysis no encontrado.")
    if pre.lot_id != post.lot_id:
        raise ValueError("Los análisis no pertenecen al mismo lote.")

    def _get_nutrient_map(analysis):
        if not analysis.leaf_analysis:
            return {}
        # Los valores se consultan en leaf_analysis_nutrients (value Float).
        # Recorremos el join Nutrient<->leaf_analysis_nutrients para tener
        # tanto el Nutrient (para cv) como el value.
        return {n.name: n for n in analysis.leaf_analysis.nutrients}

    # Para mapear valor, hacemos una segunda pasada explícita via la tabla
    # de asociación. Esto evita un N+1 al acceder a .value.
    def _get_value_map(analysis):
        if not analysis.leaf_analysis:
            return {}
        from app.modules.foliage.models import leaf_analysis_nutrients

        rows = (
            db.session.query(
                leaf_analysis_nutrients.c.nutrient_id, leaf_analysis_nutrients.c.value
            )
            .filter(
                leaf_analysis_nutrients.c.leaf_analysis_id == analysis.leaf_analysis.id
            )
            .all()
        )
        nutrient_ids = [r[0] for r in rows]
        nutrients_by_id = (
            {
                n.id: n
                for n in Nutrient.query.filter(Nutrient.id.in_(nutrient_ids)).all()
            }
            if nutrient_ids
            else {}
        )
        return {
            nutrients_by_id[nid].name: (nutrients_by_id[nid], value)
            for nid, value in rows
            if nid in nutrients_by_id
        }

    pre_map = _get_value_map(pre)
    post_map = _get_value_map(post)

    all_names = set(pre_map) | set(post_map)
    nutrients_result = {}

    for name in sorted(all_names):
        pre_entry = pre_map.get(name)
        post_entry = post_map.get(name)
        pre_val = pre_entry[1] if pre_entry else None
        post_val = post_entry[1] if post_entry else None

        if pre_val is None or post_val is None:
            nutrients_result[name] = {
                "pre": pre_val,
                "post": post_val,
                "delta": None,
                "delta_pct": None,
                "cv_threshold": None,
                "status": "incomplete",
            }
            continue

        # Tomamos Nutrient desde cualquiera de los dos mapas
        nutrient_obj = (pre_entry or post_entry)[0]
        cv_threshold = nutrient_obj.cv if nutrient_obj.cv else 5.0

        delta = post_val - pre_val
        delta_pct = (delta / pre_val * 100) if pre_val != 0 else None

        if delta_pct is None:
            status = "incomplete"
        elif delta_pct > cv_threshold:
            status = "improved"
        elif delta_pct < -cv_threshold:
            status = "worsened"
        else:
            status = "unchanged"

        nutrients_result[name] = {
            "pre": round(pre_val, 4),
            "post": round(post_val, 4),
            "delta": round(delta, 4),
            "delta_pct": round(delta_pct, 2) if delta_pct is not None else None,
            "cv_threshold": cv_threshold,
            "status": status,
        }

    counts = {"improved": 0, "worsened": 0, "unchanged": 0, "incomplete": 0}
    for v in nutrients_result.values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1

    return {
        "lot_id": pre.lot_id,
        "pre": {"analysis_id": pre.id, "date": str(pre.date)},
        "post": {"analysis_id": post.id, "date": str(post.date)},
        "days_elapsed": (post.date - pre.date).days if pre.date and post.date else None,
        "nutrients": nutrients_result,
        "summary": counts,
    }
