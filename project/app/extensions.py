__doc__ = """El objetivo de este archivo  es la carga de los módulos en un archivo independiente para evitar la carga circular de los mismos.
"""
# Third party imports
from flask_caching import Cache
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

# Local application imports
jwt = JWTManager()
db = SQLAlchemy()
migrate = Migrate()
cache = Cache()
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
