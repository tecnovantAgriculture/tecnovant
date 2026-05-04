# CodeViz Research Context

> **Note**: This file contains research context from CodeViz. Most recent contexts are at the bottom.

---

## Research Query 

crea un mapa visual de la arquitectura del proyecto

*Session: 69ced5f8bb30f5759f19c0e87e8395fc | Generated: 3/7/2025, 11:19:39 a. m.*

### Analysis Summary

# Arquitectura del Proyecto

Este proyecto sigue una estructura modular, con una clara separación de responsabilidades entre los componentes principales. La aplicación se organiza en torno a un núcleo (`app/core`), módulos específicos (`app/modules`), y recursos estáticos (`app/static`) y plantillas (`app/templates`).

## Componentes Principales

### app/core
El directorio `app/core` contiene la lógica central de la aplicación. Es responsable de la gestión de usuarios, autenticación, rutas API y web, y la definición de modelos y esquemas de datos.

*   **Propósito:** Proporcionar la funcionalidad base y los servicios esenciales para toda la aplicación.
*   **Partes Internas Clave:**
    *   `controller.py`: Maneja la lógica de negocio principal y la interacción con los modelos.
    *   `models.py`: Define los modelos de datos de la aplicación, probablemente utilizando un ORM.
    *   `schemas.py`: Define los esquemas de datos para la validación y serialización, comúnmente utilizados con APIs.
    *   `api_routes.py`: Define las rutas para la API RESTful de la aplicación.
    *   `web_routes.py`: Define las rutas para las páginas web renderizadas.
    *   `templates/dashboard/`: Contiene plantillas Jinja2 para el panel de control, incluyendo vistas para usuarios, clientes, perfiles, etc.
    *   `templates/`: Contiene plantillas generales para la aplicación, como `login.j2`, `forgot_password.j2`, `home.j2`, etc.
*   **Relaciones Externas:** Interactúa con los módulos específicos para extender la funcionalidad y con las plantillas para renderizar la interfaz de usuario.

### app/helpers
El directorio `app/helpers` contiene funciones y utilidades de propósito general que son utilizadas por varios componentes de la aplicación.

*   **Propósito:** Proporcionar un conjunto de herramientas reutilizables para tareas comunes.
*   **Partes Internas Clave:**
    *   `crud_pattern.py`: Probablemente implementa patrones para operaciones CRUD (Crear, Leer, Actualizar, Eliminar).
    *   `csv_handler.py`: Maneja la lectura y escritura de archivos CSV.
    *   `error_handler.py`: Gestiona el manejo de errores en la aplicación.
    *   `helpers_functions.py`: Contiene funciones de utilidad diversas.
    *   `mail.py`: Funciones para el envío de correos electrónicos.
    *   `route_lister.py`: Posiblemente para listar o gestionar rutas de la aplicación.
    *   `validators.py`: Contiene funciones para la validación de datos.
*   **Relaciones Externas:** Utilizado por `app/core` y los módulos en `app/modules`.

### app/modules
El directorio `app/modules` contiene módulos específicos que extienden la funcionalidad de la aplicación. Cada subdirectorio dentro de `modules` representa un módulo independiente con su propia lógica, modelos, esquemas y rutas.

*   **Propósito:** Encapsular funcionalidades específicas y permitir la modularidad y escalabilidad de la aplicación.
*   **Partes Internas Clave:**
    *   **foliage:**
        *   **Propósito:** Gestionar datos relacionados con el follaje, como análisis de hojas, cultivos, fincas, lotes, etc.
        *   **Partes Internas Clave:**
            *   `api_routes.py`: Rutas API específicas para el módulo de follaje.
            *   `controller.py`: Lógica de negocio para el módulo de follaje.
            *   `models.py`: Modelos de datos para el módulo de follaje.
            *   `schemas.py`: Esquemas de datos para el módulo de follaje.
            *   `templates/`: Plantillas Jinja2 para las vistas del módulo de follaje.
            *   `csv_controller.py`, `crop_csv_helper.py`: Probablemente para la importación/exportación de datos relacionados con cultivos en formato CSV.
        *   **Relaciones Externas:** Interactúa con `app/core` para la autenticación y servicios base, y con `app/helpers` para utilidades.
    *   **foliage_report:**
        *   **Propósito:** Generar y gestionar informes relacionados con el follaje.
        *   **Partes Internas Clave:**
            *   `api_routes.py`: Rutas API específicas para los informes de follaje.
            *   `controller.py`: Lógica de negocio para la generación de informes.
            *   `templates/`: Plantillas Jinja2 para la visualización y solicitud de informes.
        *   **Relaciones Externas:** Depende del módulo `foliage` para los datos y de `app/core` para la infraestructura.

