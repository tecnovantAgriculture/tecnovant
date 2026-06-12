"""Define REST API routes for the core module."""

# Third party imports
from flask import Response, jsonify
from flask_jwt_extended import jwt_required, unset_jwt_cookies
from sqlalchemy.orm import joinedload

# Local application imports
from app.helpers.csv_handler import CsvHandler

from . import core_api as api
from .controller import (
    ChangePasswordView,
    ForgotPasswordRequestView,
    LoginView,
    OrgView,
    ProfileView,
    RefreshView,
    ResetPasswordSubmitView,
    UserView,
    login_required,
)
from .models import Organization, User

#############################################
# Set up the API routes for the core module #
#############################################

####################################
# Login, logout and refresh routes #
####################################
api.add_url_rule("/login", view_func=LoginView.as_view("login"), methods=["POST"])


@api.route("/logout")
@login_required
def logout():
    """Log out the current user.

    :status 200: Successful logout
    """
    response = jsonify({"msg": "Logout successful"})
    unset_jwt_cookies(response)
    return response, 200


api.add_url_rule("/refresh", view_func=RefreshView.as_view("refresh"), methods=["POST"])

forgot_password_request_view = ForgotPasswordRequestView.as_view(
    "forgot_password_request"
)
api.add_url_rule(
    "/forgot-password-request", view_func=forgot_password_request_view, methods=["POST"]
)

reset_password_submit_view = ResetPasswordSubmitView.as_view("reset_password_submit")
api.add_url_rule(
    "/reset-password-submit/<token>",
    view_func=reset_password_submit_view,
    methods=["POST"],
)

################################
# Endpoints for the User model #
################################
user_view = UserView.as_view("user_view")

api.add_url_rule("/users/", view_func=user_view, methods=["GET", "POST", "DELETE"])
api.add_url_rule(
    "/users/<string:user_id>", view_func=user_view, methods=["GET", "PUT", "DELETE"]
)

########################################
# Endpoints for the Organization model #
########################################

org_view = OrgView.as_view("org_view")
api.add_url_rule("/org/", view_func=org_view, methods=["GET", "POST", "DELETE"])
api.add_url_rule(
    "/org/<int:org_id>", view_func=org_view, methods=["GET", "PUT", "DELETE"]
)


profile_view = ProfileView.as_view("profile_view")
api.add_url_rule("/profile", view_func=profile_view, methods=["GET", "PUT"])

change_password_view = ChangePasswordView.as_view("change_password_view")
api.add_url_rule(
    "/profile/change-password", view_func=change_password_view, methods=["POST"]
)


# ---------------------------------------------------------------------------
# CSV download endpoints
# ---------------------------------------------------------------------------


@api.route("/users/csv/download")
@jwt_required()
def download_users_csv():
    """Download CSV of all users with organization info."""
    handler = CsvHandler()
    users = User.query.order_by(User.id).all()

    rows = []
    for user in users:
        org_names = ", ".join(o.name for o in user.organizations.all())
        rows.append(
            {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "email": user.email,
                "role": user.role.value if user.role else "",
                "organization": org_names,
                "active": "Sí" if user.active else "No",
                "created_at": str(user.created_at),
                "updated_at": str(user.updated_at),
            }
        )

    csv_data = handler.export_to_csv(rows)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"},
    )


@api.route("/clients/csv/download")
@jwt_required()
def download_clients_csv():
    """Download CSV of all clients/organizations."""
    handler = CsvHandler()
    orgs = (
        Organization.query.options(joinedload(Organization.reseller_package))
        .order_by(Organization.id)
        .all()
    )

    rows = []
    for org in orgs:
        reseller_name = ""
        if org.reseller_package and org.reseller_package.reseller_id:
            reseller_user = User.query.get(org.reseller_package.reseller_id)
            reseller_name = reseller_user.username if reseller_user else ""

        rows.append(
            {
                "id": org.id,
                "name": org.name,
                "description": org.description or "",
                "nit": org.nit or "",
                "contact": org.contact or "",
                "address": org.address or "",
                "phone": org.phone or "",
                "reseller": reseller_name,
                "active": "Sí" if org.active else "No",
                "created_at": str(org.created_at),
                "updated_at": str(org.updated_at),
            }
        )

    csv_data = handler.export_to_csv(rows)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=clients.csv"},
    )


# # Registro de rutas
# def register_routes(api):
#     """Registra las rutas para las vistas UserView y OrgView."""


#     api.add_url_rule("/users/", view_func=user_view, methods=["GET", "POST"])
#     api.add_url_rule(
#         "/users/<string:user_id>", view_func=user_view, methods=["GET", "PUT", "DELETE"]
#     )
#     api.add_url_rule("/organizations/", view_func=org_view, methods=["GET", "POST"])
#     api.add_url_rule(
#         "/organizations/<int:org_id>",
#         view_func=org_view,
#         methods=["GET", "PUT", "DELETE"],
#     )


# # def get_user(user_id):
# #     # Obtener datos del token
# #     aut_user_id = get_jwt_identity()
# #     claims = get_jwt()
# #     aut_roles = [role["name"] for role in claims["roles"]]
# #     aut_client_id = claims["client"]["id"] if claims.get("client") else None

# #     user = User.query.get_or_404(user_id)

# #     # Verificar permisos para ver este usuario
# #     if "administrator" in aut_roles:
# #         # Administradores pueden ver cualquier usuario
# #         pass
# #     elif "reseller" in aut_roles:
# #         # Resellers solo pueden ver usuarios de sus clientes
# #         current_user = User.query.get(aut_user_id)
# #         if not hasattr(current_user, 'reseller_info') or not current_user.reseller_info.is_reseller_client(user.client_id):
# #             return jsonify({"error": "Permission denied"}), 403
# #     elif user.client_id != aut_client_id:
# #         # Otros roles solo pueden ver usuarios de su mismo cliente
# #         return jsonify({"error": "Permission denied"}), 403

# #     return jsonify(UserSchema().dump(user))
