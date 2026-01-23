# 🍃 Foliage – Gestión Agronómica Integral

Módulo responsable de **mapear las entidades agronómicas base** de TecnoAgro (fincas, lotes, cultivos) y todos los registros asociados a los programas foliares: análisis comunes, foliares y de suelo, objetivos nutrimentales, aplicaciones, recomendaciones y productos comerciales. Expone CRUDs autenticados (JWT + roles), vistas administrativas en Tailwind y utilidades CSV que alimentan a módulos como **Agrovista** (para nutrimentos objetivo) y **Foliage Report** (para recomendaciones avanzadas).

---

## 🧩 1. Estructura General del Módulo

| Componente | Ubicación | Descripción |
| --- | --- | --- |
| **Blueprint web** | `app/modules/foliage/__init__.py` (`foliage`) | Renderiza dashboards bajo `/dashboard/foliage/*`. |
| **Blueprint API** | `app/modules/foliage/__init__.py` (`foliage_api`) | REST JSON en `/api/foliage/*` con MethodViews protegidas. |
| **Controlador** | `controller.py` | Clase por recurso (`FarmView`, `LotView`, `CropView`, `CommonAnalysisView`, `LeafAnalysisView`, etc.) con permisos y validaciones. |
| **CSV helpers** | `csv_controller.py`, `crop_csv_helper.py` | Importación/exportación CSV para cultivos y catálogos. |
| **Helpers** | `helpers.py` | Sembrado inicial de nutrientes (macro/micro) y categorías. |
| **Modelos** | `models.py` | Más de 15 tablas relacionando fincas → lotes → cultivos → análisis → recomendaciones. |
| **Esquemas** | `schemas.py` | Validaciones Marshmallow (p.ej. `NutrientValueSchema`). |
| **Templates** | `templates/*.j2` | UI de administración (fincas, lotes, cultivos, nutrientes, objetivos, análisis, productos, precios). |
| **Rutas web** | `web_routes.py` | Orquesta vistas, filtros, combos dependientes y datos previos. |
| **Rutas API** | `api_routes.py` | Registra endpoints CRUD + utilidades CSV bajo un mismo módulo. |

---

## 🧭 2. Flujo de Datos y Funcionalidad Principal

1. **Catálogos base**
   - `FarmView`, `LotView`, `CropView`, `NutrientView` gestionan las entidades matrices.
   - Validan duplicados por organización (`org_id`) y controlan soft delete a través de `active` cuando aplica.
   - Los listados filtran por rol (`RoleEnum.ADMINISTRATOR` vs `RESELLER`) usando `ResellerPackage` (`controller.py:62-210`).

2. **Asociaciones Lote/Cultivo**
   - `LotCropView` registra los ciclos productivos por lote (`start_date`/`end_date`) permitiendo conocer el cultivo vigente (`models.py:149-175`).

3. **Análisis agronómicos**
   - `CommonAnalysisView`, `SoilAnalysisView`, `LeafAnalysisView` guardan métricas generales, de suelo y foliares respectivamente. Cada análisis se vincula a un lote y concentra estadísticas como proteína, energía y aforos (`models.py:177-241`).
   - Las mediciones foliares se almacenan en tablas puente (`leaf_analysis_nutrients`) con valores por nutriente y timestamps (`models.py:13-38`).

4. **Programación nutrimental**
   - `ObjectiveView` define metas por cultivo (`objective_nutrients` guarda `target_value`), reutilizadas por Agrovista para objetivos secundarios.
   - `NutrientApplicationView` almacena aplicaciones reales con detalle de nutrientes (`nutrient_application_nutrients`).
   - `ProductionView` y `ProductView/ProductContributionView/ProductPriceView` modelan rendimientos, productos comerciales y sus aportes/costos (`models.py:414-516`).

5. **Recomendaciones**
   - `Recommendation` guarda conclusiones automáticas/manuales, comparaciones contra niveles óptimos y JSON embebidos con análisis (`models.py:315-362`). Este registro es consumido por `foliage_report` para construir dashboards detallados.

