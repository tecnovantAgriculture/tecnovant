"""📃 Rutas de páginas de la aplicación (jinja2)

CONVENCIÓN DE DECORADORES DE AUTENTICACIÓN:
- @login_required: Para rutas web estándar (redirige a login si no autenticado)
- @jwt_required(): Para rutas que requieren validación JWT explícita
- @api_login_required: Para rutas API que devuelven JSON 401 (no redirección)

Regla general: usar @login_required para rutas web que renderizan templates.
"""

# Third party imports
import hashlib
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from flask import Response, current_app, flash, g, jsonify, redirect, render_template, request, session, url_for
from flask_jwt_extended import (
    get_jwt,
    get_jwt_identity,
    jwt_required,
    verify_jwt_in_request,
)

# from sqlalchemy.orm import joinedload
from sqlalchemy import false, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload
from werkzeug.security import check_password_hash, generate_password_hash

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
from .models import (
    MaintenanceDrone,
    OperationBillingRecord,
    OperationalActivity,
    OperationalActivityLog,
    PilotDevice,
    PilotCertification,
    PilotFlightLog,
    PilotOperationReport,
    PilotProfile,
    Organization,
    RoleEnum,
    User,
    get_clients_for_user,
)
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


def _parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_datetime_fields(day_value, time_value):
    if not day_value or not time_value:
        return None
    return datetime.strptime(f"{day_value} {time_value}", "%Y-%m-%d %H:%M")

def _parse_optional_decimal(value):
    value = (value or "").strip().replace(",", ".")
    if not value:
        return None
    try:
        return Decimal(value)
    except Exception:
        return None


def _activity_log(activity, action, message=None):
    db.session.add(
        OperationalActivityLog(
            activity=activity,
            user_id=get_jwt_identity(),
            action=action,
            message=message,
        )
    )


def _activity_payload(activity, farm_lookup=None, lot_lookup=None):
    if farm_lookup is None:
        farm_lookup = getattr(g, 'activity_farm_lookup', None)
    if lot_lookup is None:
        lot_lookup = getattr(g, 'activity_lot_lookup', None)
    organization_id = None
    farm_id = None
    lot_id = None
    billing_record = getattr(activity, "billing_record", None)
    if billing_record and billing_record.organization_id:
        organization_id = billing_record.organization_id

    try:
        from app.modules.foliage.models import Farm, Lot

        if not organization_id and activity.client_project:
            organization = Organization.query.filter(func.lower(Organization.name) == activity.client_project.lower()).first()
            organization_id = organization.id if organization else None
        if organization_id and activity.farm_name:
            farm_key = (organization_id, activity.farm_name.casefold())
            farm = (
                farm_lookup.get(farm_key)
                if farm_lookup is not None
                else Farm.query.filter(
                    Farm.org_id == organization_id,
                    func.lower(Farm.name) == activity.farm_name.lower(),
                ).first()
            )
            if farm:
                farm_id = farm.id
                if activity.lot_code:
                    lot_key = (farm.id, activity.lot_code.casefold())
                    lot = (
                        lot_lookup.get(lot_key)
                        if lot_lookup is not None
                        else Lot.query.filter(
                            Lot.farm_id == farm.id,
                            func.lower(Lot.name) == activity.lot_code.lower(),
                        ).first()
                    )
                    lot_id = lot.id if lot else None
    except Exception:
        pass

    return {
        "id": activity.id,
        "title": activity.title,
        "operation_type": activity.operation_type,
        "date": activity.starts_at.strftime("%Y-%m-%d"),
        "start_date": activity.starts_at.strftime("%Y-%m-%d"),
        "end_date": activity.ends_at.strftime("%Y-%m-%d"),
        "start_time": activity.starts_at.strftime("%H:%M"),
        "end_time": activity.ends_at.strftime("%H:%M"),
        "starts_at": activity.starts_at.isoformat(),
        "ends_at": activity.ends_at.isoformat(),
        "duration_minutes": activity.duration_minutes,
        "place": activity.place,
        "organization_id": organization_id,
        "program_start": (billing_record.scheduled_date.isoformat() if billing_record and billing_record.scheduled_date else activity.starts_at.strftime("%Y-%m-%d")),
        "program_end": (billing_record.executed_date.isoformat() if billing_record and billing_record.executed_date else activity.ends_at.strftime("%Y-%m-%d")),
        "final_client": ((billing_record.raw_payload or {}).get("final_client") if billing_record else "") or "",
        "farm_id": farm_id,
        "lot_id": lot_id,
        "client_project": activity.client_project or "",
        "farm_name": activity.farm_name or "",
        "paddocks": activity.paddocks or "",
        "area_hectares": str(activity.area_hectares) if activity.area_hectares is not None else "",
        "unit_price": str(billing_record.unit_price) if billing_record and billing_record.unit_price is not None else "",
        "rest_days": activity.rest_days if activity.rest_days is not None else "",
        "lot_code": activity.lot_code or "",
        "pilot_id": activity.pilot_id,
        "pilot_name": activity.pilot.full_name if activity.pilot else "",
        "drone_id": activity.drone_id,
        "drone_name": f"{activity.drone.brand} {activity.drone.model}" if activity.drone else "",
        "observations": activity.observations or "",
        "status": activity.status,
    }



def _month_name_es(value):
    names = [
        "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
        "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
    ]
    return names[value.month - 1]


def _resolve_activity_catalog_selection(create_missing=False):
    from app.modules.foliage.models import Farm, Lot

    g.activity_catalog_error = None
    organization_id = request.form.get("organization_id", type=int)
    farm_id = request.form.get("farm_id", type=int)
    lot_id = request.form.get("lot_id", type=int)
    organization = Organization.query.get(organization_id) if organization_id else None
    farm = Farm.query.get(farm_id) if farm_id else None
    lot = Lot.query.get(lot_id) if lot_id else None

    if lot:
        farm = lot.farm
    if farm and organization and organization.id != farm.org_id:
        g.activity_catalog_error = "La finca no pertenece al cliente seleccionado."
        return organization, None, None

    if create_missing and organization:
        farm_name = (request.form.get("farm_name") or "").strip()
        if not farm and farm_name:
            farm = Farm.query.filter(
                Farm.org_id == organization.id,
                func.lower(Farm.name) == farm_name.lower(),
            ).first()
            if not farm:
                farm = Farm(name=farm_name, org_id=organization.id)
                db.session.add(farm)
                db.session.flush()

        lot_name = (request.form.get("lot_code") or "").strip()
        if farm and not lot and lot_name:
            lot = Lot.query.filter(
                Lot.farm_id == farm.id,
                func.lower(Lot.name) == lot_name.lower(),
            ).first()
            if not lot:
                lot_area = _parse_optional_decimal(request.form.get("area_hectares"))
                if lot_area is None or lot_area <= 0:
                    g.activity_catalog_error = "Escribe el area del nuevo potrero en hectareas."
                else:
                    lot = Lot(name=lot_name, area=float(lot_area), farm_id=farm.id, active=True)
                    db.session.add(lot)
                    db.session.flush()

    if lot and farm and lot.farm_id != farm.id:
        g.activity_catalog_error = "El potrero no pertenece a la finca seleccionada."
        return organization, farm, None

    return organization, farm, lot


def _sync_activity_billing(activity, requested_unit_price=None):
    from app.modules.foliage.models import Farm, Lot

    organization, farm, lot = _resolve_activity_catalog_selection()
    if not organization and activity.client_project:
        organization = Organization.query.filter(func.lower(Organization.name) == activity.client_project.lower()).first()

    if organization and not farm and activity.farm_name:
        farm = Farm.query.filter(
            Farm.org_id == organization.id,
            func.lower(Farm.name) == activity.farm_name.lower(),
        ).first()
    if farm and not lot and activity.lot_code:
        lot = Lot.query.filter(
            Lot.farm_id == farm.id,
            func.lower(Lot.name) == activity.lot_code.lower(),
        ).first()

    if not organization and not farm:
        return

    record = getattr(activity, "billing_record", None)
    if not record:
        record = OperationBillingRecord(activity=activity)
        db.session.add(record)

    profile_data = organization.profile_data or {} if organization else {}
    unit_price = requested_unit_price
    if unit_price is None:
        unit_price = record.unit_price
    if unit_price is None:
        unit_price = _parse_optional_decimal(str(profile_data.get("billing_unit_price") or ""))
    area = activity.area_hectares or (Decimal(str(lot.area)) if lot and lot.area is not None else None)
    hours = Decimal(activity.duration_minutes or 0) / Decimal(60) if activity.duration_minutes else None

    record.organization_id = organization.id if organization else record.organization_id
    record.farm_name = farm.name if farm else activity.farm_name
    record.paddock_name = lot.name if lot else (activity.lot_code or activity.paddocks)
    record.area_hectares = area
    record.scheduled_date = activity.starts_at.date() if activity.starts_at else None
    record.executed_date = activity.completed_at.date() if activity.completed_at else (activity.starts_at.date() if activity.starts_at else None)
    record.billing_month = _month_name_es(record.executed_date or record.scheduled_date) if (record.executed_date or record.scheduled_date) else None
    record.unit_price = unit_price
    record.invoice_total = (area * unit_price) if area is not None and unit_price is not None else None
    record.pilot_name = activity.pilot.full_name if activity.pilot else None
    record.operation_hours = hours
    record.hectares_per_hour = (area / hours) if area is not None and hours and hours > 0 else None
    record.observations = activity.observations
    record.raw_payload = {
        **(record.raw_payload or {}),
        "source": "operational_calendar",
        "activity_id": activity.id,
        "activity_status": activity.status,
        "invoice_status": "pending" if not record.invoice_number else "invoiced",
        "final_client": organization.name if organization else activity.client_project,
        "organization_id": organization.id if organization else None,
        "farm_id": farm.id if farm else None,
        "lot_id": lot.id if lot else None,
    }

def _has_activity_conflict(pilot_id, drone_id, starts_at, ends_at, activity_id=None):
    base = OperationalActivity.query.filter(
        OperationalActivity.status.notin_(["cancelled", "completed"]),
        OperationalActivity.starts_at < ends_at,
        OperationalActivity.ends_at > starts_at,
    )
    if activity_id:
        base = base.filter(OperationalActivity.id != activity_id)

    pilot_busy = base.filter(OperationalActivity.pilot_id == pilot_id).first()
    drone_busy = base.filter(OperationalActivity.drone_id == drone_id).first()
    return pilot_busy, drone_busy


