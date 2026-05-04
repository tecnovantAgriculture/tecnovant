"""🚀 Application factory and extension initialization."""

# Python standard library imports
import logging
import os
from importlib import import_module

# Third party imports
from flask import Flask, request

# Local application imports
from .config import Config
from .extensions import cache, db, jwt, limiter, migrate
from .helpers.error_handler import error_handler, setup_logging
from .helpers.helpers_functions import inject_user, merge_dicts
from .helpers.mail import mail


def init_extensions(app):
    """
    Initialize Flask extensions.

    Args:
        app (Flask): The Flask application instance.
    """
    mail.init_app(app)
    jwt.init_app(app)
    db.init_app(app)
    migrate.init_app(app, db)
    cache.init_app(app)
    
    # Configure rate limiter storage (Redis if available, else memory)
    # RATELIMIT_STORAGE_URI must be set in app.config BEFORE init_app
    if app.config.get("CACHE_REDIS_URL"):
        app.config["RATELIMIT_STORAGE_URI"] = app.config["CACHE_REDIS_URL"]
    else:
        app.config.setdefault("RATELIMIT_STORAGE_URI", "memory://")
    limiter.init_app(app)


def register_blueprints(app):
    """
    Register Flask Blueprints from the configuration.

    Args:
        app (Flask): The Flask application instance.
    """
    if Config.CORE == True:
        try:
            from app.core import core, core_api, core_api_v1

            app.register_blueprint(core)
            app.register_blueprint(core_api)
            app.register_blueprint(core_api_v1)
        except ImportError as e:
            logging.error(f"Failed to import core module: {e}")

    for module in Config.MODULES:
        module_name = f"app.modules.{module}"
        try:
            module_obj = import_module(module_name)
            blueprint_web = getattr(module_obj, module)
            app.register_blueprint(blueprint_web)

            # Verificar si existe el blueprint MODULE_api
            if hasattr(module_obj, f"{module}_api"):
                blueprint_api = getattr(module_obj, f"{module}_api")
                app.register_blueprint(blueprint_api)
        except ImportError as e:
            logging.error(f"Failed to import module {module_name}: {e}")
        except AttributeError as e:
            logging.error(f"Blueprint {module} not found in module {module_name}: {e}")


def init_avatar_storage(app):
    """Initialize avatar storage directory at application startup.

    Args:
        app (Flask): The Flask application instance.
    """
    try:
        from app.core.services.avatar_service import AvatarService
        # Usar app context para que current_app esté disponible
        # (necesario para acceder a app.config durante flask db migrate)
        with app.app_context():
            AvatarService.ensure_storage_directory()
            app.logger.info("Avatar storage directory initialized")
    except ImportError as e:
        app.logger.warning(f"Cannot initialize avatar storage: {e}")
    except Exception as e:
        app.logger.error(f"Failed to initialize avatar storage directory: {e}")


def configure_logging():
    """✍🏼 Configure application logging.

    Returns:
        logging.Logger: The configured logger instance.
    """
    logging.getLogger("mail").setLevel(logging.DEBUG)
    return setup_logging()


def create_app():
    """🌟 Factory function to create and configure the Flask application.

    Returns:
        Flask: The configured Flask application instance.
    """
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)

    # Set template folder based on config theme
    theme = Config.THEME
    template_folder = os.path.join(app.root_path, "templates", theme)
    app.template_folder = template_folder


    # Initialize extensions and blueprints
    init_extensions(app)
    register_blueprints(app)

    # Register breadcrumbs context processor (local import avoids circular dependency)
    try:
        from .core.navigation import register_breadcrumbs_context
        register_breadcrumbs_context(app)
    except Exception as e:
        logging.warning(f"Could not register breadcrumbs context processor: {e}")

    # Initialize avatar storage directory
    init_avatar_storage(app)

    # Configure logging and error handling
    logger = configure_logging()
    error_handler(app, logger)

    # flask url for user refresh token, is very important, the route most be exist
    app.config["JWT_REFRESH_COOKIE_PATH"] = "/api/core/refresh"

    # ── Inject CSRF meta tag into HTML responses ──────────────
    from flask_jwt_extended import get_csrf_token as jwt_get_csrf

    @app.after_request
    def inject_csrf_meta(response):
        """
        Insert <meta name="csrf-token" content="..."> into HTML <head>.
        The token comes from the JWT access cookie (csrf_access_token).
        If no JWT is present (anonymous user), the meta tag is omitted —
        the JS fallback reads the cookie directly.
        """
        ct = response.content_type or ""
        if "text/html" not in ct:
            return response

        # Try to get CSRF token from the JWT cookie set by flask-jwt-extended
        csrf_cookie = request.cookies.get("csrf_access_token", "")
        if not csrf_cookie:
            # Also check flask-wtf style cookie
            csrf_cookie = request.cookies.get("csrf_token", "")

        if csrf_cookie and response.status_code < 400:
            meta_tag = f'<meta name="csrf-token" content="{csrf_cookie}">'
            # Insert before </head>
            body = response.get_data(as_text=True)
            marker = "</head>"
            if marker.lower() in body.lower():
                # Case-insensitive replace
                idx = body.lower().index(marker)
                body = body[:idx] + f"    {meta_tag}\n" + body[idx:]
                response.set_data(body)

        return response

    # from app.core.controller import initialize_system

    # @app.before_request
    # def before_request():
    #     db.create_all()
    #     initialize_system()

    @app.context_processor
    def inject_debug():
        return dict(DEBUG=app.config["DEBUG"])

    app.jinja_env.filters["merge"] = merge_dicts
    app.jinja_env.filters["merge_dicts"] = merge_dicts

    @app.context_processor
    def inject_context():
        """Agrega múltiples funciones al contexto de Jinja2."""
        context = {}
        context.update(inject_user())
        return context

    ###############################################################
    """
    List all the routes in the application for debugging and api documentation purposes
    """
    from flask import render_template

    from .helpers.route_lister import RouteLister

    view = RouteLister.as_view("list_routes")
    app.add_url_rule("/list_endpoints", view_func=view)

    @app.route("/info")
    def info():
        """Página: Información general del proyecto
        
        Acceso controlado por modo DEBUG:
        - DEBUG=True: acceso público (desarrollo)
        - DEBUG=False: solo usuarios administradores (producción)
        
        :param None: No requiere parámetros
        :status 200: Retorna el contenido
        :status 403: Acceso denegado en producción para no-administradores
        """
        from flask import abort
        from flask_jwt_extended import get_jwt_identity
        from app.core.models import User
        
        # Si DEBUG está activado, acceso público
        if app.config.get('DEBUG', False):
            context = {
                "title": "About Us",
                "description": "Descripción general del proyecto.",
                "author": "Johnny De Castro",
                "site_title": "Descripción",
            }
            return render_template("router_lister.j2", **context)
        
        # En producción, verificar que el usuario sea administrador
        user_id = get_jwt_identity()
        if not user_id:
            abort(403, description="Authentication required in production mode")
        
        user = User.query.get(user_id)
        if not user or not user.is_admin():
            abort(403, description="Admin privileges required in production mode")
        
        context = {
            "title": "About Us",
            "description": "Descripción general del proyecto.",
            "author": "Johnny De Castro",
            "site_title": "Descripción",
        }
        return render_template("router_lister.j2", **context)

    ###############################################################

    return app
