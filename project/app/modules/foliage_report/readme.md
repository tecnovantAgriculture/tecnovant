# 📑 Foliage Report – Informes y Recomendaciones Nutritivas

Módulo encargado de **generar, listar y visualizar informes foliares integrados**. Combina datos provenientes de `foliage` (análisis comunes, foliares y objetivos) con algoritmos agronómicos propios (Ley del Mínimo de Liebig, optimización lineal de nutrientes, coeficientes de variación) para producir recomendaciones automatizadas, comparativas históricas y visualizaciones ricas listas para compartir con clientes.

---

## 🧩 1. Estructura General

| Componente | Ubicación | Descripción |
| --- | --- | --- |
| **Blueprint web** | `app/modules/foliage_report/__init__.py` (`foliage_report`) | Vistas HTML bajo `/dashboard/foliage_report/*`. |
| **Blueprint API** | `foliage_report_api` | Endpoints JSON en `/api/foliage/report/*`. |
| **Controlador** | `controller.py` | `ReportView`, `RecommendationView`, `RecommendationGenerator`, `RecommendationFilterView`, `DeleteRecommendationView`. |
| **Helpers** | `helpers.py` | Ley de Liebig, `NutrientOptimizer` (SciPy), recursos Leaf/Objective, coeficientes de variación, plantillas de aportes/precios. |
| **Plantillas** | `templates/*.j2` | UI para listar, solicitar y visualizar informes (`listar_reportes.j2`, `view_report.j2`, `ver_reporte.j2`, etc.). |
| **Rutas web** | `web_routes.py` | Dashboards, filtros combinados, cálculos de tendencias y render final. |
| **Rutas API** | `api_routes.py` | Registro de endpoints públicos: `report/<id>`, `/generate`, `/get_filtered_reports`, `/delete_report/<id>`, catálogos complementarios. |
| **Documentación** | `help.md` | Notas internas de uso. |

---

## 🔁 2. Flujo General de un Informe

1. **Selección de contexto**  
   - El usuario elige finca/lote/cultivo y análisis base desde la UI (`listar_reportes`, `solicitar_informe.j2`).  
   - Los datos alimentan la API `/api/foliage/report/generate` con `lot_id`, `common_analysis_id`, `objective_id`, `title` y opcionales como `minimum_law_analyses`.

2. **Generación (`RecommendationGenerator.post`)**  
   - Valida JWT y roles (`administrator`, `reseller`, `org_admin`, `org_editor`).  
   - Obtiene los análisis comunes/foliares/objetivos asociados (`controller.py:591-868`).  
   - Calcula nutrientes limitantes mediante `LeyLiebig` y estima coeficientes CV vía `helpers.determinar_coeficientes_variacion`.  
   - Construye recomendaciones automáticas (texto + JSON) y guarda un nuevo `Recommendation` enlazado al lote/cultivo.

3. **Procesamiento avanzado (`helpers.py`)**  
   - `LeafAnalysisResource` y `ObjectiveResource` empaquetan datos en estructuras consistentes.  
   - `NutrientOptimizer` usa `scipy.optimize.linprog` para resolver cuánta cantidad de cada producto aplicar minimizando costo y respetando aportes nutrimentales (`helpers.py:130-331`).  
   - `contribuciones_de_producto` / `precios_de_producto` consultan `ProductContribution` y `ProductPrice` desde `foliage` para alimentar el optimizador.  
   - `calcular_cv_nutriente` y `determinar_coeficientes_variacion` generan estadísticas del lote basadas en históricos.

4. **Visualización (`ReportView.get`)**  
   - Ensambla la respuesta JSON consolidada: datos generales, comparaciones óptimas, gráfico foliar (normaliza claves a símbolos N/P/K, etc.), histórico del lote y recomendaciones (`controller.py:45-448`).  
   - Construye `foliarChartData` y `historicalData` listos para graficarse en la UI.

