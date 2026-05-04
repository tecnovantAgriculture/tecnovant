"""📃 Rutas web del módulo Agrovista (procesamiento NDVI)

CONVENCIÓN DE DECORADORES DE AUTENTICACIÓN:
- @login_required: Para rutas web estándar (redirige a login si no autenticado)
- @jwt_required(): Para rutas que requieren validación JWT explícita
- @api_login_required: Para rutas API que devuelven JSON 401 (no redirección)

Este módulo usa exclusivamente @login_required para todas sus rutas web.
"""

from flask import render_template, url_for
from flask_jwt_extended import get_jwt, get_jwt_identity

from app.core.controller import login_required
from app.core.models import get_clients_for_user
from app.helpers.dashboard_helpers import get_dashboard_menu
from app.modules.foliage.models import Farm

from . import agrovista as web
from .models import NDVIImage

@web.route("/", methods=["GET"])
@login_required
def hello():
    user_id = get_jwt_identity()
    organizations = get_clients_for_user(user_id) if user_id else []
    org = organizations[0] if organizations else None
    farm = None
    if org:
        farm = (
            Farm.query.filter(Farm.org_id == org.id)
            .order_by(Farm.created_at.desc())
            .first()
        )
    context = {
        "dashboard": True,
        "title": "NDVI Tool",
        "description": "Herramienta para el analisis NDVI.",
        "author": "Johnny De Castro",
        "site_title": "Análisis de Imagenes",
        "data_menu": get_dashboard_menu(),
        "entity_name": "Reportes",
        "entity_name_lower": "reporte",
        "context_client": org.name if org else "Sin cliente",
        "context_farm": farm.name if farm else "Sin finca",
        "context_asset": None,
    }
    return render_template("agrovista/ndvi-tool.j2", **context)


@web.route("/secondary-objectives", methods=["GET"])
@login_required
def secondary_objectives():
    """Vista web GET-only para objetivos secundarios.
    
    NOTA: Este endpoint es solo para la interfaz web (renderiza template).
    Para operaciones CRUD completas (GET, POST, PUT, DELETE), usar los endpoints
    API en `agrovista/api_routes.py`.
    """
    context = {
        "dashboard": True,
        "title": "Objetivos secundarios",
        "description": "Gestion primaria de objetivos secundarios para NDVI.",
        "author": "Johnny De Castro",
        "site_title": "Agrovista",
        "data_menu": get_dashboard_menu(),
        "entity_name": "Objetivos secundarios",
        "entity_name_lower": "objetivo secundario",
    }
    return render_template("agrovista/secondary-objectives.j2", **context)


@web.route("/comparacion", methods=["GET"])
@login_required
def comparison_config():
    user_id = get_jwt_identity()
    claims = get_jwt()
    organizations = get_clients_for_user(user_id) if user_id else []
    org = organizations[0] if organizations else None
    farm = None
    if org:
        farm = (
            Farm.query.filter(Farm.org_id == org.id)
            .order_by(Farm.created_at.desc())
            .first()
        )
    context = {
        "dashboard": True,
        "title": "Comparación nutricional",
        "description": "Configuración de comparación nutricional.",
        "author": "Johnny De Castro",
        "site_title": "Comparación nutricional",
        "data_menu": get_dashboard_menu(),
        "entity_name": "Comparación nutricional",
        "entity_name_lower": "comparacion nutricional",
        "context_client": org.name if org else "Sin cliente",
        "context_farm": farm.name if farm else "Sin finca",
        "claims": claims,
    }
    return render_template("agrovista/comparacion-config.j2", **context)
