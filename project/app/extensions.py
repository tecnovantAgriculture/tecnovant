__doc__ = """El objetivo de este archivo  es la carga de los módulos en un archivo independiente para evitar la carga circular de los mismos.
"""
# Third party imports
from flask_caching import Cache
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

# Local application imports
jwt = JWTManager()
db = SQLAlchemy()
migrate = Migrate()
cache = Cache()