def _activity_form_payload():
    start_day = (request.form.get("start_date") or request.form.get("date") or "").strip()
    end_day = (request.form.get("end_date") or start_day).strip()
    start_time = (request.form.get("start_time") or "").strip()
    end_time = (request.form.get("end_time") or "").strip()
    starts_at = _parse_datetime_fields(start_day, start_time)
    ends_at = _parse_datetime_fields(end_day, end_time)
    duration_minutes = int((ends_at - starts_at).total_seconds() // 60) if starts_at and ends_at else 0
    organization, farm, lot = _resolve_activity_catalog_selection(create_missing=True)
    client_project = organization.name if organization else (request.form.get("client_project") or "").strip()
    farm_name = farm.name if farm else (request.form.get("farm_name") or "").strip()
    lot_code = lot.name if lot else (request.form.get("lot_code") or "").strip()
    area_hectares = _parse_optional_decimal(request.form.get("area_hectares"))
    if area_hectares is None and lot and lot.area is not None:
        area_hectares = Decimal(str(lot.area))

    return {
        "title": (request.form.get("title") or "").strip(),
        "operation_type": (request.form.get("operation_type") or "").strip(),
        "starts_at": starts_at,
        "ends_at": ends_at,
        "duration_minutes": duration_minutes,
        "place": (request.form.get("place") or "").strip(),
        "client_project": client_project or None,
        "farm_name": farm_name or None,
        "paddocks": (request.form.get("paddocks") or "").strip() or None,
        "area_hectares": area_hectares,
        "unit_price": _parse_optional_decimal(request.form.get("unit_price")),
        "rest_days": request.form.get("rest_days", type=int),
        "lot_code": lot_code or None,
        "pilot_id": request.form.get("pilot_id", type=int),
        "drone_id": request.form.get("drone_id", type=int),
        "observations": (request.form.get("observations") or "").strip() or None,
        "status": (request.form.get("status") or "scheduled").strip(),
    }

def _validate_activity_payload(payload, activity_id=None):
    if getattr(g, "activity_catalog_error", None):
        return g.activity_catalog_error
    required = ["title", "operation_type", "starts_at", "ends_at", "place", "client_project", "farm_name", "lot_code", "pilot_id", "drone_id"]
    if any(not payload.get(key) for key in required):
        return "Completa los campos obligatorios, cliente, finca y potrero."
    if payload["duration_minutes"] <= 0:
        return "La hora fin debe ser posterior a la hora inicio."
    if payload.get("area_hectares") is None or payload["area_hectares"] <= 0:
        return "El area debe ser mayor que cero."
    if payload.get("unit_price") is None or payload["unit_price"] < 0:
        return "Escribe un valor por hectarea valido."
    if payload.get("rest_days") is not None and payload["rest_days"] < 0:
        return "Los dias de descanso no pueden ser negativos."

    pilot = PilotProfile.query.get(payload["pilot_id"])
    if not pilot or pilot.status != "active":
        return "Selecciona un piloto activo."

    drone = MaintenanceDrone.query.get(payload["drone_id"])
    if not drone or drone.status != "Aeronavegable":
        return "Selecciona un dron aeronavegable."

    pilot_busy, drone_busy = _has_activity_conflict(
        payload["pilot_id"],
        payload["drone_id"],
        payload["starts_at"],
        payload["ends_at"],
        activity_id=activity_id,
    )
    if pilot_busy:
        return "El piloto ya tiene una actividad en ese horario."
    if drone_busy:
        return "El dron ya esta asignado en ese horario."
    return None


def _is_mobile_request():
    user_agent = (request.headers.get("User-Agent") or "").lower()
    mobile_tokens = (
        "android",
        "iphone",
        "ipad",
        "ipod",
        "mobile",
        "windows phone",
        "blackberry",
    )
    return any(token in user_agent for token in mobile_tokens)


def _pilot_mobile_guard():
    if _is_mobile_request():
        return None
    return (
        render_template(
            "pilot_portal/mobile_required.j2",
            title="Portal piloto",
            site_title="TecnoVant",
        ),
        403,
    )


def _pilot_device_fingerprint():
    raw = "|".join(
        [
            request.headers.get("User-Agent", ""),
            request.headers.get("Accept-Language", ""),
            request.remote_addr or "",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _current_pilot():
    pilot_id = session.get("pilot_id")
    if not pilot_id:
        return None
    return PilotProfile.query.get(pilot_id)


def _require_pilot():
    guard = _pilot_mobile_guard()
    if guard:
        return None, guard
    pilot = _current_pilot()
    if not pilot or pilot.status != "active":
        session.pop("pilot_id", None)
        return None, redirect(url_for("core.pilot_login"))
    return pilot, None


def _pilot_activity_query(pilot):
    return (
        OperationalActivity.query.options(
            joinedload(OperationalActivity.drone),
            joinedload(OperationalActivity.pilot),
        )
        .filter(OperationalActivity.pilot_id == pilot.id)
    )


def _pilot_minutes(pilot):
    total = (
        db.session.query(func.coalesce(func.sum(PilotFlightLog.flight_minutes), 0))
        .filter(PilotFlightLog.pilot_id == pilot.id)
        .scalar()
    )
    return int(total or 0)


def _format_hours(minutes):
    return round((minutes or 0) / 60, 1)


def _status_label(status):
    return {
        "scheduled": "Pendiente",
        "in_progress": "En proceso",
        "completed": "Finalizada",
        "cancelled": "Cancelada",
    }.get(status, status)


def _pilot_context(pilot, **extra):
    minutes = _pilot_minutes(pilot)
    context = {
        "pilot": pilot,
        "total_minutes": minutes,
        "total_hours": _format_hours(minutes),
        "status_label": _status_label,
        "title": "Portal piloto",
        "site_title": "TecnoVant",
    }
    context.update(extra)
    return context


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
    is_platform_admin = bool(user and user.is_admin())

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

    # Los assets aun no tienen una relacion directa con organizaciones. Para
    # evitar exponer archivos de otros clientes, solo se agregan globalmente
    # para el administrador de plataforma.
    if is_platform_admin:
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
    recent_assets = []
    if is_platform_admin:
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

    month_names_short = [
        "Ene", "Feb", "Mar", "Abr", "May", "Jun",
        "Jul", "Ago", "Sep", "Oct", "Nov", "Dic",
    ]
    current_month_start = today.replace(day=1)
    next_month_start = (current_month_start + timedelta(days=32)).replace(day=1)
    previous_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
    org_names = [org.name for org in organizations]

    def _month_hectares_series(start_date, end_date):
        day_count = (end_date - start_date).days
        daily = [Decimal("0") for _ in range(day_count)]
        logged_activity_ids = set()
        log_query = (
            PilotFlightLog.query.join(OperationalActivity, PilotFlightLog.activity_id == OperationalActivity.id)
            .filter(
                PilotFlightLog.flight_date >= start_date,
                PilotFlightLog.flight_date < end_date,
                PilotFlightLog.total_hectares.isnot(None),
            )
        )
        if not is_platform_admin:
            log_query = log_query.filter(
                OperationalActivity.client_project.in_(org_names) if org_names else false()
            )
        for log in log_query.all():
            if not log.flight_date:
                continue
            day_index = (log.flight_date - start_date).days
            if 0 <= day_index < day_count:
                daily[day_index] += Decimal(str(log.total_hectares or 0))
                if log.activity_id:
                    logged_activity_ids.add(log.activity_id)

        billing_query = OperationBillingRecord.query.filter(
            OperationBillingRecord.area_hectares.isnot(None),
            OperationBillingRecord.executed_date >= start_date,
            OperationBillingRecord.executed_date < end_date,
        )
        if not is_platform_admin:
            billing_query = billing_query.filter(
                OperationBillingRecord.organization_id.in_(org_ids) if org_ids else false()
            )
        for record in billing_query.all():
            if record.activity_id and record.activity_id in logged_activity_ids:
                continue
            if not record.executed_date:
                continue
            day_index = (record.executed_date - start_date).days
            if 0 <= day_index < day_count:
                daily[day_index] += Decimal(str(record.area_hectares or 0))

        running = Decimal("0")
        cumulative = []
        for value in daily:
            running += value
            cumulative.append(running)
        return daily, cumulative

    current_daily, current_cumulative = _month_hectares_series(current_month_start, next_month_start)
    previous_daily, previous_cumulative = _month_hectares_series(previous_month_start, current_month_start)
    chart_days = max(len(current_daily), len(previous_daily))

    def _chart_values(values):
        return [float(round(value, 2)) for value in values] + [None for _ in range(chart_days - len(values))]

    hectares_chart = {
        "labels": [str(day) for day in range(1, chart_days + 1)],
        "current_month": f"{month_names_short[current_month_start.month - 1]} {current_month_start.year}",
        "previous_month": f"{month_names_short[previous_month_start.month - 1]} {previous_month_start.year}",
        "current_daily": _chart_values(current_daily),
        "previous_daily": _chart_values(previous_daily),
        "current_cumulative": _chart_values(current_cumulative),
        "previous_cumulative": _chart_values(previous_cumulative),
        "current_total": float(round(sum(current_daily, Decimal("0")), 2)),
        "previous_total": float(round(sum(previous_daily, Decimal("0")), 2)),
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
        "hectares_chart": hectares_chart,
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


@web.route("/dashboard/operaciones/calendario")
@login_required
def operational_calendar():
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=7)
    today_start = datetime.combine(today, time.min)
    today_end = datetime.combine(today, time.max)
    week_start_dt = datetime.combine(week_start, time.min)
    week_end_dt = datetime.combine(week_end, time.min)

    current_user_id = get_jwt_identity()
    current_user = User.query.get(current_user_id)
    clients = get_clients_for_user(current_user_id)
    client_ids = [client.id for client in clients]
    is_platform_admin = bool(current_user and current_user.is_admin())

    activities_query = OperationalActivity.query.options(
        joinedload(OperationalActivity.pilot),
        joinedload(OperationalActivity.drone),
        joinedload(OperationalActivity.billing_record),
    ).outerjoin(OperationBillingRecord)
    if not is_platform_admin:
        activities_query = activities_query.filter(
            OperationBillingRecord.organization_id.in_(client_ids) if client_ids else false()
        )
    activities = activities_query.order_by(OperationalActivity.starts_at.asc()).all()

    pilots_query = PilotProfile.query
    drones_query = MaintenanceDrone.query
    if not is_platform_admin:
        pilot_ids = {activity.pilot_id for activity in activities}
        drone_ids = {activity.drone_id for activity in activities}
        pilots_query = pilots_query.filter(PilotProfile.id.in_(pilot_ids) if pilot_ids else false())
        drones_query = drones_query.filter(MaintenanceDrone.id.in_(drone_ids) if drone_ids else false())
    pilots = pilots_query.order_by(PilotProfile.first_name.asc()).all()
    drones = drones_query.order_by(MaintenanceDrone.brand.asc(), MaintenanceDrone.model.asc()).all()
    from app.modules.foliage.models import Farm, Lot

    farms_query = Farm.query.order_by(Farm.name.asc())
    lots_query = Lot.query.join(Farm).order_by(Lot.name.asc())
    if not is_platform_admin:
        farms_query = farms_query.filter(Farm.org_id.in_(client_ids) if client_ids else false())
        lots_query = lots_query.filter(Farm.org_id.in_(client_ids) if client_ids else false())
    farms = farms_query.all()
    lots = lots_query.all()
    farm_lookup = {(farm.org_id, farm.name.casefold()): farm for farm in farms}
    lot_lookup = {(lot.farm_id, lot.name.casefold()): lot for lot in lots}
    g.activity_farm_lookup = farm_lookup
    g.activity_lot_lookup = lot_lookup

    context = {
        "dashboard": True,
        "title": "Calendario Operativo",
        "description": "Planifica y consulta actividades operativas.",
        "author": "TecnoAgro",
        "site_title": "Operaciones",
        "page_title": "Calendario Operativo",
        "data_menu": get_dashboard_menu(),
        "pilots": pilots,
        "drones": drones,
        "clients": clients,
        "farms": farms,
        "lots": lots,
        "clients_json": [
            {"id": client.id, "name": client.name, "unit_price": (client.profile_data or {}).get("billing_unit_price") or ""}
            for client in clients
        ],
        "farms_json": [{"id": farm.id, "name": farm.name, "organization_id": farm.org_id} for farm in farms],
        "lots_json": [{"id": lot.id, "name": lot.name, "farm_id": lot.farm_id, "area": lot.area} for lot in lots],
        "activities": activities,
        "activities_json": [_activity_payload(activity) for activity in activities],
        "stats": {
            "today": activities_query.filter(
                OperationalActivity.starts_at >= today_start,
                OperationalActivity.starts_at <= today_end,
            ).count(),
            "week": activities_query.filter(
                OperationalActivity.starts_at >= week_start_dt,
                OperationalActivity.starts_at < week_end_dt,
            ).count(),
            "pending": activities_query.filter(OperationalActivity.status == "scheduled").count(),
            "completed": activities_query.filter(OperationalActivity.status == "completed").count(),
            "cancelled": activities_query.filter(OperationalActivity.status == "cancelled").count(),
        },
    }
    return (
        render_template(
            "dashboard/operational_calendar.j2",
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/operaciones/calendario/pilotos", methods=["POST"])
@login_required
def operational_calendar_create_pilot():
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()
    first_name = (request.form.get("first_name") or "").strip()
    last_name = (request.form.get("last_name") or "").strip()
    if not username or not password or not first_name or not last_name:
        return jsonify({"success": False, "message": "Completa usuario, clave, nombres y apellidos."}), 400

    pilot = PilotProfile(
        username=username,
        password_hash=generate_password_hash(password),
        role=(request.form.get("role") or "pilot").strip(),
        first_name=first_name,
        last_name=last_name,
        document_number=(request.form.get("document_number") or "").strip() or None,
        phone=(request.form.get("phone") or "").strip() or None,
        email=(request.form.get("email") or "").strip() or None,
        certification_status=(request.form.get("certification_status") or "Vigente").strip(),
        status=(request.form.get("status") or "active").strip(),
    )
    db.session.add(pilot)
    try:
        db.session.flush()
        cert_name = (request.form.get("certification_name") or "").strip()
        if cert_name:
            db.session.add(
                PilotCertification(
                    pilot=pilot,
                    name=cert_name,
                    issuer=(request.form.get("certification_issuer") or "").strip() or None,
                    certificate_number=(request.form.get("certificate_number") or "").strip() or None,
                    expires_at=_parse_date((request.form.get("certification_expires_at") or "").strip()),
                    status=pilot.certification_status,
                )
            )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"success": False, "message": "Ya existe un piloto con ese usuario."}), 400

    return jsonify({
        "success": True,
        "message": "Piloto registrado correctamente.",
        "pilot": {"id": pilot.id, "name": pilot.full_name},
    })


@web.route("/dashboard/operaciones/calendario/actividades", methods=["POST"])
@login_required
def operational_calendar_create_activity():
    payload = _activity_form_payload()
    error = _validate_activity_payload(payload)
    if error:
        return jsonify({"success": False, "message": error}), 400

    unit_price = payload.pop("unit_price", None)
    activity = OperationalActivity(
        **payload,
        created_by_id=get_jwt_identity(),
    )
    db.session.add(activity)
    db.session.flush()
    _activity_log(activity, "created", "Actividad creada.")
    _sync_activity_billing(activity, unit_price)
    db.session.commit()
    return jsonify({
        "success": True,
        "message": "Actividad creada correctamente.",
        "activity": _activity_payload(activity),
    })


@web.route("/dashboard/operaciones/calendario/actividades/<int:activity_id>", methods=["POST"])
@login_required
def operational_calendar_update_activity(activity_id):
    activity = OperationalActivity.query.get_or_404(activity_id)
    if activity.status in {"cancelled", "completed"}:
        return jsonify({"success": False, "message": "No puedes editar una actividad cerrada."}), 400

    payload = _activity_form_payload()
    error = _validate_activity_payload(payload, activity_id=activity.id)
    if error:
        return jsonify({"success": False, "message": error}), 400

    unit_price = payload.pop("unit_price", None)
    for key, value in payload.items():
        setattr(activity, key, value)
    _activity_log(activity, "updated", "Actividad actualizada.")
    _sync_activity_billing(activity, unit_price)
    db.session.commit()
    return jsonify({
        "success": True,
        "message": "Actividad actualizada correctamente.",
        "activity": _activity_payload(activity),
    })


@web.route("/dashboard/operaciones/calendario/actividades/<int:activity_id>/eliminar", methods=["POST"])
@login_required
def operational_calendar_delete_activity(activity_id):
    activity = OperationalActivity.query.get_or_404(activity_id)
    if activity.billing_record:
        db.session.delete(activity.billing_record)
    PilotFlightLog.query.filter_by(activity_id=activity.id).update(
        {PilotFlightLog.activity_id: None}, synchronize_session=False
    )
    PilotOperationReport.query.filter_by(activity_id=activity.id).update(
        {PilotOperationReport.activity_id: None}, synchronize_session=False
    )
    db.session.delete(activity)
    db.session.commit()
    return jsonify({"success": True, "message": "Actividad eliminada correctamente.", "activity_id": activity_id})


@web.route("/dashboard/operaciones/calendario/actividades/<int:activity_id>/cancelar", methods=["POST"])
@login_required
def operational_calendar_cancel_activity(activity_id):
    activity = OperationalActivity.query.get_or_404(activity_id)
    if activity.status == "completed":
        return jsonify({"success": False, "message": "No puedes cancelar una actividad finalizada."}), 400
    activity.status = "cancelled"
    activity.cancelled_at = datetime.utcnow()
    _activity_log(activity, "cancelled", "Actividad cancelada.")
    db.session.commit()
    return jsonify({"success": True, "message": "Actividad cancelada.", "activity": _activity_payload(activity)})


@web.route("/dashboard/operaciones/calendario/actividades/<int:activity_id>/finalizar", methods=["POST"])
@login_required
def operational_calendar_complete_activity(activity_id):
    activity = OperationalActivity.query.get_or_404(activity_id)
    if activity.status == "cancelled":
        return jsonify({"success": False, "message": "No puedes finalizar una actividad cancelada."}), 400
    activity.status = "completed"
    activity.completed_at = datetime.utcnow()
    _activity_log(activity, "completed", "Actividad finalizada.")
    _sync_activity_billing(activity)
    db.session.commit()
    return jsonify({"success": True, "message": "Actividad finalizada.", "activity": _activity_payload(activity)})


@web.route("/piloto")
def pilot_home():
    return redirect(url_for("core.pilot_panel" if session.get("pilot_id") else "core.pilot_login"))


@web.route("/piloto/login", methods=["GET", "POST"])
def pilot_login():
    guard = _pilot_mobile_guard()
    if guard:
        return guard

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()
        pilot = PilotProfile.query.filter(func.lower(PilotProfile.username) == username.lower()).first()
        if not pilot or pilot.status != "active" or not check_password_hash(pilot.password_hash, password):
            flash("Usuario o clave incorrectos.", "error")
            return redirect(url_for("core.pilot_login"))

        session["pilot_id"] = pilot.id
        fingerprint = _pilot_device_fingerprint()
        device = PilotDevice.query.filter_by(pilot_id=pilot.id, device_fingerprint=fingerprint).first()
        if not device:
            db.session.add(
                PilotDevice(
                    pilot=pilot,
                    device_fingerprint=fingerprint,
                    user_agent=(request.headers.get("User-Agent") or "")[:255],
                )
            )
        else:
            device.last_access_at = datetime.utcnow()
        db.session.commit()
        return redirect(url_for("core.pilot_panel"))

    return render_template(
        "pilot_portal/login.j2",
        title="Ingreso piloto",
        site_title="TecnoVant",
    )


@web.route("/piloto/logout", methods=["GET", "POST"])
def pilot_logout():
    session.pop("pilot_id", None)
    return redirect(url_for("core.pilot_login"))


@web.route("/piloto/panel")
def pilot_panel():
    pilot, response = _require_pilot()
    if response:
        return response

    now = datetime.now()
    today_start = datetime.combine(now.date(), time.min)
    today_end = datetime.combine(now.date(), time.max)
    week_end = today_start + timedelta(days=7)
    activities = (
        _pilot_activity_query(pilot)
        .filter(OperationalActivity.ends_at >= today_start)
        .order_by(OperationalActivity.starts_at.asc())
        .limit(10)
        .all()
    )
    today_count = (
        _pilot_activity_query(pilot)
        .filter(OperationalActivity.starts_at >= today_start, OperationalActivity.starts_at <= today_end)
        .count()
    )
    pending_count = _pilot_activity_query(pilot).filter_by(status="scheduled").count()
    week_count = (
        _pilot_activity_query(pilot)
        .filter(OperationalActivity.starts_at >= today_start, OperationalActivity.starts_at < week_end)
        .count()
    )
    last_log = (
        PilotFlightLog.query.filter_by(pilot_id=pilot.id)
        .order_by(PilotFlightLog.created_at.desc())
        .first()
    )
    return render_template(
        "pilot_portal/panel.j2",
        **_pilot_context(
            pilot,
            activities=activities,
            today_count=today_count,
            pending_count=pending_count,
            week_count=week_count,
            last_log=last_log,
        ),
    )


@web.route("/piloto/calendario")
def pilot_calendar():
    pilot, response = _require_pilot()
    if response:
        return response

    today = date.today()
    requested_year = request.args.get("year", type=int) or today.year
    requested_month = request.args.get("month", type=int) or today.month
    if requested_month < 1 or requested_month > 12:
        requested_year = today.year
        requested_month = today.month

    month_anchor = date(requested_year, requested_month, 1)
    next_month = date(month_anchor.year + (month_anchor.month == 12), (month_anchor.month % 12) + 1, 1)
    previous_month = (month_anchor - timedelta(days=1)).replace(day=1)

    start = datetime.combine(month_anchor, time.min)
    end = datetime.combine(next_month, time.min)
    activities = (
        _pilot_activity_query(pilot)
        .filter(OperationalActivity.starts_at >= start, OperationalActivity.starts_at < end)
        .order_by(OperationalActivity.starts_at.asc())
        .all()
    )
    grouped = {}
    for activity in activities:
        key = activity.starts_at.date()
        grouped.setdefault(key, []).append(activity)

    month_start_offset = (month_anchor.weekday()) % 7
    calendar_start = month_anchor - timedelta(days=month_start_offset)
    calendar_days = []
    for index in range(42):
        day = calendar_start + timedelta(days=index)
        calendar_days.append(
            {
                "date": day,
                "in_month": month_anchor <= day < next_month,
                "count": len(grouped.get(day, [])),
                "is_today": day == today,
            }
        )

    month_names = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    return render_template(
        "pilot_portal/calendar.j2",
        **_pilot_context(
            pilot,
            grouped=grouped,
            calendar_days=calendar_days,
            month_anchor=month_anchor,
            month_title=f"{month_names[month_anchor.month - 1].capitalize()} {month_anchor.year}",
            previous_month=previous_month,
            next_month=next_month,
        ),
    )

@web.route("/piloto/bitacora", methods=["GET", "POST"])
def pilot_flight_log():
    pilot, response = _require_pilot()
    if response:
        return response

    if request.method == "POST":
        activity_id = request.form.get("activity_id", type=int)
        activity = None
        if activity_id:
            activity = _pilot_activity_query(pilot).filter(OperationalActivity.id == activity_id).first()
            if not activity:
                flash("La operacion seleccionada no pertenece a tu agenda.", "error")
                return redirect(url_for("core.pilot_flight_log"))

        drone_id = request.form.get("drone_id", type=int)
        drone = MaintenanceDrone.query.get(drone_id) if drone_id else (activity.drone if activity else None)
        flight_date = _parse_date((request.form.get("flight_date") or "").strip())
        start_day = (request.form.get("start_date") or request.form.get("flight_date") or "").strip()
        end_day = (request.form.get("end_date") or start_day).strip()
        started_at = _parse_datetime_fields(start_day, (request.form.get("start_time") or "").strip())
        ended_at = _parse_datetime_fields(end_day, (request.form.get("end_time") or "").strip())

        if not drone or not flight_date or not started_at or not ended_at or ended_at <= started_at:
            flash("Completa dron, fecha y horas reales de vuelo.", "error")
            return redirect(url_for("core.pilot_flight_log"))

        minutes = int((ended_at - started_at).total_seconds() // 60)
        flight_log = PilotFlightLog(
            pilot=pilot,
            activity=activity,
            drone=drone,
            flight_date=flight_date,
            started_at=started_at,
            ended_at=ended_at,
            flight_minutes=minutes,
            takeoff_location=(request.form.get("takeoff_location") or "").strip() or (activity.place if activity else None),
            landing_location=(request.form.get("landing_location") or "").strip() or (activity.place if activity else None),
            weather=(request.form.get("weather") or "").strip() or None,
            battery_cycles=request.form.get("battery_cycles", type=int),
            total_hectares=_parse_optional_decimal(request.form.get("total_hectares")),
            notes=(request.form.get("notes") or "").strip() or None,
        )
        db.session.add(flight_log)
        drone.flight_hours = (drone.flight_hours or Decimal("0")) + (Decimal(minutes) / Decimal(60))
        if activity and activity.status not in {"cancelled", "completed"}:
            activity.status = "in_progress"
            activity.completed_at = None
            _activity_log(activity, "pilot_log_saved", "El piloto registro bitacora manual.")
        db.session.commit()
        flash("Bitacora registrada correctamente.", "success")
        return redirect(url_for("core.pilot_flight_log"))

    today_start = datetime.combine(date.today(), time.min)
    activities = (
        _pilot_activity_query(pilot)
        .filter(OperationalActivity.starts_at >= today_start - timedelta(days=30))
        .order_by(OperationalActivity.starts_at.desc())
        .limit(30)
        .all()
    )
    drones = MaintenanceDrone.query.order_by(MaintenanceDrone.brand.asc(), MaintenanceDrone.model.asc()).all()
    logs = (
        PilotFlightLog.query.options(joinedload(PilotFlightLog.drone), joinedload(PilotFlightLog.activity))
        .filter(PilotFlightLog.pilot_id == pilot.id)
        .order_by(PilotFlightLog.flight_date.desc(), PilotFlightLog.created_at.desc())
        .limit(10)
        .all()
    )
    return render_template(
        "pilot_portal/flight_log.j2",
        **_pilot_context(pilot, activities=activities, drones=drones, logs=logs),
    )


@web.route("/piloto/ortofotos", methods=["GET", "POST"])
def pilot_orthophotos():
    pilot, response = _require_pilot()
    if response:
        return response

    from app.modules.media.controller import MediaController
    from app.modules.orthophotos.models import OrthophotoMission, OrthophotoPhoto

    pilot_marker = f"Piloto: {pilot.username}"

    def pilot_missions_query():
        return OrthophotoMission.query.filter(
            OrthophotoMission.description.ilike(f"%{pilot_marker}%")
        )

    if request.method == "POST":
        mission_id = request.form.get("mission_id", type=int)
        mission_name = (request.form.get("mission_name") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        files = [file for file in request.files.getlist("files") if file and getattr(file, "filename", None)]

        if not files:
            flash("Selecciona las imagenes de la mision.", "error")
            return redirect(url_for("core.pilot_orthophotos"))

        mission = None
        if mission_id:
            mission = pilot_missions_query().filter(OrthophotoMission.id == mission_id).first()

        if mission is None:
            if not mission_name:
                mission_name = f"Ortofotos {pilot.full_name} {date.today().strftime('%d/%m/%Y')}"
            description_parts = [
                "Carga movil desde portal piloto.",
                pilot_marker,
                f"Nombre piloto: {pilot.full_name}",
            ]
            if notes:
                description_parts.append(f"Observaciones: {notes}")
            mission = OrthophotoMission(
                name=mission_name,
                description=" | ".join(description_parts),
                status="receiving",
            )
            db.session.add(mission)
            db.session.flush()
        else:
            mission.status = "receiving"
            mission.processing_error = None
            mission.progress = None
            if notes and (mission.description or "").find(notes) == -1:
                mission.description = f"{mission.description or pilot_marker} | Observaciones: {notes}"

        ctrl = MediaController()
        uploaded = 0
        errors = []
        for file in files:
            try:
                asset, _created = ctrl.save_local_upload(file)
                db.session.add(
                    OrthophotoPhoto(
                        mission_id=mission.id,
                        asset_id=asset.id,
                        original_name=file.filename or asset.original_name,
                    )
                )
                uploaded += 1
            except ValueError as exc:
                errors.append(f"{file.filename}: {exc}")
            except Exception as exc:
                current_app.logger.exception("pilot orthophotos: failed to upload %s", file.filename)
                errors.append(f"{file.filename}: {exc or 'No se pudo cargar'}")

        if uploaded:
            db.session.commit()
            message = f"Se cargaron {uploaded} imagenes para procesamiento."
            if errors:
                message += " Algunas imagenes requieren revision."
            flash(message, "success")
        else:
            db.session.rollback()
            flash("No se pudo cargar ninguna imagen. Revisa los archivos e intenta nuevamente.", "error")

        if errors:
            for error in errors[:3]:
                flash(error, "error")
        return redirect(url_for("core.pilot_orthophotos"))

    missions = (
        pilot_missions_query()
        .order_by(OrthophotoMission.created_at.desc())
        .limit(12)
        .all()
    )
    return render_template(
        "pilot_portal/orthophotos.j2",
        **_pilot_context(pilot, missions=missions),
    )


@web.route("/piloto/operaciones/<int:activity_id>")
def pilot_activity_detail(activity_id):
    pilot, response = _require_pilot()
    if response:
        return response

    activity = _pilot_activity_query(pilot).filter(OperationalActivity.id == activity_id).first_or_404()
    flight_log = PilotFlightLog.query.filter_by(pilot_id=pilot.id, activity_id=activity.id).first()
    reports = (
        PilotOperationReport.query.filter_by(pilot_id=pilot.id, activity_id=activity.id)
        .order_by(PilotOperationReport.created_at.desc())
        .all()
    )
    return render_template(
        "pilot_portal/activity_detail.j2",
        **_pilot_context(pilot, activity=activity, flight_log=flight_log, reports=reports),
    )


@web.route("/piloto/operaciones/<int:activity_id>/iniciar", methods=["POST"])
def pilot_start_activity(activity_id):
    pilot, response = _require_pilot()
    if response:
        return response

    activity = _pilot_activity_query(pilot).filter(OperationalActivity.id == activity_id).first_or_404()
    if activity.status == "scheduled":
        activity.status = "in_progress"
        _activity_log(activity, "pilot_started", "El piloto inicio la operacion.")
        db.session.commit()
        flash("Operacion iniciada.", "success")
    return redirect(url_for("core.pilot_activity_detail", activity_id=activity.id))


@web.route("/piloto/operaciones/<int:activity_id>/finalizar", methods=["POST"])
def pilot_finish_activity(activity_id):
    pilot, response = _require_pilot()
    if response:
        return response

    activity = _pilot_activity_query(pilot).filter(OperationalActivity.id == activity_id).first_or_404()
    if activity.status != "cancelled":
        activity.status = "completed"
        activity.completed_at = datetime.utcnow()
        _activity_log(activity, "pilot_completed", "El piloto marco la operacion como finalizada.")
        _sync_activity_billing(activity)
        db.session.commit()
        flash("Operacion finalizada.", "success")
    return redirect(url_for("core.pilot_activity_detail", activity_id=activity.id))


@web.route("/piloto/operaciones/<int:activity_id>/bitacora", methods=["POST"])
def pilot_save_flight_log(activity_id):
    pilot, response = _require_pilot()
    if response:
        return response

    activity = _pilot_activity_query(pilot).filter(OperationalActivity.id == activity_id).first_or_404()
    flight_date = _parse_date((request.form.get("flight_date") or "").strip())
    started_at = _parse_datetime_fields((request.form.get("start_date") or "").strip(), (request.form.get("start_time") or "").strip())
    ended_at = _parse_datetime_fields((request.form.get("end_date") or "").strip(), (request.form.get("end_time") or "").strip())
    if not flight_date or not started_at or not ended_at or ended_at <= started_at:
        flash("Revisa la fecha y las horas reales de vuelo.", "error")
        return redirect(url_for("core.pilot_activity_detail", activity_id=activity.id))

    minutes = int((ended_at - started_at).total_seconds() // 60)
    flight_log = PilotFlightLog.query.filter_by(pilot_id=pilot.id, activity_id=activity.id).first()
    previous_minutes = flight_log.flight_minutes if flight_log else 0
    payload = {
        "pilot": pilot,
        "activity": activity,
        "drone": activity.drone,
        "flight_date": flight_date,
        "started_at": started_at,
        "ended_at": ended_at,
        "flight_minutes": minutes,
        "takeoff_location": (request.form.get("takeoff_location") or "").strip() or activity.place,
        "landing_location": (request.form.get("landing_location") or "").strip() or activity.place,
        "weather": (request.form.get("weather") or "").strip() or None,
        "battery_cycles": request.form.get("battery_cycles", type=int),
        "total_hectares": _parse_optional_decimal(request.form.get("total_hectares")),
        "notes": (request.form.get("notes") or "").strip() or None,
    }
    if flight_log:
        for key, value in payload.items():
            setattr(flight_log, key, value)
    else:
        flight_log = PilotFlightLog(**payload)
        db.session.add(flight_log)

    delta_hours = Decimal(minutes - previous_minutes) / Decimal(60)
    activity.drone.flight_hours = (activity.drone.flight_hours or Decimal("0")) + delta_hours
    if activity.status not in {"cancelled", "completed"}:
        activity.status = "in_progress"
        activity.completed_at = None
    _activity_log(activity, "pilot_log_saved", "El piloto registro bitacora de vuelo.")
    db.session.commit()
    flash("Bitacora guardada correctamente.", "success")
    return redirect(url_for("core.pilot_activity_detail", activity_id=activity.id))


@web.route("/piloto/operaciones/<int:activity_id>/novedad", methods=["POST"])
def pilot_report_issue(activity_id):
    pilot, response = _require_pilot()
    if response:
        return response

    activity = _pilot_activity_query(pilot).filter(OperationalActivity.id == activity_id).first_or_404()
    message = (request.form.get("message") or "").strip()
    if not message:
        flash("Escribe el detalle de la novedad.", "error")
        return redirect(url_for("core.pilot_activity_detail", activity_id=activity.id))
    db.session.add(
        PilotOperationReport(
            pilot=pilot,
            activity=activity,
            report_type=(request.form.get("report_type") or "general").strip(),
            message=message,
        )
    )
    _activity_log(activity, "pilot_reported", "El piloto reporto una novedad.")
    db.session.commit()
    flash("Novedad reportada.", "success")
    return redirect(url_for("core.pilot_activity_detail", activity_id=activity.id))


@web.route("/dashboard/operaciones/ejecuciones")
@login_required
def operation_executions():
    from app.modules.foliage.models import Farm, Lot

    current_user_id = get_jwt_identity()
    current_user = User.query.get(current_user_id)
    organization_ids = [org.id for org in get_clients_for_user(current_user_id)]
    is_platform_admin = bool(current_user and current_user.is_admin())

    today = date.today()
    year = request.args.get("year", default=today.year, type=int)
    month = request.args.get("month", default=today.month, type=int)
    if month < 1:
        month = 12
        year -= 1
    elif month > 12:
        month = 1
        year += 1

    month_anchor = date(year, month, 1)
    previous_month = (month_anchor.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_month = (month_anchor.replace(day=28) + timedelta(days=4)).replace(day=1)
    calendar_start = month_anchor - timedelta(days=month_anchor.weekday())
    calendar_end = calendar_start + timedelta(days=42)
    range_start = datetime.combine(calendar_start, time.min)
    range_end = datetime.combine(calendar_end, time.max)
    now = datetime.utcnow()

    activities_query = OperationalActivity.query.options(
        joinedload(OperationalActivity.pilot),
        joinedload(OperationalActivity.drone),
        joinedload(OperationalActivity.billing_record),
        selectinload(OperationalActivity.logs),
        selectinload(OperationalActivity.flight_logs),
        selectinload(OperationalActivity.pilot_reports),
    ).outerjoin(OperationBillingRecord)
    if not is_platform_admin:
        activities_query = activities_query.filter(
            OperationBillingRecord.organization_id.in_(organization_ids) if organization_ids else false()
        )
    activities = (
        activities_query
        .filter(OperationalActivity.starts_at <= range_end, OperationalActivity.ends_at >= range_start)
        .order_by(OperationalActivity.starts_at.asc())
        .all()
    )

    def activity_progress(activity):
        if activity.status == "cancelled":
            return 0
        if activity.status == "completed" or activity.completed_at:
            return 100
        if activity.status != "in_progress":
            return 0
        total_seconds = max((activity.ends_at - activity.starts_at).total_seconds(), 1)
        elapsed = (now - activity.starts_at).total_seconds()
        return max(1, min(99, int(round((elapsed / total_seconds) * 100))))

    def execution_status(activity, progress):
        has_report = any(getattr(report, "status", "open") == "open" for report in getattr(activity, "pilot_reports", []))
        if activity.status == "cancelled":
            return "cancelled", "Cancelada"
        if has_report and activity.status != "completed":
            return "reported", "Con novedad"
        if activity.status == "completed":
            return "completed", "Finalizada"
        if activity.status == "in_progress":
            return "in_progress", "En proceso"
        if activity.starts_at > now and activity.starts_at <= now + timedelta(hours=24):
            return "soon", "Por iniciar"
        return "scheduled", "Pendiente"

    def fmt_dt(value):
        return value.strftime("%d/%m/%Y %I:%M %p")

    executions = []
    gantt_weeks = []
    for week_index in range(6):
        week_start = calendar_start + timedelta(days=week_index * 7)
        week_end = week_start + timedelta(days=6)
        gantt_weeks.append({
            "index": week_index + 1,
            "start": week_start,
            "end": week_end,
            "label": f"S{week_index + 1}",
            "range": f"{week_start.day:02d}/{week_start.month:02d} - {week_end.day:02d}/{week_end.month:02d}",
            "is_current": week_start <= today <= week_end,
        })
    gantt_week_count = len(gantt_weeks)
    stats = {"total": 0, "running": 0, "scheduled": 0, "completed": 0, "reported": 0}
    total_hectares = Decimal("0")
    total_minutes = 0
    for activity in activities:
        progress = activity_progress(activity)
        status_key, status_label = execution_status(activity, progress)
        logs = sorted(getattr(activity, "logs", []) or [], key=lambda item: item.created_at)
        flight_logs = getattr(activity, "flight_logs", []) or []
        reports = sorted(getattr(activity, "pilot_reports", []) or [], key=lambda item: item.created_at, reverse=True)
        billing_record = getattr(activity, "billing_record", None)
        minutes = sum((log.flight_minutes or 0) for log in flight_logs)
        if not minutes and billing_record and billing_record.operation_hours is not None:
            minutes = int(Decimal(str(billing_record.operation_hours)) * Decimal(60))
        hectares = Decimal("0")
        for log in flight_logs:
            value = getattr(log, "total_hectares", None)
            if value is not None:
                hectares += Decimal(str(value))
        billing_source = ((billing_record.raw_payload or {}).get("source") if billing_record else "") or ""
        if hectares == 0 and billing_record and billing_record.area_hectares is not None and billing_source != "operational_calendar":
            hectares = Decimal(str(billing_record.area_hectares))
        planned_hectares = Decimal(str(activity.area_hectares)) if activity.area_hectares is not None else Decimal("0")
        progress_hectares = hectares
        if planned_hectares > 0:
            hectares_progress = min(Decimal("100"), max(Decimal("0"), (progress_hectares / planned_hectares) * Decimal("100")))
            hectares_progress_label = f"{progress_hectares:.1f}/{planned_hectares:.1f} ha - {hectares_progress:.0f}%"
            hectares_progress_state = "ok" if hectares_progress >= 100 else ("shortfall" if status_key == "completed" else "partial")
        else:
            hectares_progress = Decimal("100") if status_key == "completed" and progress_hectares > 0 else Decimal("0")
            hectares_progress_label = f"{progress_hectares:.1f} ha reportadas" if progress_hectares > 0 else "Sin hectareas reportadas"
            hectares_progress_state = "ok" if progress_hectares > 0 else ("missing" if status_key == "completed" else "empty")
        total_minutes += minutes
        total_hectares += hectares
        if status_key == "in_progress":
            stats["running"] += 1
        elif status_key == "completed":
            stats["completed"] += 1
        elif status_key == "reported":
            stats["reported"] += 1
        else:
            stats["scheduled"] += 1
        stats["total"] += 1
        clip_start = max(activity.starts_at.date(), calendar_start)
        clip_end = min(activity.ends_at.date(), calendar_end - timedelta(days=1))
        operation_days = max((activity.ends_at.date() - activity.starts_at.date()).days + 1, 1)
        gantt_start_week = max(1, min(gantt_week_count, ((clip_start - calendar_start).days // 7) + 1))
        gantt_end_week = max(gantt_start_week, min(gantt_week_count, ((clip_end - calendar_start).days // 7) + 1))
        gantt_week_span = max(gantt_end_week - gantt_start_week + 1, 1)
        execution = {
            "id": activity.id,
            "title": activity.title,
            "operation_type": activity.operation_type,
            "place": activity.place,
            "client_project": ((billing_record.raw_payload or {}).get("final_client") if billing_record else None) or "Sin cliente",
            "organization_id": billing_record.organization_id if billing_record else None,
            "lot_id": ((billing_record.raw_payload or {}).get("lot_id") if billing_record else None),
            "pilot": activity.pilot.full_name if activity.pilot else "Sin piloto",
            "drone": f"{activity.drone.brand} {activity.drone.model}" if activity.drone else "Sin dron",
            "starts_at": activity.starts_at,
            "ends_at": activity.ends_at,
            "starts_label": fmt_dt(activity.starts_at),
            "ends_label": fmt_dt(activity.ends_at),
            "progress": progress,
            "status": status_key,
            "status_label": status_label,
            "duration_hours": round((activity.duration_minutes or 0) / 60, 1),
            "real_hours": round(minutes / 60, 1),
            "hectares": float(hectares),
            "planned_hectares": float(planned_hectares),
            "hectares_progress": float(round(hectares_progress, 1)),
            "hectares_progress_state": hectares_progress_state,
            "hectares_progress_label": hectares_progress_label,
            "report_count": len(reports),
            "log_count": len(logs),
            "latest_note": reports[0].message if reports else (logs[-1].message if logs else ((billing_record.observations if billing_record else None) or "Sin novedades registradas")),
            "operation_days": operation_days,
            "gantt_start_week": gantt_start_week,
            "gantt_end_week": gantt_end_week,
            "gantt_week_span": gantt_week_span,
            "gantt_left": round(((gantt_start_week - 1) / gantt_week_count) * 100, 4),
            "gantt_width": round((gantt_week_span / gantt_week_count) * 100, 4),
        }
        execution["payload"] = {
            key: value
            for key, value in execution.items()
            if key not in {"starts_at", "ends_at", "payload"}
        }
        executions.append(execution)

    days = []
    for offset in range(42):
        current_day = calendar_start + timedelta(days=offset)
        day_start = datetime.combine(current_day, time.min)
        day_end = datetime.combine(current_day, time.max)
        day_items = [item for item in executions if item["starts_at"] <= day_end and item["ends_at"] >= day_start]
        days.append(
            {
                "date": current_day,
                "number": current_day.day,
                "in_month": current_day.month == month_anchor.month,
                "is_today": current_day == today,
                "executions": day_items,
            }
        )

    month_names = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    catalog_query = Organization.query.filter(Organization.active.is_(True))
    if not is_platform_admin:
        catalog_query = catalog_query.filter(Organization.id.in_(organization_ids) if organization_ids else false())
    catalog_organizations = catalog_query.order_by(Organization.name.asc()).all()
    catalog_ids = [item.id for item in catalog_organizations]
    catalog_farms = Farm.query.filter(Farm.org_id.in_(catalog_ids)).order_by(Farm.name.asc()).all() if catalog_ids else []
    catalog_lots = Lot.query.join(Farm).filter(Farm.org_id.in_(catalog_ids), Lot.active.is_(True)).order_by(Farm.name.asc(), Lot.name.asc()).all() if catalog_ids else []
    execution_catalog = {
        "organizations": [{"id": item.id, "name": item.name} for item in catalog_organizations],
        "farms": [{"id": item.id, "organization_id": item.org_id, "name": item.name} for item in catalog_farms],
        "lots": [{"id": item.id, "farm_id": item.farm_id, "name": item.name} for item in catalog_lots],
    }
    context = {
        "dashboard": True,
        "title": "Ejecuciones",
        "description": "Consulta el avance operativo de las misiones programadas.",
        "author": "TecnoAgro",
        "site_title": "Operaciones",
        "page_title": "Ejecuciones",
        "data_menu": get_dashboard_menu(),
        "month_title": f"{month_names[month_anchor.month - 1].capitalize()} {month_anchor.year}",
        "today_date": today,
        "previous_month": previous_month,
        "next_month": next_month,
        "calendar_days": days,
        "gantt_weeks": gantt_weeks,
        "executions": executions,
        "stats": stats,
        "total_real_hours": round(total_minutes / 60, 1),
        "total_hectares": float(total_hectares),
        "execution_catalog": execution_catalog,
    }
    return (
        render_template(
            "dashboard/operation_executions.j2",
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/operaciones/ejecuciones/<int:activity_id>/asociacion", methods=["POST"])
@login_required
def operation_executions_update_association(activity_id):
    from app.modules.foliage.models import Lot

    activity = OperationalActivity.query.get_or_404(activity_id)
    current_user_id = get_jwt_identity()
    current_user = User.query.get(current_user_id)
    organization_ids = [org.id for org in get_clients_for_user(current_user_id)]
    is_platform_admin = bool(current_user and current_user.is_admin())
    organization = Organization.query.get(request.form.get("organization_id", type=int))
    lot = Lot.query.get(request.form.get("lot_id", type=int))
    farm = lot.farm if lot else None
    if not organization or not farm or not lot:
        return jsonify({"success": False, "message": "Selecciona un cliente y un potrero validos."}), 400
    if farm.org_id != organization.id:
        return jsonify({"success": False, "message": "El potrero no pertenece al cliente seleccionado."}), 400
    if not is_platform_admin and organization.id not in organization_ids:
        return jsonify({"success": False, "message": "No tienes acceso a este cliente."}), 403

    record = getattr(activity, "billing_record", None)
    if not record:
        record = OperationBillingRecord(activity=activity)
        db.session.add(record)
    unit_price = record.unit_price
    if unit_price is None:
        unit_price = _parse_optional_decimal(str((organization.profile_data or {}).get("billing_unit_price") or ""))
    area = record.area_hectares or activity.area_hectares
    if area is None and lot.area is not None:
        area = Decimal(str(lot.area))
    record.organization_id = organization.id
    record.farm_name = farm.name
    record.paddock_name = lot.name
    record.area_hectares = area
    record.unit_price = unit_price
    record.invoice_total = Decimal(str(area)) * unit_price if area is not None and unit_price is not None else None
    record.raw_payload = {**(record.raw_payload or {}), "final_client": organization.name, "organization_id": organization.id, "farm_id": farm.id, "lot_id": lot.id, "association_updated_by": current_user_id}
    activity.client_project = organization.name
    activity.farm_name = farm.name
    activity.lot_code = lot.name
    if activity.area_hectares is None and area is not None:
        activity.area_hectares = area
    db.session.commit()
    return jsonify({"success": True, "message": "Cliente y potrero asociados correctamente."})

@web.route("/dashboard/mantenimiento/bitacoras")
@login_required
def maintenance_logs():
    context = {
        "dashboard": True,
        "title": "Bitacoras",
        "description": "Consulta y registra bitacoras de mantenimiento.",
        "author": "TecnoAgro",
        "site_title": "Mantenimiento",
        "page_title": "Bitacoras",
        "data_menu": get_dashboard_menu(),
    }
    return (
        render_template(
            "dashboard/maintenance_logs.j2",
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/mantenimiento/horas-vuelo")
@login_required
def flight_hours():
    context = {
        "dashboard": True,
        "title": "Horas de vuelo",
        "description": "Consulta y registra horas de vuelo de equipos.",
        "author": "TecnoAgro",
        "site_title": "Mantenimiento",
        "page_title": "Horas de vuelo",
        "data_menu": get_dashboard_menu(),
    }
    return (
        render_template(
            "dashboard/flight_hours.j2",
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/mantenimiento/drones", methods=["GET", "POST"])
@login_required
def maintenance_drones():
    if request.method == "POST":
        serial_number = (request.form.get("serial_number") or "").strip()
        brand = (request.form.get("brand") or "").strip()
        model = (request.form.get("model") or "").strip()
        flight_hours_raw = (request.form.get("flight_hours") or "0").strip()

        if not serial_number or not brand or not model:
            flash("Completa numero de serie, marca y modelo.", "error")
            return redirect(url_for("core.maintenance_drones"))

        try:
            flight_hours = round(float(flight_hours_raw.replace(",", ".")), 1)
        except ValueError:
            flash("Las horas de vuelo deben ser un numero valido.", "error")
            return redirect(url_for("core.maintenance_drones"))

        if flight_hours < 0:
            flash("Las horas de vuelo no pueden ser negativas.", "error")
            return redirect(url_for("core.maintenance_drones"))

        drone = MaintenanceDrone(
            serial_number=serial_number,
            brand=brand,
            model=model,
            flight_hours=flight_hours,
            status=(request.form.get("status") or "Aeronavegable").strip() or "Aeronavegable",
        )
        db.session.add(drone)
        try:
            db.session.commit()
            flash("Equipo registrado correctamente.", "success")
            return redirect(url_for("core.maintenance_drones"))
        except IntegrityError:
            db.session.rollback()
            flash("Ya existe un drone con ese numero de serie.", "error")

        return redirect(url_for("core.maintenance_drones"))

    drones = MaintenanceDrone.query.order_by(MaintenanceDrone.created_at.desc()).all()
    total_hours = sum(float(drone.flight_hours or 0) for drone in drones)
    active_count = sum(1 for drone in drones if drone.status == "Aeronavegable")
    context = {
        "dashboard": True,
        "title": "Drones",
        "description": "Consulta y registra drones para mantenimiento.",
        "author": "TecnoAgro",
        "site_title": "Mantenimiento",
        "page_title": "Drones",
        "data_menu": get_dashboard_menu(),
        "suppress_base_flashes": True,
        "drones": drones,
        "total_hours": total_hours,
        "active_count": active_count,
    }
    return (
        render_template(
            "dashboard/maintenance_drones.j2",
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/mantenimiento/drones/<int:drone_id>/editar", methods=["POST"])
@login_required
def maintenance_drones_update(drone_id):
    drone = MaintenanceDrone.query.get_or_404(drone_id)
    serial_number = (request.form.get("serial_number") or "").strip()
    brand = (request.form.get("brand") or "").strip()
    model = (request.form.get("model") or "").strip()
    status = (request.form.get("status") or "Aeronavegable").strip()
    flight_hours_raw = (request.form.get("flight_hours") or "0").strip()

    if not serial_number or not brand or not model:
        flash("Completa numero de serie, marca y modelo.", "error")
        return redirect(url_for("core.maintenance_drones"))

    try:
        flight_hours = round(float(flight_hours_raw.replace(",", ".")), 1)
    except ValueError:
        flash("Las horas de vuelo deben ser un numero valido.", "error")
        return redirect(url_for("core.maintenance_drones"))

    if flight_hours < 0:
        flash("Las horas de vuelo no pueden ser negativas.", "error")
        return redirect(url_for("core.maintenance_drones"))

    drone.serial_number = serial_number
    drone.brand = brand
    drone.model = model
    drone.flight_hours = flight_hours
    drone.status = status or "Aeronavegable"
    try:
        db.session.commit()
        flash("Drone actualizado correctamente.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("Ya existe un drone con ese numero de serie.", "error")
    return redirect(url_for("core.maintenance_drones"))


@web.route("/dashboard/mantenimiento/drones/<int:drone_id>/eliminar", methods=["POST"])
@login_required
def maintenance_drones_delete(drone_id):
    drone = MaintenanceDrone.query.get_or_404(drone_id)
    try:
        db.session.delete(drone)
        db.session.commit()
        flash("Drone eliminado correctamente.", "success")
    except Exception:
        db.session.rollback()
        flash("No se puede eliminar este drone porque tiene operaciones o registros asociados.", "error")
    return redirect(url_for("core.maintenance_drones"))


@web.route("/dashboard/logistica/shopfy")
@login_required
def logistics_shopfy():
    context = {
        "dashboard": True,
        "title": "Shopfy",
        "description": "Consulta y gestiona operaciones logisticas de Shopfy.",
        "author": "TecnoAgro",
        "site_title": "Logistica",
        "page_title": "Shopfy",
        "data_menu": get_dashboard_menu(),
    }
    return (
        render_template(
            "dashboard/logistics_shopfy.j2",
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/logistica/garantias")
@login_required
def warranty_management():
    context = {
        "dashboard": True,
        "title": "Manejo de garantias",
        "description": "Consulta y gestiona procesos de garantia.",
        "author": "TecnoAgro",
        "site_title": "Logistica",
        "page_title": "Manejo de garantias",
        "data_menu": get_dashboard_menu(),
    }
    return (
        render_template(
            "dashboard/warranty_management.j2",
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/logistica/reparaciones-pagas")
@login_required
def paid_repairs():
    context = {
        "dashboard": True,
        "title": "Reparaciones pagas",
        "description": "Consulta y gestiona reparaciones pagas.",
        "author": "TecnoAgro",
        "site_title": "Logistica",
        "page_title": "Reparaciones pagas",
        "data_menu": get_dashboard_menu(),
    }
    return (
        render_template(
            "dashboard/paid_repairs.j2",
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/operacion-realizada/facturacion")
@login_required
def completed_operation_billing():
    from app.modules.foliage.models import Farm, Lot

    current_user_id = get_jwt_identity()
    current_user = User.query.get(current_user_id)
    organization_ids = [org.id for org in get_clients_for_user(current_user_id)]
    is_platform_admin = bool(current_user and current_user.is_admin())


    filters = {
        "finca": (request.args.get("finca") or "").strip(),
        "cliente": (request.args.get("cliente") or "").strip(),
        "piloto": (request.args.get("piloto") or "").strip(),
        "mes": (request.args.get("mes") or "").strip(),
        "factura": (request.args.get("factura") or "").strip(),
        "q": (request.args.get("q") or "").strip(),
    }

    query = OperationBillingRecord.query.options(
        joinedload(OperationBillingRecord.activity).joinedload(OperationalActivity.pilot),
        joinedload(OperationBillingRecord.organization),
    )

    if not is_platform_admin:
        query = query.filter(
            OperationBillingRecord.organization_id.in_(organization_ids) if organization_ids else false()
        )

    if filters["finca"]:
        query = query.filter(OperationBillingRecord.farm_name == filters["finca"])
    if filters["piloto"]:
        query = query.filter(OperationBillingRecord.pilot_name == filters["piloto"])
    if filters["mes"]:
        query = query.filter(OperationBillingRecord.billing_month == filters["mes"])
    if filters["factura"] == "pendientes":
        query = query.filter(or_(OperationBillingRecord.invoice_number.is_(None), OperationBillingRecord.invoice_number == ""))
    elif filters["factura"] == "facturadas":
        query = query.filter(OperationBillingRecord.invoice_number.isnot(None), OperationBillingRecord.invoice_number != "")
    if filters["q"]:
        search = f"%{filters['q']}%"
        query = query.filter(
            or_(
                OperationBillingRecord.farm_name.ilike(search),
                OperationBillingRecord.paddock_name.ilike(search),
                OperationBillingRecord.invoice_number.ilike(search),
                OperationBillingRecord.observations.ilike(search),
                OperationBillingRecord.organization.has(Organization.name.ilike(search)),
            )
        )

    records = (
        query.order_by(OperationBillingRecord.executed_date.desc(), OperationBillingRecord.source_item.desc())
        .all()
    )
    if filters["cliente"]:
        records = [
            record for record in records
            if (
                (record.raw_payload or {}).get("final_client", "") == filters["cliente"]
                or (record.organization and record.organization.name == filters["cliente"])
            )
        ]

    total_invoice = sum((record.invoice_total or Decimal("0")) for record in records)
    total_area = sum((record.area_hectares or Decimal("0")) for record in records)
    pending_records = [record for record in records if not record.invoice_number]
    invoices = {record.invoice_number for record in records if record.invoice_number}
    options_query = OperationBillingRecord.query.options(joinedload(OperationBillingRecord.organization))
    if not is_platform_admin:
        options_query = options_query.filter(
            OperationBillingRecord.organization_id.in_(organization_ids) if organization_ids else false()
        )
    if filters["factura"] == "pendientes":
        options_query = options_query.filter(
            or_(OperationBillingRecord.invoice_number.is_(None), OperationBillingRecord.invoice_number == "")
        )
    elif filters["factura"] == "facturadas":
        options_query = options_query.filter(
            OperationBillingRecord.invoice_number.isnot(None),
            OperationBillingRecord.invoice_number != "",
        )
    option_records = options_query.all()
    filter_options = {
        "farms": sorted({record.farm_name for record in option_records if record.farm_name}),
        "pilots": sorted({record.pilot_name for record in option_records if record.pilot_name}),
        "months": sorted({record.billing_month for record in option_records if record.billing_month}),
        "clients": sorted({
            (record.raw_payload or {}).get("final_client") or (record.organization.name if record.organization else None)
            for record in option_records
            if (record.raw_payload or {}).get("final_client") or record.organization
        }),
    }
    catalog_query = Organization.query.filter(Organization.active.is_(True))
    if not is_platform_admin:
        catalog_query = catalog_query.filter(Organization.id.in_(organization_ids) if organization_ids else false())
    catalog_organizations = catalog_query.order_by(Organization.name.asc()).all()
    catalog_ids = [item.id for item in catalog_organizations]
    catalog_farms = Farm.query.filter(Farm.org_id.in_(catalog_ids)).order_by(Farm.name.asc()).all() if catalog_ids else []
    catalog_lots = Lot.query.join(Farm).filter(
        Farm.org_id.in_(catalog_ids), Lot.active.is_(True)
    ).order_by(Farm.name.asc(), Lot.name.asc()).all() if catalog_ids else []
    billing_catalog = {
        "organizations": [{"id": item.id, "name": item.name} for item in catalog_organizations],
        "farms": [{"id": item.id, "organization_id": item.org_id, "name": item.name} for item in catalog_farms],
        "lots": [
            {"id": item.id, "farm_id": item.farm_id, "name": item.name, "area": item.area}
            for item in catalog_lots
        ],
    }

    context = {
        "dashboard": True,
        "title": "Facturacion",
        "description": "Consulta y gestiona la facturacion de operaciones realizadas.",
        "author": "TecnoAgro",
        "site_title": "Operacion realizada",
        "page_title": "Facturacion",
        "data_menu": get_dashboard_menu(),
        "records": records,
        "filters": filters,
        "filter_options": filter_options,
        "billing_catalog": billing_catalog,
        "stats": {
            "total_records": len(records),
            "pending_records": len(pending_records),
            "invoice_count": len(invoices),
            "total_invoice": total_invoice,
            "total_area": total_area,
        },
    }
    return (
        render_template(
            "dashboard/completed_operation_billing.j2",
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/operacion-realizada/facturacion/factura-consolidada")
@login_required
def completed_operation_billing_consolidated_invoice():
    current_user_id = get_jwt_identity()
    current_user = User.query.get(current_user_id)
    organization_ids = [org.id for org in get_clients_for_user(current_user_id)]
    is_platform_admin = bool(current_user and current_user.is_admin())
    filters = {
        "finca": (request.args.get("finca") or "").strip(),
        "cliente": (request.args.get("cliente") or "").strip(),
        "piloto": (request.args.get("piloto") or "").strip(),
        "mes": (request.args.get("mes") or "").strip(),
    }
    if not filters["cliente"]:
        flash("Selecciona un cliente para generar la factura consolidada.", "error")
        return redirect(url_for("core.completed_operation_billing", factura="pendientes"))

    query = OperationBillingRecord.query.options(
        joinedload(OperationBillingRecord.organization),
        joinedload(OperationBillingRecord.activity).joinedload(OperationalActivity.pilot),
    ).filter(
        or_(OperationBillingRecord.invoice_number.is_(None), OperationBillingRecord.invoice_number == "")
    )
    if not is_platform_admin:
        query = query.filter(
            OperationBillingRecord.organization_id.in_(organization_ids) if organization_ids else false()
        )
    if filters["finca"]:
        query = query.filter(OperationBillingRecord.farm_name == filters["finca"])
    if filters["piloto"]:
        query = query.filter(OperationBillingRecord.pilot_name == filters["piloto"])
    if filters["mes"]:
        query = query.filter(OperationBillingRecord.billing_month == filters["mes"])

    records = query.order_by(OperationBillingRecord.executed_date.asc(), OperationBillingRecord.source_item.asc()).all()
    records = [
        record for record in records
        if (
            (record.raw_payload or {}).get("final_client", "") == filters["cliente"]
            or (record.organization and record.organization.name == filters["cliente"])
        )
    ]
    if not records:
        flash("No hay operaciones pendientes para los filtros seleccionados.", "error")
        return redirect(url_for("core.completed_operation_billing", factura="pendientes", **filters))

    total_area = sum((Decimal(str(record.area_hectares or 0)) for record in records), Decimal("0"))
    total_value = sum((Decimal(str(record.invoice_total or 0)) for record in records), Decimal("0"))
    pilots = {}
    for record in records:
        pilot_name = record.pilot_name or "Sin piloto"
        pilot = pilots.setdefault(pilot_name, {"name": pilot_name, "operations": 0, "area": Decimal("0"), "total": Decimal("0")})
        pilot["operations"] += 1
        pilot["area"] += Decimal(str(record.area_hectares or 0))
        pilot["total"] += Decimal(str(record.invoice_total or 0))

    organization = next((record.organization for record in records if record.organization), None)
    reference = f"BORRADOR-{datetime.now().strftime('%Y%m%d-%H%M')}"
    return render_template(
        "dashboard/consolidated_operation_invoice.j2",
        records=records,
        filters=filters,
        organization=organization,
        pilots=list(pilots.values()),
        total_area=total_area,
        total_value=total_value,
        reference=reference,
        generated_at=datetime.now(),
    )

@web.route("/dashboard/operacion-realizada/facturacion/<int:record_id>/asociacion", methods=["POST"])
@login_required
def completed_operation_billing_update_association(record_id):
    from app.modules.foliage.models import Farm, Lot

    record = OperationBillingRecord.query.get_or_404(record_id)
    current_user_id = get_jwt_identity()
    current_user = User.query.get(current_user_id)
    organization_ids = [org.id for org in get_clients_for_user(current_user_id)]
    is_platform_admin = bool(current_user and current_user.is_admin())
    organization = Organization.query.get(request.form.get("organization_id", type=int))
    if not organization:
        return jsonify({"success": False, "message": "Selecciona un cliente valido."}), 400
    if not is_platform_admin and organization.id not in organization_ids:
        return jsonify({"success": False, "message": "No tienes acceso a este cliente."}), 403
    if not is_platform_admin and record.organization_id is not None and record.organization_id not in organization_ids:
        return jsonify({"success": False, "message": "No tienes acceso a este registro."}), 403

    farm = Farm.query.get(request.form.get("farm_id", type=int))
    farm_name = (request.form.get("farm_name") or "").strip()
    if farm and farm.org_id != organization.id:
        return jsonify({"success": False, "message": "La finca no pertenece al cliente seleccionado."}), 400
    if not farm and farm_name:
        farm = Farm.query.filter(
            Farm.org_id == organization.id,
            func.lower(Farm.name) == farm_name.lower(),
        ).first()
    if not farm and farm_name:
        farm = Farm(name=farm_name, org_id=organization.id)
        db.session.add(farm)
        db.session.flush()

    lot = Lot.query.get(request.form.get("lot_id", type=int))
    lot_name = (request.form.get("lot_name") or "").strip()
    if lot and (not farm or lot.farm_id != farm.id):
        db.session.rollback()
        return jsonify({"success": False, "message": "El potrero no pertenece a la finca seleccionada."}), 400
    if not lot and lot_name and not farm:
        db.session.rollback()
        return jsonify({"success": False, "message": "Selecciona o crea una finca para guardar el potrero nuevo."}), 400
    if not lot and lot_name and farm:
        lot = Lot.query.filter(
            Lot.farm_id == farm.id,
            func.lower(Lot.name) == lot_name.lower(),
        ).first()
    if not lot and lot_name:
        lot_area = _parse_optional_decimal(request.form.get("lot_area"))
        if lot_area is None or lot_area < 0:
            db.session.rollback()
            return jsonify({"success": False, "message": "Escribe el area en hectareas del nuevo potrero."}), 400
        lot = Lot(name=lot_name, area=float(lot_area), farm_id=farm.id, active=True)
        db.session.add(lot)
        db.session.flush()

    unit_price = record.unit_price
    if unit_price is None:
        unit_price = _parse_optional_decimal(str((organization.profile_data or {}).get("billing_unit_price") or ""))
    area = record.area_hectares
    if area is None and lot and lot.area is not None:
        area = Decimal(str(lot.area))
    record.organization_id = organization.id
    if farm:
        record.farm_name = farm.name
    if lot:
        record.paddock_name = lot.name
    record.area_hectares = area
    record.unit_price = unit_price
    record.invoice_total = area * unit_price if area is not None and unit_price is not None else None
    record.raw_payload = {
        **(record.raw_payload or {}),
        "final_client": organization.name,
        "organization_id": organization.id,
        "farm_id": farm.id if farm else None,
        "lot_id": lot.id if lot else None,
        "association_updated_by": current_user_id,
    }
    if record.activity:
        record.activity.client_project = organization.name
        if farm:
            record.activity.farm_name = farm.name
        if lot:
            record.activity.lot_code = lot.name
        if record.activity.area_hectares is None and area is not None:
            record.activity.area_hectares = area
    db.session.commit()
    return jsonify({"success": True, "message": "Datos de facturacion asociados correctamente."})
@web.route("/dashboard/operacion-realizada/facturacion/<int:record_id>/numero", methods=["POST"])
@login_required
def completed_operation_billing_update_invoice(record_id):
    record = OperationBillingRecord.query.get_or_404(record_id)
    current_user_id = get_jwt_identity()
    current_user = User.query.get(current_user_id)
    organization_ids = [org.id for org in get_clients_for_user(current_user_id)]
    is_platform_admin = bool(current_user and current_user.is_admin())

    if not is_platform_admin and record.organization_id not in organization_ids:
        return jsonify({"success": False, "message": "No tienes acceso a este registro."}), 403

    invoice_number = (request.form.get("invoice_number") or "").strip()
    if not invoice_number:
        flash("Escribe el numero de factura.", "error")
        return redirect(url_for("core.completed_operation_billing"))
    if len(invoice_number) > 80:
        flash("El numero de factura no puede superar 80 caracteres.", "error")
        return redirect(url_for("core.completed_operation_billing"))

    record.invoice_number = invoice_number
    record.raw_payload = {
        **(record.raw_payload or {}),
        "invoice_status": "invoiced",
        "invoice_number_updated_by": current_user_id,
    }
    db.session.commit()
    flash(f"Factura {invoice_number} guardada correctamente.", "success")
    return redirect(url_for("core.completed_operation_billing"))

@web.route("/dashboard/operacion-realizada/cronograma")
@login_required
def completed_operation_schedule():
    context = {
        "dashboard": True,
        "title": "Cronograma",
        "description": "Consulta el cronograma de operaciones realizadas.",
        "author": "TecnoAgro",
        "site_title": "Operación realizada",
        "page_title": "Cronograma",
        "data_menu": get_dashboard_menu(),
    }
    return (
        render_template(
            "dashboard/completed_operation_schedule.j2",
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/operacion-realizada/facturas")
@login_required
def completed_operation_invoices():
    context = {
        "dashboard": True,
        "title": "Facturas",
        "description": "Consulta y gestiona facturas de operaciones realizadas.",
        "author": "TecnoAgro",
        "site_title": "Operación realizada",
        "page_title": "Facturas",
        "data_menu": get_dashboard_menu(),
    }
    return (
        render_template(
            "dashboard/completed_operation_invoices.j2",
            **context,
            request=request,
        ),
        200,
    )

@web.route("/dashboard/marketing/programacion-demostraciones")
@login_required
def marketing_demo_schedule():
    context = {
        "dashboard": True,
        "title": "Programación de demostraciones",
        "description": "Consulta y gestiona demostraciones programadas.",
        "author": "TecnoAgro",
        "site_title": "Marketing",
        "page_title": "Programación de demostraciones",
        "data_menu": get_dashboard_menu(),
    }
    return (
        render_template(
            "dashboard/marketing_demo_schedule.j2",
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/marketing/venta-drones")
@login_required
def marketing_drone_sales():
    context = {
        "dashboard": True,
        "title": "Venta de drones",
        "description": "Consulta y gestiona oportunidades de venta de drones.",
        "author": "TecnoAgro",
        "site_title": "Marketing",
        "page_title": "Venta de drones",
        "data_menu": get_dashboard_menu(),
    }
    return (
        render_template(
            "dashboard/marketing_drone_sales.j2",
            **context,
            request=request,
        ),
        200,
    )

@web.route("/dashboard/capacitaciones/dji-academy")
@login_required
def training_dji_academy():
    context = {
        "dashboard": True,
        "title": "Dji academy",
        "description": "Consulta y gestiona contenidos de Dji academy.",
        "author": "TecnoAgro",
        "site_title": "Capacitaciones",
        "page_title": "Dji academy",
        "data_menu": get_dashboard_menu(),
    }
    return (
        render_template(
            "dashboard/training_dji_academy.j2",
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/capacitaciones/videos")
@login_required
def training_videos():
    context = {
        "dashboard": True,
        "title": "Videos de capacitación",
        "description": "Consulta y gestiona videos de capacitación.",
        "author": "TecnoAgro",
        "site_title": "Capacitaciones",
        "page_title": "Videos de capacitación",
        "data_menu": get_dashboard_menu(),
    }
    return (
        render_template(
            "dashboard/training_videos.j2",
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/capacitaciones/registros")
@login_required
def training_records():
    context = {
        "dashboard": True,
        "title": "Registros",
        "description": "Consulta y gestiona registros de capacitación.",
        "author": "TecnoAgro",
        "site_title": "Capacitaciones",
        "page_title": "Registros",
        "data_menu": get_dashboard_menu(),
    }
    return (
        render_template(
            "dashboard/training_records.j2",
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/capacitaciones/certificacion")
@login_required
def training_certification():
    context = {
        "dashboard": True,
        "title": "Certificación DJI y Tecnovant",
        "description": "Consulta y gestiona certificaciones DJI y Tecnovant.",
        "author": "TecnoAgro",
        "site_title": "Capacitaciones",
        "page_title": "Certificación DJI y Tecnovant",
        "data_menu": get_dashboard_menu(),
    }
    return (
        render_template(
            "dashboard/training_certification.j2",
            **context,
            request=request,
        ),
        200,
    )

@web.route("/dashboard/certificaciones-uaeac/explotadores-uas")
@login_required
def uaeac_uas_operators():
    context = {
        "dashboard": True,
        "title": "Explotadores UAS",
        "description": "Consulta y gestiona certificaciones UAEAC para explotadores UAS.",
        "author": "TecnoAgro",
        "site_title": "Certificaciones UAEAC",
        "page_title": "Explotadores UAS",
        "data_menu": get_dashboard_menu(),
    }
    return (
        render_template(
            "dashboard/uaeac_uas_operators.j2",
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/certificaciones-uaeac/pilotos-uas")
@login_required
def uaeac_uas_pilots():
    context = {
        "dashboard": True,
        "title": "Pilotos UAS",
        "description": "Consulta y gestiona certificaciones UAEAC para pilotos UAS.",
        "author": "TecnoAgro",
        "site_title": "Certificaciones UAEAC",
        "page_title": "Pilotos UAS",
        "data_menu": get_dashboard_menu(),
    }
    return (
        render_template(
            "dashboard/uaeac_uas_pilots.j2",
            **context,
            request=request,
        ),
        200,
    )


@web.route("/dashboard/certificaciones-uaeac/dji-academy")
@login_required
def uaeac_dji_academy():
    context = {
        "dashboard": True,
        "title": "DJI Academy",
        "description": "Consulta y gestiona certificaciones UAEAC asociadas a DJI Academy.",
        "author": "TecnoAgro",
        "site_title": "Certificaciones UAEAC",
        "page_title": "DJI Academy",
        "data_menu": get_dashboard_menu(),
    }
    return (
        render_template(
            "dashboard/uaeac_dji_academy.j2",
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
    org_dict = {"Seleccione un cliente": ""}
    org_dict.update({org.name: org.id for org in assigned_org})
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
    active_clients = sum(1 for item in items if item.get("active"))
    visible_org_ids = [item.get("id") for item in items if item.get("id") is not None]
    total_area, total_invoice, invoice_count = db.session.query(
        func.coalesce(func.sum(OperationBillingRecord.area_hectares), 0),
        func.coalesce(func.sum(OperationBillingRecord.invoice_total), 0),
        func.count(func.distinct(OperationBillingRecord.invoice_number)),
    ).filter(
        OperationBillingRecord.organization_id.in_(visible_org_ids) if visible_org_ids else false(),
        OperationBillingRecord.invoice_number.isnot(None),
        OperationBillingRecord.invoice_number != "",
    ).one()
    clients_with_billing = db.session.query(
        func.count(func.distinct(OperationBillingRecord.organization_id))
    ).filter(
        OperationBillingRecord.organization_id.in_(visible_org_ids) if visible_org_ids else false()
    ).scalar() or 0
    crud_metric_cards = [
        {
            "label": "Clientes",
            "value": len(items),
            "description": f"{active_clients} activos",
            "icon": "fas fa-users",
            "icon_bg": "bg-emerald-100 dark:bg-emerald-900/40",
            "icon_text": "text-emerald-700 dark:text-emerald-300",
        },
        {
            "label": "Con facturación",
            "value": clients_with_billing,
            "description": f"{invoice_count} facturas",
            "icon": "fas fa-file-invoice",
            "icon_bg": "bg-sky-100 dark:bg-sky-900/40",
            "icon_text": "text-sky-700 dark:text-sky-300",
        },
        {
            "label": "Área",
            "value": f"{float(total_area or 0):,.2f} ha",
            "description": "Hectáreas facturadas",
            "icon": "fas fa-seedling",
            "icon_bg": "bg-cyan-100 dark:bg-cyan-900/40",
            "icon_text": "text-cyan-700 dark:text-cyan-300",
        },
        {
            "label": "Total",
            "value": "$ {:,.0f}".format(float(total_invoice or 0)),
            "description": "Valor facturado",
            "icon": "fas fa-dollar-sign",
            "icon_bg": "bg-amber-100 dark:bg-amber-900/40",
            "icon_text": "text-amber-700 dark:text-amber-300",
            "value_class": "text-emerald-600 dark:text-emerald-400",
        },
    ]
    reseller_dict = {}
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
            crud_metric_cards=crud_metric_cards,
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