### app/static
El directorio `app/static` contiene todos los archivos estáticos de la aplicación, como CSS, JavaScript e imágenes.

*   **Propósito:** Servir recursos estáticos directamente al navegador del cliente.
*   **Partes Internas Clave:**
    *   `assets/css/`: Archivos CSS para el estilo de la aplicación.
    *   `assets/img/`: Imágenes utilizadas en la aplicación.
    *   `assets/js/`: Archivos JavaScript para la interactividad del lado del cliente. Incluye librerías como `mermaid.min.js` para la visualización de diagramas.
*   **Relaciones Externas:** Consumido directamente por los navegadores web que acceden a la aplicación.

### app/templates
El directorio `app/templates` contiene las plantillas Jinja2 utilizadas para renderizar las páginas web.

*   **Propósito:** Definir la estructura y el contenido de la interfaz de usuario.
*   **Partes Internas Clave:**
    *   `default/layouts/`: Plantillas de diseño base para diferentes secciones de la aplicación (e.g., `crud_base.j2`, `access_form.j2`).
    *   `default/macros/`: Macros Jinja2 reutilizables para elementos de UI (e.g., `_button.j2`, `_forms.j2`).
    *   `default/partials/`: Pequeños fragmentos de plantillas reutilizables (e.g., `footer.j2`, `header.j2`, `navigation.j2`).
    *   `default/settings/`: Plantillas relacionadas con la configuración de la UI, como iconos.
    *   `base.j2`: La plantilla base de la aplicación de la que heredan otras plantillas.
*   **Relaciones Externas:** Utilizadas por los controladores en `app/core` y `app/modules` para generar las respuestas HTML.

## Otros Componentes Clave

*   **migrations:** Contiene scripts de migración de base de datos, probablemente utilizando Alembic.
*   **run.py:** El punto de entrada principal de la aplicación.
*   **config.py:** Archivo de configuración de la aplicación.
*   **extensions.py:** Probablemente para inicializar extensiones o plugins de la aplicación.

## Flujo General de la Aplicación

1.  Un usuario realiza una solicitud HTTP.
2.  La solicitud es recibida por el servidor web y enrutada a través de `api_routes.py` o `web_routes.py` en `app/core` o en los módulos específicos (`app/modules/foliage`, `app/modules/foliage_report`).
3.  El controlador correspondiente (`controller.py` en `app/core` o en los módulos) procesa la solicitud.
4.  El controlador interactúa con los modelos (`models.py`) para acceder o modificar datos en la base de datos.
5.  Las funciones de ayuda en `app/helpers` pueden ser utilizadas para tareas comunes como validación, manejo de CSV, envío de correos, etc.
6.  Para las solicitudes web, el controlador renderiza una plantilla Jinja2 desde `app/templates` o desde los directorios `templates` de los módulos.
7.  Los archivos estáticos de `app/static` se sirven directamente al navegador para el CSS, JavaScript e imágenes.
8.  La respuesta (HTML, JSON, etc.) se envía de vuelta al usuario.

Este diseño modular permite una clara separación de preocupaciones, facilitando el desarrollo, mantenimiento y escalabilidad de la aplicación.

### Implementation Steps

1. **Understanding the Overall Project Architecture**
   The project is structured modularly, separating responsibilities among core components. It's organized around a central core, specific modules, static resources, and templates. This design promotes clear separation of concerns, facilitating development, maintenance, and scalability.