5. **Consumo web (`web_routes.py`)**  
   - `/listar_reportes/` renderiza tablas filtrables (por finca/lote) con datos precargados y control lateral de filtros.  
   - `/vista_reporte/<id>` transforma el JSON de `ReportView` en páginas ricas: gráficos, tarjetas de nutrientes limitantes, recomendaciones de texto y tablas históricas.  
   - Se calcula `trends` sobre el histórico para mostrar variaciones porcentuales y mensuales (`web_routes.py:64-151`).

---

## 🧠 3. Algoritmos Clave

| Algoritmo | Archivo | Descripción |
| --- | --- | --- |
| **Ley de Liebig (`LeyLiebig`)** | `helpers.py:29-192` | Determina el nutriente limitante evaluando porcentajes de suficiencia y aplica correcciones `p/i/r`. |
| **Optimizador de nutrientes (`NutrientOptimizer`)** | `helpers.py:195-331` | Aplica programación lineal (SciPy `linprog`) para recomendar combinaciones de productos que cumplan demandas ideales minimizando costo. |
| **Recursos serializados** | `LeafAnalysisResource`, `ObjectiveResource` | Convierte modelos SQLAlchemy en payloads listos para UI/API (niveles ideales actuales). |
| **Coeficientes de variación** | `deteminar_coeficientes_variacion`, `calcular_cv_nutriente` | Derivan métricas históricas por lote y nutriente, usadas para ponderar ajustes. |
| **Catálogos nutrimentales** | `macronutrients/micronutrients` importados desde `foliage.helpers` | Proveen listas base de símbolos, unidades y roles. |

---

## 🗃️ 4. Recursos Consumidos del Módulo Foliage

- `CommonAnalysis`, `SoilAnalysis`, `LeafAnalysis`, `Lot`, `LotCrop`, `Crop`, `Objective`, `Recommendation`, `Nutrient` y tablas puente (`leaf_analysis_nutrients`, `objective_nutrients`).  
- `ProductContribution`, `ProductPrice` y sus relaciones para calcular costos.  
- Permisos reutilizan la misma lógica (`check_resource_access`, `ResellerPackage`) para mantener coherencia de seguridad.

---

## 🌐 5. API Pública

| Método | Ruta | Descripción |
| --- | --- | --- |
| `GET` | `/api/foliage/report/report/<id>` | Devuelve JSON completo de un informe (usado por UI y clientes externos). |
| `POST` | `/api/foliage/report/generate` | Genera/guarda una `Recommendation` construyendo datos analíticos y textos automáticos. |
| `GET` | `/api/foliage/report/get_filtered_reports` | Lista de recomendaciones con filtros por finca, lote, fechas y crop. |
| `DELETE` | `/api/foliage/report/delete_report/<id>` | Marca/borrar un informe existente. |
| `GET` | `/api/foliage/report/get-farms`, `/get-lots`, `/get-objectives`, `/get-objectives-for-crop/<id>` | Catálogos auxiliares acotados a la organización del usuario. |
| `GET` | `/api/foliage/report/analyses` | Retorna análisis `common/soil/leaf` filtrados por finca, lote y rango de fechas (con `leaf_analysis_nutrients`). |

Todas las rutas requieren JWT y utilizan las verificaciones de acceso heredadas de `app.core`.

---

## 🖥️ 6. Interfaces Web

| Ruta | Plantilla | Características |
| --- | --- | --- |
| `/dashboard/foliage_report/listar_reportes/` | `listar_reportes.j2` | Tabla resumida de recomendaciones con filtros `farm_id/lot_id`, muestra cantidad total y link al detalle. |
| `/dashboard/foliage_report/vista_reporte/<id>` | `view_report.j2` / `ver_reporte.j2` | Visualiza gráficos foliares, tablas de nutrientes, históricos, recomendación textual y estado del nutriente limitante. |
| `/dashboard/foliage_report/solicitar_informe*.j2` | Formularios | Paso a paso para capturar parámetros del nuevo informe, seleccionar análisis base y objetivos. |
| Templates `ver_reporte2.j2` y `view_report copy.j2` | Variantes experimentales con comparativas adicionales y rediseños. |

