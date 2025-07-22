"""🚀 Application factory and extension initialization."""

# Python standard library imports
import logging
import os
from importlib import import_module

# Third party imports
from flask import Flask

# Local application imports
from .config import Config
from .extensions import cache, db, jwt, migrate
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


def register_blueprints(app):
    """
    Register Flask Blueprints from the configuration.

    Args:
        app (Flask): The Flask application instance.
    """
    if Config.CORE == True:
        try:
            from app.core import core, core_api

            app.register_blueprint(core)
            app.register_blueprint(core_api)
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

    # Configure logging and error handling
    logger = configure_logging()
    error_handler(app, logger)

    # flask url for user refresh token, is very important, the route most be exist
    app.config["JWT_REFRESH_COOKIE_PATH"] = "/api/core/refresh"

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
        :param None: No requiere parámetros
        :status 200: Retorna el contenido
        """
        context = {
            "title": "About Us",
            "description": "Descripción general del proyecto.",
            "author": "Johnny De Castro",
            "site_title": "Descripción",
        }

        return render_template("router_lister.j2", **context)

    ###############################################################

    return app