2. **Exploring the Core Application Logic (`app/core`)**
   The `app/core` directory houses the application's central logic, managing users, authentication, API and web routes, and defining data models and schemas. It provides foundational functionality and essential services, interacting with specific modules to extend features and with templates for UI rendering. Key internal parts include components for business logic, data models, data schemas, API routes, web routes, and various dashboard and general templates.

3. **Understanding the Utility Functions (`app/helpers`)**
   The `app/helpers` directory contains general-purpose functions and utilities used across various components. Its purpose is to provide reusable tools for common tasks. These helpers are utilized by both the core application and specific modules. Key internal parts include utilities for CRUD operations, CSV handling, error management, email sending, route listing, and data validation.

4. **Delving into Specific Application Modules (`app/modules`)**
   The `app/modules` directory holds specific modules that extend the application's functionality. Each subdirectory within `modules` represents an independent module with its own logic, models, schemas, and routes. This structure encapsulates specific functionalities, enabling modularity and scalability.

5. **Examining the `foliage` Module**
   The `foliage` module within `app/modules` is designed to manage data related to foliage, such as leaf analysis, crops, farms, and lots. It includes its own API routes, business logic, data models, and schemas, along with dedicated templates. It also contains components for CSV import/export of crop-related data. This module interacts with the core for authentication and base services, and with helpers for utilities.

6. **Exploring the `foliage_report` Module**
   The `foliage_report` module, also within `app/modules`, is responsible for generating and managing foliage-related reports. It has its own API routes, business logic for report generation, and templates for viewing and requesting reports. This module depends on the `foliage` module for data and the core for infrastructure.

7. **Understanding Static Resources (`app/static`)**
   The `app/static` directory contains all static files, including CSS, JavaScript, and images. Its purpose is to serve these resources directly to the client's browser. It includes subdirectories for CSS stylesheets, images, and JavaScript files, which may include libraries for diagram visualization.

8. **Working with Application Templates (`app/templates`)**
   The `app/templates` directory contains Jinja2 templates used for rendering web pages. It defines the structure and content of the user interface. It includes base layout templates, reusable Jinja2 macros for UI elements, small reusable template fragments, and templates for UI settings. These templates are used by controllers in the core and modules to generate HTML responses.

9. **Identifying Other Key Application Components**
   Beyond the main directories, other key components include `migrations` for database migration scripts, `run.py` as the main application entry point, `config.py` for application configuration, and `extensions.py` for initializing application extensions or plugins.

10. **Understanding the General Application Flow**
   The application's general flow begins when a user makes an HTTP request, which is routed through API or web routes in the core or specific modules. The corresponding controller processes the request, interacting with models for data access or modification. Helper functions are utilized for common tasks. For web requests, the controller renders a Jinja2 template. Static files are served directly to the browser, and the final response is sent back to the user.


*******************************

# CODE_AGENT_GUIDE

Guía operativa para agentes de código en el proyecto TecnoAgro. Resume la arquitectura, convenciones y flujos necesarios para mantener y extender la aplicación con foco en modularidad, seguridad, rendimiento y escalabilidad.

---

## Panorama General

- **Stack**: Flask 3.1 (factory pattern), SQLAlchemy + Flask-Migrate, JWT cookies (flask-jwt-extended), Jinja2 + Tailwind CSS, Flask-Caching, Redis opcional, Marshmallow para validaciones.
- **Dominios clave**: Núcleo (`app/core`) para autenticación, control de usuarios y utilidades; módulos verticales (`app/modules/*`) para features de negocio (follaje, reportes, agrovista, media, etc.); helpers transversales (`app/helpers`) para CRUD, validaciones, CSV, mailing, logging y listados de rutas.
- **Patrones**: Blueprints (web/api), servicios por módulo, controladores MethodView con JWT y RBAC, soft delete vía bandera `active`, manejo de errores centralizado con logging rotativo, plantillas temáticas (`app/templates/<theme>`).
- **Entrada**: `run.py` instancia la app vía `create_app()`; configuración leída de `.env` validada por `Config.validate_config()`.

