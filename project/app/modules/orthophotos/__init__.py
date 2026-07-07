"""Modulo de ortofotos para cargas de pilotos y seguimiento interno."""

from flask import Blueprint

orthophotos = Blueprint("orthophotos", __name__, template_folder="templates")
orthophotos_api = Blueprint(
    "orthophotos_api", __name__, url_prefix="/api/orthophotos"
)

from . import api_routes, models, web_routes
