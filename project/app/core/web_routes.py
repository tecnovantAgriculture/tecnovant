"""📃 Rutas de páginas de la aplicación (jinja2)

CONVENCIÓN DE DECORADORES DE AUTENTICACIÓN:
- @login_required: Para rutas web estándar (redirige a login si no autenticado)
- @jwt_required(): Para rutas que requieren validación JWT explícita
- @api_login_required: Para rutas API que devuelven JSON 401 (no redirección)

Regla general: usar @login_required para rutas web que renderizan templates.
"""

# Third party imports
from datetime import date, datetime

from flask import Response, current_app, redirect, render_template, request, url_for
from flask_jwt_extended import (
    get_jwt,
    get_jwt_identity,
    jwt_required,
    verify_jwt_in_request,
)

# from sqlalchemy.orm import joinedload
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.extensions import db

# Local application imports
from . import core as web
from .config import CoreConfig
from .controller import (
    InstallationView,
    OrgView,
    ResetPasswordFormView,
    UserView,
    login_required,
)
from .models import RoleEnum, User, get_clients_for_user
from .services.profile_service import ProfileService

__doc__ = """
paginas de bienvenida y contenido general
"""


def get_index_menu():
    """Menu for home page (core.index)."""
    return {
        "menu": [
            {"name": "Home", "url": url_for("core.index")},
            {"name": "Dashboard", "url": url_for("core.dashboard")},
        ]
    }


def get_dashboard_menu():
    """Menu for dashboard page (core.dashboard)."""
    menu_items = [
        {"name": "Home", "url": url_for("core.index")},
    ]
    if current_app.config.get("DEBUG", False):
        menu_items.append({"name": "Info", "url": "/info"})
    return {"menu": menu_items}


