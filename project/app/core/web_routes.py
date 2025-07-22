"""📃 Rutas de páginas de la aplicación (jinja2)"""

# Third party imports
from flask import redirect, render_template, request, url_for
from flask_jwt_extended import (
    get_jwt,
    get_jwt_identity,
    jwt_required,
    verify_jwt_in_request,
)

# Local application imports
from . import core as web
from .controller import (
    InstallationView,
    OrgView,
    ResetPasswordFormView,
    UserView,
    login_required,
)
from .models import RoleEnum, User, get_clients_for_user

# from sqlalchemy.orm import joinedload


__doc__ = """
paginas de bienvenida y contenido general
"""


def get_dashboard_menu():
    return {
        "menu": [
            {"name": "Home", "url": url_for("core.index")},
            {"name": "Logout", "url": url_for("core.logout")},
            {"name": "Profile", "url": url_for("core.profile")},
        ]
    }


@web.route("/")
def index():
    """Página: Inicio de la aplicación "Welcome Page"
    :param None: No requiere parámetros, opcional obtiene el ID del usuario autenticado
    :status 200: Retorna la página principal
    """
    user_authenticated = False
    claims = None  # Initialize claims variable here
    context = {
        "has_login_button": True,
        "is_full_width": True,
        "title": "Welcome",
        "description": "Bienvenido a TecnoAgro.",
        "keywords": "gestión foliar, manejo de suelos y cultivos",
        "author": "Johnny De Castro",
        "site_title": "Software para gestión de  datos de foliar",
        "og_image": "/img/og-image.jpg",
        "twitter_image": "/img/twitter-image.jpg",
    }
    try:
        verify_jwt_in_request()
        claims = get_jwt_identity()
        if claims is not None:
            user_authenticated = True
        else:
            user_authenticated = False
    except Exception as e:
        # Si hay un error al obtener el token, asume que no está autenticado
        user_authenticated = False
    return (
        render_template(
            "home.j2",
            is_user_authenticated=user_authenticated,
            **context,
            request=request,
        ),
        200,
    )


__doc__ = """
Paginas de autenticacion y autorizacion
"""


@web.route("/login")
def login():
    """Página: Inicio de sesión. Implementa core_api.login"""
    context = {
        "has_login_button": False,
        "is_full_width": True,
        "title": "Bienvenido a App TecnoAgro",
        "description": "Acceso a la aplicación.",
        "author": "Johnny De Castro",
        "site_title": "Login",
        "og_image": "/img/og-image.jpg",
        "twitter_image": "/img/twitter-image.jpg",
    }
    try:
        verify_jwt_in_request()
        user_id = get_jwt_identity()
        if user_id:
            return redirect(url_for("core.dashboard"))
    except:
        pass
    return render_template(
        "login.j2", login_status="not_authenticated", **context, request=request
    )


@web.route("/logout")
def logout():
    """Página de cierre de sesión. Implementa core_api.logout"""
    return render_template("logout.j2")


@web.route("/forgot_password")
def forgot_password():
    return render_template("forgot_password.j2")


web.add_url_rule(
    "/reset-password/<token>",
    view_func=ResetPasswordFormView.as_view("reset_password_form"),
    methods=["GET"],
)

__doc__ = """
Paginas de dashboard y administracion
"""


@web.route("/dashboard")
@login_required
def dashboard():

    context = {
        "dashboard": True,
        "title": "Dashboard TecnoAgro",
        "description": "Panel de control.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "og_image": "/img/og-image.jpg",
        "twitter_image": "/img/twitter-image.jpg",
        "data_menu": get_dashboard_menu(),
    }

    return (
        render_template(
            "dashboard/welcome.j2",
            **context,
            request=request,
        ),
        200,
    )


@web.route("/home/not-authorized")
def not_authorized():
    """
    Página de error para usuarios no autorizados
    """
    return render_template("dashboard/not_authorized.j2")


@web.route("/dashboard/users")
@jwt_required()
def amd_users():
    """
    Página: Renderiza la vista de usuarios
    """
    user_id = get_jwt_identity()
    context = {
        "dashboard": True,
        "title": "Gestión de usuarios",
        "description": "Administración de usuarios.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "data_menu": get_dashboard_menu(),
    }
    user_view = UserView()
    response, status_code = user_view._get_user_list()
    items = response.get_json()
    assigned_org = get_clients_for_user(user_id)
    org_dict = {org.name: org.id for org in assigned_org}
    # logging.error("Items obtenidos: %s, org_dict: %s", items, org_dict)

    if status_code != 200:
        return render_template("error.j2"), status_code
    return (
        render_template(
            "dashboard/users.j2",
            items=items,
            org_dict=org_dict,
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/clients")
@jwt_required()
def amd_clients():
    """
    Página: Renderiza la vista de clientes
    """
    claims = get_jwt()
    user_role = claims.get("rol")
    user_id = claims.get("id")
    context = {
        "dashboard": True,
        "title": "Gestión de clientes",
        "description": "Administración de clientes.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "data_menu": get_dashboard_menu(),
    }
    org_view = OrgView()
    response, status_code = org_view._get_org_list()
    if status_code != 200:
        return render_template("error.j2"), status_code
    items = response.get_json()
    if user_role == "administrator":
        # Obtener todos los usuarios con rol reseller
        resellers = User.query.filter_by(role=RoleEnum.RESELLER).all()
        reseller_dict = {"Sin Reseller": None}
        for user in resellers:
            reseller_dict[user.full_name] = user.id
    elif user_role == "reseller":
        # Obtener el usuario actual
        user = User.query.get(user_id)
        reseller_dict = {user.full_name: user.username}
    return (
        render_template(
            "dashboard/clients.j2",
            items=items,
            reseller_dict=reseller_dict,
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/profile")
@jwt_required()
def profile():
    """
    Página: Renderiza la vista de perfil de usuario
    """
    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if not user:
        # Handle case where user might not be found (though JWT ensures they exist)
        return redirect(url_for("core.logout"))

    # Prepare data for the template
    context = {
        "dashboard": True,
        "title": "Mi Perfil",
        "description": "Gestiona tu información personal y contraseña.",
        "author": "Johnny De Castro",
        "site_title": "Mi Perfil",
        "data_menu": get_dashboard_menu(),  # Ensure get_dashboard_menu is accessible
        # Pass user data explicitly
        "user_id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "role": user.role.description,  # Use the description
        # Handle organizations - pass a list of names or IDs/names
        "organizations": [
            {"id": org.id, "name": org.name} for org in user.organizations.all()
        ],
    }
    # Note: The 'client' variable in the template is ambiguous.
    # We now pass 'organizations'. You'll need to adjust the template.
    # If you only want the *first* org name for simplicity in the template:
    # context["client_org_name"] = user.organizations.first().name if user.organizations.first() else "N/A"

    return render_template("dashboard/profile.j2", **context, request=request)


web.add_url_rule("/install", view_func=InstallationView.as_view("install"))