---

## Arquitectura y Estructura

- `app/__init__.py`: crea la app, inicializa extensiones (`mail`, `jwt`, `db`, `migrate`, `cache`), registra blueprints dinámicamente (core + `Config.MODULES`), publica `/list_endpoints` y `/info`, configura filtros/contexts de Jinja.
- `app/config.py`: clase `Config` centraliza variables de entorno, mail, JWT, caché, base de datos (SQLite local o motores externos). Valida claves críticas (`SECRET_KEY`, credenciales DB).
- `app/extensions.py`: instancia única de extensiones para evitar import circular.
- `app/core`: dos blueprints (`core`, `core_api`) con rutas web (`web_routes.py`) y REST (`api_routes.py`), controladores RBAC (`controller.py`), modelos de usuarios/organizaciones/roles (`models.py`), esquemas Marshmallow (`schemas.py`), plantillas base del dashboard.
- `app/helpers`: utilidades reutilizables (`crud_pattern.CRUDMixin`, `validators.APIValidator`, `error_handler`, `mail`, `route_lister`, `csv_handler`, etc.).
- `app/modules/<module>`: cada módulo repite patrón `__init__.py` (blueprints web/api), `controller.py` con servicios específicos, `models.py`, `schemas.py`, `helpers.py`, `templates/` con vistas Jinja enfocadas en dashboard.
- `app/templates/default`: layout base, macros y parciales reutilizables (Tailwind, Flowbite).
- `migrations/`: scripts Alembic gestionados vía Flask-Migrate.
- `Makefile`, `start.sh`: scripts de gestión (ejecución, lint, migrate).
- `requirements*.txt`, `pyproject.toml`, `setup.cfg`: dependencias, herramientas (black/isort/flake8) con line length 88.

---

## 📂 Estructura general del módulo

Cada módulo creado se ubica en:

```
project/app/modules/<nombre_modulo>/
```

Su diseño está orientado a **separar responsabilidades** entre la capa de presentación (UI), la capa de API, la lógica de negocio y el manejo de datos.

---

## 📄 Archivos principales

### 1. `__init__.py`

- **Responsabilidad**: inicializa el módulo.
- **Función**:

  - *Declara los *blueprints* de Flask.
  - Si hay interfaz web, se crea un blueprint para rutas web (`/<nombre_modulo>`).
  - Si hay API, se crea un blueprint para rutas de API (`/api/<nombre_modulo>`).
  - Importa los archivos de rutas correspondientes (`web_routes`, `api_routes`).

### 2. `api_routes.py`

- **Responsabilidad**: definir los endpoints de API.
- **Función**:

  - Manejar peticiones HTTP tipo REST (JSON).
  - Exponer endpoints públicos/privados para el consumo de datos.
  - No contiene lógica de negocio; solo enruta y entrega respuestas usando los *controllers*.

---

### 3. `web_routes.py`

- **Responsabilidad**: manejar las rutas que devuelven vistas HTML.
- **Función**:

  - Renderizar plantillas (Jinja2) para la interfaz del usuario.
  - Consumir datos ya procesados por la API o los *controllers*.
  - **Nota clave**: aquí solo se consumen los endpoints de api_routes usando vanilla JS.

---

### 4. `templates/<nombre_vista>/`

- **Responsabilidad**: contener las plantillas HTML (Jinja2).
- **Función**:

  - Define la presentación visual de las páginas del módulo.
  - Se alimenta de los datos entregados por `web_routes.py`.

---

### 5.  CRUD y Helpers `controller.py` y `helpers.py`

Patrón de vistas CRUD reutilizable con RBAC y helpers.

- Procura Extender CRUDMixin para heredar JWT, access control y paginación.
- Delegar persistencia en servicios especializados por módulo.
- Validar payloads con APIValidator antes de invocar lógica CRUD.
- Usa check_resource_access para respetar reglas multi-tenant.

#### controller.py

- **Responsabilidad**: lógica de negocio del módulo.
- **Función**:

  - Procesar la información recibida desde API o UI.
  - Coordinar interacciones entre modelos, esquemas y helpers.
  - Es el “cerebro” del módulo.