6. **Permisos y auditoría**
   - Todos los MethodView usan `@jwt_required()` y decoradores `check_permission` / `check_resource_access` para validar rol, pertenencia y ownership antes de cada operación.
   - Las respuestas JSON usan un `CustomJSONEncoder` propio para serializar `date/datetime` (`controller.py:20-33`).

---

## 📄 3. Modelado Relacional

| Tabla | Campos clave | Relaciones destacadas |
| --- | --- | --- |
| `farms`, `lots`, `crops` | `org_id`, `farm_id`, `area`, `name` | `Farm.lots`, `Lot.farm`, `LotCrop` (historia cultivo). |
| `common_analyses` | `lot_id`, métricas (proteína, energía, yield_estimate) | 1-1 con `SoilAnalysis` y `LeafAnalysis`. |
| `leaf_analysis_nutrients`, `objective_nutrients`, `nutrient_application_nutrients`, `product_contribution_nutrients` | Tablas puente | Guardan valores por nutriente con timestamp. |
| `recommendations` | `lot_id`, `crop_id`, `limiting_nutrient_id`, JSON embebidos | Vincula organización vía `lot.farm.organization`. |
| `products`, `product_contributions`, `product_prices` | Catálogo de insumos y sus aportes económicos/nutrimentales | Se cruzan en reportes de optimización. |

Los modelos incluyen propiedades convenientes (`farm_name`, `organization`, `lot_name`) y `__repr__` descriptivos para facilitar depuración.

---

## 🌐 4. API REST (Resumen)

`api_routes.py` registra un `MethodView` por recurso. Todos aceptan:

| Método | Ruta | Descripción |
| --- | --- | --- |
| `GET/POST/PUT/DELETE` | `/api/foliage/farms`, `/lots`, `/crops`, `/nutrients`, `/lots_crops`, `/objectives`, `/products`, `/products_contributions`, `/product_prices`, `/common_analyses`, `/leaf_analyses`, `/soil_analyses`, `/nutrient_applications`, `/production` | CRUD completos con filtros (`?filter_value=`/`?search=`) y validación de roles. |
| `POST` | `/api/foliage/crops/csv/import` | Importa cultivos desde CSV (usa `CropCsvImporter`). |
| `POST` | `/api/foliage/csv/upload` | Devuelve el contenido parseado de un CSV genérico. |
| `GET` | `/api/foliage/csv/download?resource=farms|crops|lots` | Exporta recursos simples a CSV generado al vuelo. |

Las respuestas usan `json.dumps(..., ensure_ascii=False, indent=4)` para mantener legibles los acentos y favorecer inspecciones manuales.

---

## 🖥️ 5. Vistas Web y UX

`web_routes.py` ofrece dashboards en `/dashboard/foliage/*` con los siguientes patrones:

- **Contexto compartido**: `get_dashboard_menu()` añade navegación “Home/Profile/Logout”; todas las vistas renderizan con `dashboard=True`.
- **Filtros dinámicos**: vistas como `amd_farms`, `amd_lots`, `amd_crops`, `nutrientes` reciben `filter_value`, `search` y construyen combos usando `get_clients_for_user` para mostrar solo las organizaciones accesibles.
- **Templates especializados**: cada entidad tiene su `*.j2` (p.ej. `lots.j2`, `common_analyses.j2`, `product_contributions.j2`) con tablas editables, formularios modales y componentes Tailwind reutilizados.
- **Reuso de lógicas**: las rutas web invocan directamente los métodos privados del `Controller` (`_get_farm_list`, `_get_lot_list`, etc.) para evitar replicar consultas y asegurar que web/API compartan reglas de negocio.

---

## 🧰 6. Helpers, CSV y Semillas

- `helpers.py` define listas `macronutrients` y `micronutrients` con descripción, símbolo, unidad y categoría (`NutrientCategory`). La función `initialize_nutrients()` inserta datos base cuando la tabla está vacía.
- `crop_csv_helper.py` extiende `CsvHandler` (core helper) para interpretar filas `name` y ejecutar UPSERTs sobre `Crop`.
- `csv_controller.py` brinda un endpoint `POST /api/foliage/crops/csv/import` que persiste masivamente cultivos y responde con conteo de filas insertadas/actualizadas.

---

## 🔐 7. Seguridad y Permisos

