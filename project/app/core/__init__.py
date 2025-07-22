"""Application core blueprints and route imports."""

from flask import Blueprint

core = Blueprint("core", __name__, url_prefix="/", template_folder="templates")

core_api = Blueprint("core_api", __name__, url_prefix="/api/core")

from . import api_routes, web_routes