#### helpers.py

- **Responsabilidad**: concentrar utilidades auxiliares.
- **Función**:

  - Funciones comunes que pueden ser reutilizadas por `controllers`, `routes` o `models`.
  - Ejemplo: formateo de fechas, cálculos, transformaciones de texto.

#### Código de ejemplo

```python
from typing import Any, Dict, List

from flask import Blueprint, Response, request
from flask_caching import Cache

from app.extensions import cache as default_cache, db
from app.helpers.crud_pattern import CRUDMixin
from app.helpers.validators import APIValidator
from app.modules.foliage.models import Farm
from app.modules.foliage.schemas import FarmSchema

foliage_api = Blueprint("foliage_api", __name__, url_prefix="/api/foliage")


class FarmService:
    """Servicios de datos reutilizados por vistas y tareas."""
    schema = FarmSchema()

    def get_all(self):
        return (
            Farm.query.filter_by(active=True)
            .order_by(Farm.name.asc())
            .options(db.joinedload(Farm.organization))
            .all()
        )

    def get_all_paginated(self, page: int, per_page: int):
        return (
            Farm.query.filter_by(active=True)
            .order_by(Farm.name.asc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )

    def get_by_id(self, farm_id: int):
        return Farm.query.filter_by(id=farm_id, active=True).first()

    def create(self, data: Dict[str, Any]) -> Farm:
        farm = Farm(**data)
        db.session.add(farm)
        db.session.commit()
        return farm

    def update(self, farm: Farm, data: Dict[str, Any]) -> Farm:
        for key, value in data.items():
            setattr(farm, key, value)
        db.session.commit()
        return farm

    def soft_delete(self, farm_ids: List[int]) -> int:
        affected = (
            Farm.query.filter(Farm.id.in_(farm_ids))
            .update({"active": False}, synchronize_session=False)
        )
        db.session.commit()
        return affected


class FarmView(CRUDMixin):
    """Exposición de CRUD Farm con control de acceso basado en claims."""
    def __init__(self):
        super().__init__(
            Farm,
            FarmSchema(),
            FarmService(),
            required_roles=["administrator", "reseller"],
        )

    @APIValidator.validate_form(
        name={"validators": [], "required": True},
        org_id=APIValidator.validate_number(min_value=1),
    )
    def post(self) -> Response:
        request.json = request.validated_data
        return super().post()

    def _has_access(self, farm: Farm, claims: Dict[str, Any]) -> bool:
        from app.core.controller import check_resource_access

        return check_resource_access(farm, claims)

    def _serialize_resource(self, farm: Farm) -> Dict[str, Any]:
        return FarmSchema().dump(farm)

    def _delete_resource(self, resource_id: int) -> Response:
        deleted = self.service.soft_delete([resource_id])
        return self._build_success_response(
            f"Deleted {deleted} farm(s)", {"deleted": deleted}
        )


def register_farm_routes(api_blueprint: Blueprint, cache: Cache = default_cache) -> None:
    """Registra rutas API con cabeceras de caché ligeras."""
    view = FarmView.as_view("foliage_farm_view")
    api_blueprint.add_url_rule(
        "/farms/", defaults={"resource_id": None}, view_func=view, methods=["GET"]
    )
    api_blueprint.add_url_rule("/farms/", view_func=view, methods=["POST", "DELETE"])
    api_blueprint.add_url_rule(
        "/farms/<int:resource_id>", view_func=view, methods=["GET", "PUT", "DELETE"]
    )

    @api_blueprint.after_request
    def inject_cache_headers(response: Response) -> Response:
        if request.method == "GET" and response.status_code == 200:
            response.headers.setdefault("Cache-Control", "public, max-age=60")
        return response


register_farm_routes(foliage_api)
```

### 6. Modelos y Datos `model.py`

- **Responsabilidad**: representar las entidades de datos en la base de datos.
- **Función**:
  - Definir modelos ORM (SQLAlchemy).
  - Encargarse de la persistencia y consultas a la base de datos.