- **JWT obligatorio**: cada `MethodView` incluye `decorators = [jwt_required()]`.
- **Roles**: `check_permission(required_roles=[...])` restringe POST/PUT/DELETE a `administrator` y `reseller` según corresponda.
- **Ownership**: `check_permission(resource_owner_check=True)` y `check_resource_access` garantizan que un reseller solo vea/modifique registros asociados a sus organizaciones (`controller.py:104-141`, `controller.py:262-311`).
- **Validaciones**: se levantan `BadRequest`, `Forbidden`, `Conflict`, `NotFound` y `Unauthorized` desde `werkzeug.exceptions` para comunicar fallas específicas.

---

## 🔄 8. Integraciones Internas

- **Agrovista** consume endpoints como `/api/foliage/common_analyses`, `/leaf_analyses`, `/secondary-objectives` (derivados de `ObjectiveView`) para completar formularios nutrimentales.
- **Foliage Report** reutiliza los modelos (`Recommendation`, `CommonAnalysis`, `LeafAnalysis`, `Objective`, `Nutrient`, etc.) para generar dashboards avanzados, y comparte tablas puente (`leaf_analysis_nutrients`, `objective_nutrients`).
- **Media** se integra vía iframes dentro de las vistas de Agrovista, pero la metadata nutrimental proviene directamente de este módulo.

---

## 📝 9. Templates Destacados

| Template | Uso |
| --- | --- |
| `nutrients.j2`, `farms.j2`, `lots.j2`, `crops.j2` | Catálogos base con tablas filtrables. |
| `common_analyses.j2`, `leaf_analyses.j2`, `soil_analyses.j2` | Captura de análisis con formularios dependientes y tablas de nutrientes. |
| `objectives.j2`, `nutrient_applications.j2`, `product_contributions.j2`, `product_prices.j2` | Gestión de metas nutrimentales, aplicaciones y costos. |
| `productions.j2` | Registro de rendimientos proyectados vs reales. |

Cada plantilla sigue el layout `base.j2`, utiliza componentes Tailwind y se apoya en `data_menu` para la navegación.

---

## 🧪 10. Validaciones y Esquemas

`models.py` incluye `NutrientValueSchema` y validadores Marshmallow (`@validates`) para asegurar rangos numéricos y presencia de campos. Aunque `schemas.py` es ligero, la intención es consolidar la lógica de validación en un solo lugar, evitando duplicidades en controladores y tareas de importación.

---

## 🧾 11. Créditos

**Desarrollado por:** [Johnny De Castro](https://jdcastro.co/)  
**Framework:** Flask + SQLAlchemy + Tailwind  
**Integración:** Redis · MariaDB · Docker · Nginx · Certbot  
**Licencia:** Propietaria – Uso interno TecnoAgro

---

## 12. Consideraciones pendientes

- Falta paginar el endpoint `/api/foliage/*` para colecciones grandes; actualmente devuelve todos los registros.
- `schemas.py` y las validaciones Marshmallow están mínimas; sería ideal formalizar contratos JSON para los múltiples formularios.
- La eliminación de registros se realiza con soft-delete condicional (`active`), pero no existe limpieza automática de relaciones dependientes.
- No hay tareas background para operaciones costosas (p.ej. cálculos sobre `leaf_analysis_nutrients`), por lo que importaciones masivas podrían bloquear la app.
- La carga CSV solo cubre cultivos; faltan herramientas similares para nutrientes, lotes o aplicaciones.

---

## 13. Próximos pasos sugeridos

1. Agregar paginación/ordenamiento server-side y filtros combinables en toda la API (`?page=&per_page=&org_id=`).
2. Consolidar validaciones en `schemas.py` (Marshmallow o Pydantic) y usarlas tanto en API como en web forms.
3. Implementar tareas asíncronas (Celery/RQ) para importadores CSV grandes y cálculos derivados (promedios históricos, KPIs).
4. Extender la CLI de semillas (`initialize_nutrients`) para poblar datos demo de fincas/lotes/cultivos y facilitar QA.
5. Documentar flujos de negocio (diagramas) y añadir pruebas unitarias/integra-cionales para cada `MethodView`.
