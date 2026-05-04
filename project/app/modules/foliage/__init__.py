"""Blueprint registrations for the foliage module."""

from flask import Blueprint

foliage = Blueprint(
    "foliage", __name__, url_prefix="/dashboard/foliage", template_folder="templates"
)
foliage_api = Blueprint("foliage_api", __name__, url_prefix="/api/foliage")

from . import api_routes, web_routes