Todas comparten `get_dashboard_menu()` y se apoyan en `data_menu` para navegabilidad consistente con el resto del sistema.

---

## 📊 7. Datos derivativos mostrados en la UI

- **Foliar Chart**: construye barras `actual/min/max` para N, P, K, Ca, Mg, S, Fe, Mn, Zn, Cu, B, Mo, Si (`controller.py:71-140`).  
- **HistoricalData**: `ReportView._get_historical_data` obtiene los últimos análisis del mismo lote para graficar tendencia y calcular variaciones porcentuales/mes a mes (`web_routes.py:100-170`).  
- **Limiting nutrient**: se determina cruzando `limiting_nutrient_id` con niveles reales y rangos óptimos para mostrar si la limitante viene de suelo o foliar.  
- **Automatic recommendations**: JSON/string generado por el optimizador y enriquecido con `minimum_law_analyses` (Ley de Liebig) para justificar cada acción propuesta.

---

## 🔐 8. Seguridad y Permisos

- Todos los MethodView usan `@jwt_required()`.  
- `check_permission` valida roles específicos en cada operación (`controller.py:452-520`, `591-650`).  
- Para listados, se filtran recursos a los que el usuario tiene acceso mediante `ResellerPackage` o relaciones de organización.  
- `DeleteRecommendationView` exige que el recurso pertenezca a una organización visible antes de eliminarlo (`controller.py:926-973`).

---

## 🔧 9. Configuración y Dependencias

- **SciPy (`linprog`)**: requerido para `NutrientOptimizer`; debe estar instalado en el entorno.  
- **Decimal**: se usa ampliamente para evitar errores de redondeo y manejar unidades (kg/ha, g/ha) con precisión.  
- **Flask cache/logger**: se consultan `current_app` y `db.session` para logging y consultas intensivas.  
- **`help.md`**: contiene instrucciones adicionales para usuarios analistas (p.ej. cómo interpretar reportes y preparar datos).

---

## 🧾 10. Créditos

**Desarrollado por:** [Johnny De Castro](https://jdcastro.co/)  
**Framework:** Flask + SQLAlchemy + Tailwind + SciPy  
**Integración:** Redis · MariaDB · Docker · Nginx · Certbot  
**Licencia:** Propietaria – Uso interno TecnoAgro

---

## 11. Consideraciones pendientes

- El optimizador corre dentro del proceso Flask; cargas pesadas podrían bloquear workers. Se recomienda moverlo a un worker asíncrono si el volumen crece.  
- Falta paginación/búsqueda avanzada en `/get_filtered_reports`; hoy devuelve todas las recomendaciones accesibles.  
- `helpers.py` mezcla cálculos científicos con acceso a base de datos; sería deseable separar servicios puros de IO.  
- Existen plantillas duplicadas (`ver_reporte`, `ver_reporte2`, `view_report copy`) que deberían consolidarse.  
- No hay pruebas automatizadas para los algoritmos de Liebig/linprog, lo que dificulta validar cambios numéricos.

---

## 12. Próximos pasos sugeridos

1. Externalizar `NutrientOptimizer` y generación de reportes a una cola (Celery/RQ) con seguimiento de progreso.  
2. Unificar plantillas de reporte en un solo layout responsivo y documentar los componentes Vue/Alpine si se agregan.  
3. Añadir paginación, búsqueda y exportación PDF/CSV en `/listar_reportes` para compartir fácilmente con productores.  
4. Documentar esquemas JSON (OpenAPI o Marshmallow) para `/generate` y `/report/<id>` a fin de habilitar integraciones externas.  
5. Agregar pruebas unitarias para `LeyLiebig`, `NutrientOptimizer`, `calcular_cv_nutriente` y los endpoints críticos.
