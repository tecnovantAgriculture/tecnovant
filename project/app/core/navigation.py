"""Navigation and breadcrumb utilities for the application.

This module provides breadcrumb generation and navigation hierarchy management.
It supports both automatic generation from request context and manual configuration
per route.
"""

from flask import request, url_for

# Breadcrumb hierarchy mapping: endpoint -> list of breadcrumb items
# Each item is a dict with 'name' and optional 'url' (endpoint name)
# The last item (current page) should have url=None
BREADCRUMB_HIERARCHY = {
    # Core module
    "core.dashboard": [{"name": "Inicio", "url": None}],
    "core.amd_clients": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Fincas y lotes", "url": None},
        {"name": "Clientes", "url": None},
    ],
    "core.amd_users": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Administración", "url": None},
        {"name": "Usuarios", "url": None},
    ],
    "core.profile": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Mi Perfil", "url": None},
    ],
    # Foliage module - Fincas y lotes
    "foliage.amd_farms": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Fincas y lotes", "url": None},
        {"name": "Fincas", "url": None},
    ],
    "foliage.amd_lots": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Fincas y lotes", "url": None},
        {"name": "Lotes", "url": None},
    ],
    "foliage.amd_lot_crops": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Fincas y lotes", "url": None},
        {"name": "Lote / Cultivo", "url": None},
    ],
    "foliage.amd_crops": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Fincas y lotes", "url": None},
        {"name": "Cultivos", "url": None},
    ],
    # Foliage module - Formularios de análisis
    "foliage.amd_common_analyses": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Formularios de análisis", "url": None},
        {"name": "Análisis foliar (físico)", "url": None},
    ],
    "foliage.amd_leaf_analyses": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Formularios de análisis", "url": None},
        {"name": "Foliares digitales", "url": None},
    ],
    "foliage.amd_soil_analyses": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Formularios de análisis", "url": None},
        {"name": "Análisis de suelo", "url": None},
    ],
    "foliage.amd_nutrient_applications": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Formularios de análisis", "url": None},
        {"name": "Aplicaciones de nutrientes", "url": None},
    ],
    "foliage.amd_productions": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Formularios de análisis", "url": None},
        {"name": "Producción", "url": None},
    ],
    # Foliage module - Configuración
    "foliage.nutrientes": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Configuración", "url": None},
        {"name": "Nutrientes", "url": None},
    ],
    "foliage.amd_objectives": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Configuración", "url": None},
        {"name": "Objetivos", "url": None},
    ],
    "foliage.amd_products": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Configuración", "url": None},
        {"name": "Productos", "url": None},
    ],
    "foliage.amd_product_contributions": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Configuración", "url": None},
        {"name": "Contribuciones de productos", "url": None},
    ],
    "foliage.amd_product_prices": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Configuración", "url": None},
        {"name": "Precios de productos", "url": None},
    ],
    # Agrovista module
    "agrovista.hello": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Análisis de imagen", "url": None},
        {"name": "NDVI / VARI Tool", "url": None},
    ],
    "agrovista.secondary_objectives": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Análisis de imagen", "url": None},
        {"name": "Objetivos secundarios", "url": None},
    ],
    "agrovista.comparison_config": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Análisis de imagen", "url": None},
        {"name": "Comparación nutricional", "url": None},
    ],
    # Media module
    "media.library": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Análisis de imagen", "url": None},
        {"name": "Ortofotos y medios", "url": None},
    ],
    "media.upload_local": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Análisis de imagen", "url": None},
        {"name": "Importar local", "url": None},
    ],
    "media.upload_s3": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Análisis de imagen", "url": None},
        {"name": "Importar desde S3", "url": None},
    ],
    "media.element": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Análisis de imagen", "url": None},
        {"name": "Ortofotos y medios", "url": "media.library"},
        {"name": "Detalle", "url": None},
    ],
    # Foliage Report module
    "foliage_report.listar_reportes": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Reportes", "url": None},
        {"name": "Recomendaciones", "url": None},
    ],
    "foliage_report.generar_informe": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Reportes", "url": None},
        {"name": "Generar reporte", "url": None},
    ],
    "foliage_report.vista_reporte": [
        {"name": "Inicio", "url": "core.dashboard"},
        {"name": "Reportes", "url": None},
        {"name": "Recomendaciones", "url": "foliage_report.listar_reportes"},
        {"name": "Detalle", "url": None},
    ],
}


def get_breadcrumbs(breadcrumbs_override=None):
    """Generate breadcrumbs for the current request.

    This function attempts to generate breadcrumbs in the following order:
    1. Use breadcrumbs_override if provided (manual override from route)
    2. Look up breadcrumbs from BREADCRUMB_HIERARCHY using request.endpoint
    3. Return empty list as fallback

    Args:
        breadcrumbs_override (list, optional): Manual breadcrumb list to use.
            Each item should be a dict with 'name' and optional 'url' keys.

    Returns:
        list: List of breadcrumb items, each with 'name' and optional 'url'.
    """
    # Use manual override if provided
    if breadcrumbs_override:
        return breadcrumbs_override

    # Look up from hierarchy
    endpoint = request.endpoint
    if endpoint and endpoint in BREADCRUMB_HIERARCHY:
        return BREADCRUMB_HIERARCHY[endpoint]

    # Fallback: empty list (breadcrumbs won't render)
    return []


def register_breadcrumbs_context(app):
    """Register breadcrumbs as a template context processor.

    This makes the get_breadcrumbs function available in all templates
    without explicitly passing it in the context.

    Args:
        app: Flask application instance
    """

    @app.context_processor
    def inject_breadcrumbs():
        return {"get_breadcrumbs": get_breadcrumbs}
