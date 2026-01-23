from flask import Blueprint

agrovista = Blueprint(
    "agrovista",
    __name__,
    url_prefix="/dashboard/agrovista",
    template_folder="templates",
)
agrovista_api = Blueprint("agrovista_api", __name__, url_prefix="/api/agrovista")

from . import web_routes, api_routes, models