# public endpoint
@web.route("/.well-known/appspecific/com.chrome.devtools.json")
def chrome_devtools_json():
    """Endpoint to satisfy Chrome DevTools automatic probing.
    Returns an empty JSON object to prevent 404 noise in the logs.
    """
    return Response("{}", status=200, mimetype="application/json")


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
            data_menu=get_index_menu(),
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
    """Renderiza el formulario de recuperación de contraseña.

    Página pública que permite al usuario solicitar un enlace de
    restablecimiento de contraseña vía email.

    :status 200: Formulario de recuperación de contraseña
    """
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
    """Página principal del panel de control post-login.

    Muestra estadísticas agregadas del tenant (análisis del mes,
    fincas activas, imágenes procesadas, lotes analizados,
    recomendaciones generadas). Solo incluye datos de organizaciones
    asociadas al usuario autenticado.

    :status 200: Dashboard con estadísticas del tenant
    """
    user_id = get_jwt_identity()
    user = User.query.get(user_id) if user_id else None
    organizations = get_clients_for_user(user_id) if user_id else []
    org_ids = [org.id for org in organizations] if organizations else []

    today = date.today()
    month_start = date(today.year, today.month, 1)
    next_month = date(today.year + (today.month == 12), (today.month % 12) + 1, 1)

    from app.modules.agrovista.models import NDVIImage
    from app.modules.foliage.models import (
        CommonAnalysis,
        Farm,
        Lot,
        LotCrop,
        Recommendation,
    )

    analyses_this_month = 0
    farms_active = 0
    images_processed = 0
    lots_analyzed = 0
    recommendations_generated = 0
    reports_exported = 0

    if org_ids:
        analyses_this_month = (
            CommonAnalysis.query.join(Lot)
            .join(Farm)
            .filter(
                Farm.org_id.in_(org_ids),
                CommonAnalysis.date >= month_start,
                CommonAnalysis.date < next_month,
            )
            .count()
        )
        farms_active = Farm.query.filter(Farm.org_id.in_(org_ids)).count()
        lots_analyzed = (
            db.session.query(func.count(func.distinct(CommonAnalysis.lot_id)))
            .join(Lot)
            .join(Farm)
            .filter(Farm.org_id.in_(org_ids))
            .scalar()
            or 0
        )
        recommendations_generated = (
            Recommendation.query.join(Lot)
            .join(Farm)
            .filter(Farm.org_id.in_(org_ids), Recommendation.active.is_(True))
            .count()
        )
        reports_exported = (
            Recommendation.query.join(Lot)
            .join(Farm)
            .filter(
                Farm.org_id.in_(org_ids),
                Recommendation.active.is_(True),
                Recommendation.applied.is_(True),
            )
            .count()
        )

    # Count only GEOTIFF assets that are available in the platform
    from app.modules.media.models import Asset, AssetType

    images_processed = Asset.query.filter(
        Asset.asset_type == AssetType.GEOTIFF.value
    ).count()

    last_recommendation = None
    if org_ids:
        last_recommendation = (
            Recommendation.query.options(
                joinedload(Recommendation.lot).joinedload(Lot.farm)
            )
            .join(Lot)
            .join(Farm)
            .filter(Farm.org_id.in_(org_ids), Recommendation.active.is_(True))
            .order_by(Recommendation.created_at.desc())
            .first()
        )

    def _relative_time_label(value):
        if not value:
            return "Sin fecha"
        delta_days = (today - value.date()).days
        if delta_days <= 0:
            return "Hoy"
        if delta_days == 1:
            return "Hace 1 día"
        if delta_days < 7:
            return f"Hace {delta_days} días"
        weeks = delta_days // 7
        if weeks == 1:
            return "Hace 1 semana"
        if weeks < 5:
            return f"Hace {weeks} semanas"
        return f"Hace {delta_days} días"

    recent_lot_crops = []
    if org_ids:
        lot_crops = (
            LotCrop.query.options(
                joinedload(LotCrop.lot).joinedload(Lot.farm),
                joinedload(LotCrop.crop),
            )
            .join(Lot)
            .join(Farm)
            .filter(Farm.org_id.in_(org_ids))
            .order_by(LotCrop.created_at.desc())
            .limit(3)
            .all()
        )
        for lot_crop in lot_crops:
            lot = lot_crop.lot
            farm = lot.farm if lot else None
            crop = lot_crop.crop
            recent_lot_crops.append(
                {
                    "farm_name": farm.name if farm else "Sin finca",
                    "lot_name": lot.name if lot else "Sin lote",
                    "crop_name": crop.name if crop else "Sin cultivo",
                    "time_label": _relative_time_label(lot_crop.created_at),
                }
            )

    # Recent image analyses: use Asset table (source of truth), not orphaned NDVIImage
    from app.modules.media.models import Asset, AssetType

    recent_image_analyses = []
    recent_assets = (
        Asset.query.filter(Asset.asset_type == AssetType.GEOTIFF.value)
        .order_by(Asset.created_at.desc())
        .limit(3)
        .all()
    )
    for asset in recent_assets:
        recent_image_analyses.append(
            {
                "filename": asset.original_name,
                "dimensions": f"{asset.width or '?'} x {asset.height or '?'}",
                "date": (
                    asset.created_at.strftime("%d/%m/%Y")
                    if asset.created_at
                    else "Sin fecha"
                ),
            }
        )

    last_analysis_summary = None
    if last_recommendation and last_recommendation.lot and last_recommendation.lot.farm:
        last_analysis_summary = {
            "farm_name": last_recommendation.lot.farm.name,
            "lot_name": last_recommendation.lot.name,
        }

    context = {
        "dashboard": True,
        "title": "Dashboard TecnoAgro",
        "description": "Panel de control.",
        "author": "Johnny De Castro",
        "site_title": "Panel de Control",
        "og_image": "/img/og-image.jpg",
        "twitter_image": "/img/twitter-image.jpg",
        "data_menu": get_dashboard_menu(),
        "user_full_name": user.full_name if user else None,
        "kpis": {
            "analyses_month": analyses_this_month,
            "farms_active": farms_active,
            "images_processed": images_processed,
        },
        "recent_lot_crops": recent_lot_crops,
        "recent_image_analyses": recent_image_analyses,
        "last_analysis_summary": last_analysis_summary,
        "operation_stats": {
            "lots_analyzed": lots_analyzed,
            "recommendations_generated": recommendations_generated,
            "reports_exported": reports_exported,
        },
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
        "description": "Administre usuarios y sus permisos de acceso.",
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
        "description": "Administre clientes y su relación con fincas.",
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

    # Get extended profile data
    extended = ProfileService.get_extended_profile(user)

    # Format last_access timestamp
    last_access = extended.get("last_access")
    formatted_last_access = None
    if last_access:
        try:
            # Parse ISO format string (assuming UTC, no timezone)
            dt = datetime.fromisoformat(last_access.replace("Z", ""))
            formatted_last_access = dt.strftime("%d/%m/%Y %H:%M")
        except (ValueError, AttributeError):
            formatted_last_access = last_access

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
        # Extended fields
        "avatar_url": extended.get("avatar_url"),
        "birthday": extended.get("birthday"),
        "last_access": last_access,
        "formatted_last_access": formatted_last_access,
        "avatar_default": CoreConfig.AVATAR_DEFAULT,
        # Handle organizations - pass a list of names or IDs/names
        "organizations": extended.get("organizations", []),
    }

    return render_template("dashboard/profile.j2", **context, request=request)


web.add_url_rule("/install", view_func=InstallationView.as_view("install"))
