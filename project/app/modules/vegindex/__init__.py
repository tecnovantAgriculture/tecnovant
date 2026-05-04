from flask import Blueprint

vegindex = Blueprint(
    "vegindex", __name__, url_prefix="/dashboard/vegindex", template_folder="templates"
)
vegindex_api = Blueprint("vegindex_api", __name__, url_prefix="/api/vegindex")

from . import api_routes, web_routes  # noqa: E402,F401
