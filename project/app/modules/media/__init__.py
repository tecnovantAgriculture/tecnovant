"""Blueprints y bindings para la gestión centralizada de activos multimedia.

El módulo ``media`` concentra los endpoints web y API relacionados con la
ingestión, exploración y selección de archivos cargados por los usuarios. Otras
áreas de la aplicación, como el flujo de Agrovista, interactúan con esta capa
en lugar de duplicar lógica de negocio o plantillas.
"""

from flask import Blueprint

media = Blueprint("media", __name__, url_prefix='/dashboard/media', template_folder='templates')
media_api = Blueprint("media_api", __name__, url_prefix='/api/media')

from . import web_routes, api_routes
