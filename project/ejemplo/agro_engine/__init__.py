from flask import Blueprint

agro_engine = Blueprint("agro_engine", __name__, url_prefix='/dashboard/agro_engine', template_folder='templates')
agro_engine_api = Blueprint("agro_engine_api", __name__, url_prefix='/api/agro_engine')

from . import web_routes, api_routes, models