Modelo de gestión y verificación SQLAlchemy alineados con RBAC y servicios reutilizables.

- **Recomendaciones**:
  - Enums de roles, permisos y acciones; reaprovechados en JWT y controladores están presentes en `app/core/models.py`.
  - Soft delete via bandera `active`; tablas de asociación para multi-tenancy.
  - Helpers `verify_user_in_organization` y `get_clients_for_user`.

---

### 7. `schemas.py`

- **Responsabilidad**: definir validaciones y serialización de datos.
- **Función**:

  - Transformar objetos Python ↔ JSON (p. ej., con Marshmallow).
  - Asegurar consistencia en entrada y salida de datos.

---

---

## 🚦 Resumen de responsabilidades

- **UI (web\_routes + templates)** → Mostrar y consumir datos.
- **API (api\_routes)** → Exponer servicios JSON.
- **Controller** → Procesar la lógica central.
- **Models** → Conexión y estructura de la base de datos.
- **Schemas** → Validación y serialización de datos.
- **Helpers** → Funciones auxiliares reutilizables.
- ****init**** → Registro de *blueprints* y punto de entrada del módulo.

---

## Vistas, templates y macros Jinja2

- **Lineamientos**: 
  - Uso de Tailwind css, heredan de /app/templates/default/
  - Vanilla JS
  - ejemplo:

```jinja
{# app/modules/foliage/templates/farms.j2: patrón de dashboards modulares #}
{% extends "base.j2" %}
{% from "macros/_forms.j2" import render_input, render_select %}
{% set page_title = "Granjas" %}
{% set data_menu = data_menu or get_dashboard_menu() %}

{% block head_extra %}
  <link rel="preload" href="{{ url_for('static', filename='assets/css/dashboard.css') }}" as="style">
{% endblock %}

{% block content %}
  <section class="space-y-6">
    <header class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-semibold text-slate-900">{{ page_title }}</h1>
        <p class="text-sm text-slate-500">Gestión multiorganización administrada por JWT claims.</p>
      </div>
      <a
        href="{{ url_for('foliage.create_farm') }}"
        class="btn-primary"
        data-testid="create-farm-button"
      >
        Nueva granja
      </a>
    </header>

    <form
      method="get"
      class="bg-white shadow-sm ring-1 ring-slate-200 rounded-md p-4 grid gap-4 md:grid-cols-3"
      data-controller="filters"
    >
      {{ render_select('filter_value', org_dict, request.args.get('filter_value'), 'Organización') }}
      {{ render_input('search', request.args.get('search'), 'Buscar granja', placeholder='Nombre o código') }}
      <button type="submit" class="btn-secondary mt-auto">Aplicar</button>
    </form>

    <div class="bg-white shadow ring-1 ring-slate-200 rounded-lg overflow-hidden">
      <table class="min-w-full divide-y divide-slate-200">
        <thead class="bg-slate-50">
          <tr>
            <th scope="col" class="table-head">Nombre</th>
            <th scope="col" class="table-head">Organización</th>
            <th scope="col" class="table-head text-right">Acciones</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100">
          {% for farm in items %}
            <tr>
              <td class="table-cell">{{ farm.name }}</td>
              <td class="table-cell">{{ org_dict|dict_get(farm.org_id, default='-') }}</td>
              <td class="table-cell text-right space-x-2">
                <a href="{{ url_for('foliage.view_farm', farm_id=farm.id) }}" class="btn-link">Ver</a>
                <button
                  type="button"
                  class="btn-link text-rose-600"
                  data-action="farms#promptDelete"
                  data-farms-id-value="{{ farm.id }}"
                >
                  Eliminar
                </button>
              </td>
            </tr>
          {% else %}
            <tr>
              <td colspan="3" class="py-6 text-center text-slate-400">
                No hay granjas disponibles con los filtros seleccionados.
              </td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </section>
{% endblock %}
```

---

## Recomendaciones y Consideraciones

```python
def recommendations() -> dict[str, tuple[str, ...]]:
    """Guardrails para escalabilidad, seguridad y rendimiento.

    - Falla rápido si faltan variables críticas en Config.validate_config().
    - Usa Flask-Caching para endpoints costosos (estadísticas, CSV, GeoTIFF).
    - Optimiza las consultas a DB, procura el rendimiento de la APP
    - Reutiliza check_permission / check_resource_access en cada MethodView.
    - Stream de payloads grandes con Response(stream_with_context(...)).
    - Sanitiza uploads con helpers.csv_handler y validators antes de persistir.
    - Log estructurado via setup_logging; integra con observabilidad externa.
    - Documenta nuevas rutas para que RouteLister exponga metadata correcta.
    - Esquemas Marshmallow con type hints y docstrings estilo OpenAPI.
    - Cobertura de pruebas: unit + integration + security + performance.
    """
    return {
        "scalabilidad": (
            "Aplica paginación del CRUDMixin para listados grandes.",
            "Carga relacionadas con selectinload/joinedload para evitar N+1.",
            "Externaliza tareas intensivas a jobs asíncronos si exceden SLAs.",
        ),
        "seguridad": (
            "JWT cookies seguras + CSRF; nunca desactivar en producción.",
            "Valida siempre payloads con Marshmallow o APIValidator.",
            "Mantén scope de organización en servicios antes de mutar datos.",
        ),
        "rendimiento": (
            "Cachea catálogos (nutrients, objectives) con cache.memoize.",
            "Pre-carga assets críticos en templates (Tailwind, Flowbite).",
            "Activa SQLALCHEMY_ECHO solo para debugging temporal.",
        ),
        "operaciones": (
            "Publica migraciones con Flask-Migrate; evita bifurcar heads.",
            "Versiona plantillas y assets estáticos junto a cada módulo.",
            "Expose feature flags via Config o Organization.settings.",
        ),
    }
```

---

## Flujo de Trabajo Recomendado

### Preparación

1. Analiza requisitos y define si se necesita nuevo módulo/blueprint.
2. Diseña esquema de base de datos y migraciones (Flask-Migrate).
3. Planea rutas y vistas, considerando rendimiento (caché, streaming).
4. Define plantillas Jinja y JS complementario si aplica.
5. Asegura cumplimiento de roles/permisos desde el diseño.

### Desarrollo

1. Usa estructura modular (routes.py, model.py, functions/service.py, `__init__`.py).
2. Implementa autenticación (JWT) y manejo de errores consistente.
3. Optimiza performance (consultas con `selectinload`, cache, streaming).
4. Documenta rutas para `RouteLister`; actualiza guías si cambian flujos.

### Testing

- **Unit**: Modelos, servicios, validadores.
- **Integración**: Endpoints REST, flujos JWT, RBAC.
- **Seguridad**: Validaciones de entrada, control de acceso, CSRF.
- **Performance**: Endpoints intensivos, manejo de archivos grandes.

---

## Lineamientos de Código

- Sigue PEP 8, PEP 257, SOLID, DRY.
- Usa Blueprints para modularidad; separa controladores/servicios.
- Sanitiza entradas contra SQLi, XSS, CSRF (JWT cookies + CSRF tokens).
- Documenta métodos/rutas con docstrings claros (`RouteLister`).
- Emplea type hints, docstrings y Marshmallow actualizado.
- Logging estructurado con RotatingFileHandler (`errors.log`).
- Configura Tailwind/Flowbite a través de macros/settings en `templates/default`.

---

## Observabilidad y Errores

- `app/helpers/error_handler.py` captura excepciones globales, loggea contexto (método, headers, body, traceback).
- Respuestas JSON para `/api/*`, HTML para web; fallback textual si falla plantilla.
- Rotating logs (máx 1 MB, 10 backups). Ajusta rutas según despliegue.

---

## Assets y Tema

- `Config.THEME` selecciona carpeta de templates (`app/templates/<theme>`).
- Plantillas base (`base.j2`) usan macros/partials; mantén UI consistente (Tailwind).
- Assets estáticos en `app/static/assets`; preferir bundling ligero y preloads.

---
