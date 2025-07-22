# Python standard library imports
from functools import wraps

# Third party imports
from flask import (
    Response,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
)
from flask.views import MethodView
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_csrf_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
    set_access_cookies,
    set_refresh_cookies,
    unset_jwt_cookies,
    verify_jwt_in_request,
)
from itsdangerous import BadTimeSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import (
    BadRequest,
    Forbidden,
    InternalServerError,
    NotFound,
    Unauthorized,
)
from werkzeug.security import check_password_hash

# Local application imports
from app.extensions import db
from app.helpers.mail import send_email

from .models import Organization  # PermissionEnum,; ActionEnum,
from .models import (
    ResellerPackage,
    RoleEnum,
    User,
    verify_user_in_organization,
)


def login_required(fn):
    """Decorador para revisar si el usuario está autenticado."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            verify_jwt_in_request()
        except Exception:
            return redirect(url_for("core.login"))
        return fn(*args, **kwargs)

    return wrapper


# Decorador personalizado para permisos
def check_permission(required_roles=None, resource_owner_check=False):
    """🎍 Decorador que verifica roles y permisos del usuario basado en el JWT.

    Args:
        required_roles (list, optional): Lista de roles requeridos (ej: ["administrator", "reseller"]).
        resource_owner_check (bool): Si True, verifica que el usuario sea dueño del recurso o tenga permisos superiores.

    Raises:
        Forbidden: Si el usuario no tiene los permisos necesarios.
    """
    if required_roles is None:
        required_roles = []

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            claims = get_jwt()
            user_role = claims.get("rol")
            user_id = claims.get("id")

            # Verificar si el rol del usuario está en los roles requeridos
            if required_roles and user_role not in required_roles:
                raise Forbidden("Insufficient permissions for this action.")

            # Si se requiere verificación de propietario
            if resource_owner_check:
                resource_id = kwargs.get("user_id") or kwargs.get("org_id")
                if resource_id:
                    user = User.query.get(user_id)
                    if not user:
                        raise NotFound("User not found.")

                    # Administradores tienen acceso total
                    if user_role == RoleEnum.ADMINISTRATOR.value:
                        return f(*args, **kwargs)

                    # Verificar si el usuario es el propietario del recurso o tiene permisos superiores
                    if user_id != resource_id and not user.is_reseller():
                        raise Forbidden("You can only modify your own resources.")

            return f(*args, **kwargs)

        return decorated_function

    return decorator


def check_resource_access(resource, claims):
    """
    Verifica si un usuario tiene acceso a un recurso específico basado en su rol y claims.

    Args:
        resource: El recurso al que se intenta acceder (debe tener un atributo org_id)
        claims: Diccionario con información del usuario (rol, user_id, org_id)

    Returns:
        bool: True si el usuario tiene acceso, False en caso contrario

    Raises:
        ValueError: Si los claims no contienen la información necesaria
    """
    user_role = claims.get("rol")
    if not user_role:
        return False

    # Caso del rol ADMINISTRATOR: acceso total
    if user_role == RoleEnum.ADMINISTRATOR.value:
        return True

    # Caso del rol RESELLER: acceso a recursos de organizaciones en su paquete
    if user_role == RoleEnum.RESELLER.value:
        reseller_org_id = claims.get("org_id")
        if not reseller_org_id:
            return False
        reseller_package = ResellerPackage.query.filter_by(
            reseller_id=reseller_org_id
        ).first()
        if not reseller_package:
            return False
        resource_org_id = getattr(resource, "org_id", None)
        if resource_org_id is None:
            return False
        return any(org.id == resource_org_id for org in reseller_package.organizations)

    # Caso de roles organizacionales: ORG_ADMIN, ORG_EDITOR, ORG_VIEWER
    if user_role in (
        RoleEnum.ORG_ADMIN.value,
        RoleEnum.ORG_EDITOR.value,
        RoleEnum.ORG_VIEWER.value,
    ):
        user_id = claims.get("user_id")
        if not user_id:
            return False
        user = User.query.get(user_id)
        if not user:
            return False
        resource_org_id = getattr(resource, "org_id", None)
        if resource_org_id is None:
            return False
        return any(org.id == resource_org_id for org in user.organizations)

    return False


class LoginView(MethodView):
    """Handle user authentication"""

    def post(self):
        """User login endpoint
        :param str username: Registered username
        :param str password: Account password
        :status 200: Successful login
        :status 400: Invalid request data
        :status 401: Authentication failure
        """
        try:
            data = request.get_json()
            if not data:
                return jsonify({"msg": "Missing request data"}), 400

            username = data.get("username", "").strip()
            password = data.get("password", "").strip()

            if not username or not password:
                return jsonify({"msg": "Credentials required"}), 400

            user = User.get_by_username(username)
            if self._invalid_credentials(user, password):
                return jsonify({"msg": "Invalid credentials"}), 401

            claims = self._build_claims(user)
            tokens = self._generate_tokens(str(user.id), claims)
            response = self._build_response(tokens, claims)

            return response

        except Exception as e:
            print(f"Login error: {str(e)}")
            return jsonify({"msg": "Invalid request"}), 400

    def _invalid_credentials(self, user, password):
        """Validate user credentials"""
        return not user or not user.check_password(password) or not user.active

    def _build_claims(self, user):
        """Construct JWT claims payload"""
        claims = {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "organizations": [
                {"id": org.id, "name": org.name} for org in user.organizations
            ],
            "rol": user.role.value,
        }

        if user.role == RoleEnum.RESELLER:
            reseller_package = user.reseller_packages.first()
            if reseller_package:
                claims["reseller_organizations"] = [
                    {"id": org.id, "name": org.name}
                    for org in reseller_package.organizations
                ]
        return claims

    def _generate_tokens(self, identity, claims):
        """Generate JWT tokens"""
        return (
            create_access_token(identity=identity, additional_claims=claims),
            create_refresh_token(identity=identity, additional_claims=claims),
        )

    def _build_response(self, tokens, claims):
        """Build final response with cookies"""
        access_token, refresh_token = tokens
        response = jsonify(
            {
                "access_csrf": get_csrf_token(access_token),
                "refresh_csrf": get_csrf_token(refresh_token),
                "additional_claims": claims,
                "msg": "Authentication successful",
            }
        )
        set_access_cookies(response, access_token)
        set_refresh_cookies(response, refresh_token)
        return response


class RefreshView(MethodView):
    """Handle token refresh operations"""

    @jwt_required(refresh=True)
    def post(self):
        """Refresh access token endpoint
        :status 200: Token refreshed successfully
        :status 401: Invalid or expired refresh token
        """
        try:
            current_user = get_jwt_identity()
            jwt_data = get_jwt()

            user = User.query.get(current_user)
            if not user or not user.active:
                return jsonify({"msg": "Invalid token"}), 401

            new_claims = self._update_claims(
                jwt_data.get("additional_claims", {}), user
            )
            new_access_token = create_access_token(
                identity=current_user, additional_claims=new_claims
            )

            response = jsonify(
                {
                    "access_csrf": get_csrf_token(new_access_token),
                    "additional_claims": new_claims,
                    "msg": "Token refreshed",
                }
            )
            set_access_cookies(response, new_access_token)

            return response

        except Exception as e:
            print(f"Refresh error: {str(e)}")
            return jsonify({"msg": "Token refresh failed"}), 401

    def _update_claims(self, existing_claims, user):
        """Update JWT claims with fresh user data"""
        updated_claims = existing_claims.copy()

        # Actualizar datos sensibles a cambios
        updated_claims.update(
            {
                "username": user.username,
                "email": user.email,
                "rol": user.role.value,
                "organizations": [
                    {"id": org.id, "name": org.name} for org in user.organizations
                ],
            }
        )

        # Actualizar organizaciones de reseller si corresponde
        if user.role == RoleEnum.RESELLER:
            reseller_package = user.reseller_packages.first()
            if reseller_package:
                updated_claims["reseller_organizations"] = [
                    {"id": org.id, "name": org.name}
                    for org in reseller_package.organizations
                ]

        return updated_claims


# Vista para usuarios
class UserView(MethodView):
    """Clase para gestionar operaciones CRUD sobre usuarios."""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, user_id=None):
        """
        Obtiene una lista de usuarios o un usuario específico.

        Args:
            user_id (str, optional): ID del usuario a consultar.

        Returns:
            JSON: Lista de usuarios o detalles de un usuario específico.
        """
        if user_id:
            return self._get_user(user_id)
        return self._get_user_list()

    @check_permission(required_roles=["administrator", "reseller"])
    def post(self):
        """
        Crea un nuevo usuario.

        Returns:
            JSON: Detalles del usuario creado.
        """
        data = request.get_json()
        if not data or not all(
            k in data for k in ("username", "email", "full_name", "password", "role")
        ):
            raise BadRequest("Missing required fields.")

        return self._create_user(data)

    @check_permission(resource_owner_check=True)
    def put(self, user_id):
        """
        Actualiza un usuario existente.

        Args:
            user_id (str): ID del usuario a actualizar.

        Returns:
            JSON: Detalles del usuario actualizado.
        """
        data = request.get_json()
        if not data or not user_id:
            raise BadRequest("Missing user_id or data.")

        return self._update_user(user_id, data)

    @check_permission(resource_owner_check=True)
    def delete(self, user_id=None):
        """
        Elimina un usuario existente.

        Args:
            user_id (str): ID del usuario a eliminar.

        Returns:
            JSON: Mensaje de confirmación.
        """
        data = request.get_json()
        if data and "ids" in data:
            return self._delete_user(user_ids=data["ids"])
        if user_id:
            return self._delete_user(user_id=user_id)
        raise BadRequest("Missing user_id.")

    # Métodos auxiliares
    def _get_user_list(self):
        """Obtiene una lista de todos los usuarios activos."""
        claims = get_jwt()
        user_role = claims.get("rol")
        user_id = claims.get("id")

        if user_role == RoleEnum.ADMINISTRATOR.value:
            users = User.query.filter_by(active=True).all()
        elif user_role == RoleEnum.RESELLER.value:
            reseller_package = ResellerPackage.query.filter_by(
                reseller_id=user_id
            ).first()
            if not reseller_package:
                raise NotFound("Reseller package not found.")
            users = []
            for org in reseller_package.organizations:
                users.extend(org.users)
        else:
            raise Forbidden("Only administrators and resellers can list users.")

        return jsonify([self._serialize_user(user) for user in users]), 200

    def _get_user(self, user_id):
        """Obtiene los detalles de un usuario específico."""
        user = User.query.get_or_404(user_id)
        claims = get_jwt()
        if not self._has_access(user, claims):
            raise Forbidden("You do not have access to this user.")
        return jsonify(self._serialize_user(user)), 200

    def _create_user(self, data):
        """Crea un nuevo usuario con los datos proporcionados."""
        if User.query.filter_by(username=data["username"]).first():
            raise BadRequest("Username already exists.")
        if User.query.filter_by(email=data["email"]).first():
            raise BadRequest("Email already exists.")
        ROLE_MAP = {
            "reseller": RoleEnum.RESELLER,
            "administrator": RoleEnum.ADMINISTRATOR,
            "org_admin": RoleEnum.ORG_ADMIN,
            "org_editor": RoleEnum.ORG_EDITOR,
            "org_viewer": RoleEnum.ORG_VIEWER,
        }
        role = ROLE_MAP.get(data["role"].lower())
        if role is None:
            raise BadRequest("Invalid role.")
        user = User(
            username=data["username"],
            email=data["email"],
            full_name=data["full_name"],
            role=role,
        )
        if "organization_id" in data:
            organization_id = data["organization_id"]
            user.assign_organization(organization_id)
        user.set_password(data["password"])
        db.session.add(user)
        db.session.commit()
        return jsonify(self._serialize_user(user)), 201

    def _update_user(self, user_id, data):
        """Actualiza los datos de un usuario existente."""
        user = User.query.get_or_404(user_id)
        if "username" in data and data["username"] != user.username:
            if User.query.filter_by(username=data["username"]).first():
                raise BadRequest("Username already exists.")
            user.username = data["username"]
        if "email" in data and data["email"] != user.email:
            if User.query.filter_by(email=data["email"]).first():
                raise BadRequest("Email already exists.")
            user.email = data["email"]
        if "full_name" in data:
            user.full_name = data["full_name"]
        if "password" in data:
            user.set_password(data["password"])
        ROLE_MAP = {
            "reseller": RoleEnum.RESELLER,
            "administrator": RoleEnum.ADMINISTRATOR,
            "org_admin": RoleEnum.ORG_ADMIN,
            "org_editor": RoleEnum.ORG_EDITOR,
            "org_viewer": RoleEnum.ORG_VIEWER,
        }
        if "role" in data:
            claims = get_jwt()
            if claims.get("rol") == RoleEnum.ADMINISTRATOR.value:
                role = ROLE_MAP.get(data["role"].lower())
                if role is None:
                    raise BadRequest("Invalid role.")
                user.role = role
            else:
                raise Forbidden("Only administrators can change roles.")
        if "organization_id" in data:
            organization_id = data["organization_id"]
            user = User.query.get(user_id)
            if user:
                # Desasignar organización anterior si corresponde
                if user.organizations:
                    for org in user.organizations:
                        user.unassign_organization(org.id)
                # Asignar nueva organización
                user.assign_organization(organization_id)

        db.session.commit()
        return jsonify(self._serialize_user(user)), 200

    def _delete_user(self, user_id=None, user_ids=None):
        """Elimina un usuario marcándolo como inactivo."""
        claims = get_jwt()

        if user_id and user_ids:
            raise BadRequest("Solo se puede especificar user_id o user_ids, no ambos.")

        if user_id:
            user = User.query.get_or_404(user_id)
            user.active = False  # no se borra al usuario, solo se inactiva.
            db.session.commit()
            return jsonify({"message": "User deleted successfully"}), 200

        if user_ids:
            deleted_users = []
            for user_id in user_ids:
                user = User.query.get(user_id)
                if not user:
                    continue
                user.active = False
                deleted_users.append(user.username)
                db.session.commit()
                deleted_users_str = ", ".join(deleted_users)
            return (
                jsonify({"message": f"Users {deleted_users_str} deleted successfully"}),
                200,
            )

        if not deleted_users:
            return (
                jsonify(
                    {"error": "No users were deleted due to permission restrictions"}
                ),
                403,
            )

    def _has_access(self, user, claims):
        """Verifica si el usuario actual tiene acceso al recurso."""
        user_role = claims.get("rol")
        user_id = claims.get("id")

        if user_role == RoleEnum.ADMINISTRATOR.value:
            return True
        if user_role == RoleEnum.RESELLER.value:
            reseller_package = ResellerPackage.query.filter_by(
                reseller_id=user_id
            ).first()
            return any(
                org.id in [o.id for o in reseller_package.organizations]
                for org in user.organizations
            )
        return user_id == user.id

    def _serialize_user(self, user):
        """Serializa un objeto User a un diccionario."""
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value,
            "active": user.active,
            "org": next((org.name for org in user.organizations.all()), ""),
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat(),
        }


# Vista para organizaciones
class OrgView(MethodView):
    """Clase para gestionar operaciones CRUD sobre organizaciones."""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, org_id=None):
        """
        Obtiene una lista de organizaciones o una organización específica.

        Args:
            org_id (int, optional): ID de la organización a consultar.

        Returns:
            JSON: Lista de organizaciones o detalles de una organización específica.
        """
        if org_id:
            return self._get_organization(org_id)
        return self._get_org_list()

    @check_permission(required_roles=["administrator", "reseller"])
    def post(self):
        """
        Crea una nueva organización.

        Returns:
            JSON: Detalles de la organización creada.
        """
        data = request.get_json()
        if not data or not all(k in data for k in ("name", "reseller_id")):
            raise BadRequest("Missing required fields.")

        return self._create_organization(data)

    @check_permission(resource_owner_check=True)
    def put(self, org_id):
        """
        Actualiza una organización existente.

        Args:
            org_id (int): ID de la organización a actualizar.

        Returns:
            JSON: Detalles de la organización actualizada.
        """
        data = request.get_json()
        if not data or not org_id:
            raise BadRequest("Missing org_id or data.")

        return self._update_organization(org_id, data)

    @check_permission(resource_owner_check=True)
    def delete(self, org_id=None):
        """
        Elimina una o varias organizaciones existentes.

        Args:
            org_id (int, optional): ID de la organización a eliminar.

        Returns:
            JSON: Mensaje de confirmación.
        """
        data = request.get_json()
        if data and "ids" in data:
            return self._delete_organization(org_ids=data["ids"])
        if org_id:
            return self._delete_organization(org_id=org_id)
        raise BadRequest("Missing org_id or ids.")

    # Métodos auxiliares
    def _get_org_list(self):
        """Obtiene una lista de todas las organizaciones activas."""
        claims = get_jwt()
        user_role = claims.get("rol")
        user_id = claims.get("id")

        if user_role == RoleEnum.ADMINISTRATOR.value:
            orgs = Organization.query.filter_by(active=True).all()
        elif user_role == RoleEnum.RESELLER.value:
            reseller_package = ResellerPackage.query.filter_by(
                reseller_id=user_id
            ).first()
            if not reseller_package:
                raise NotFound("Reseller package not found.")
            orgs = reseller_package.organizations
        else:
            user = User.query.get(user_id)
            orgs = user.organizations

        return jsonify([self._serialize_organization(org) for org in orgs]), 200

    def _get_organization(self, org_id):
        """Obtiene los detalles de una organización específica."""
        org = Organization.query.get_or_404(org_id)
        claims = get_jwt()
        if not self._has_access(org, claims):
            raise Forbidden("You do not have access to this organization.")
        return jsonify(self._serialize_organization(org)), 200

    def _create_organization(self, data):
        """Crea una nueva organización con los datos proporcionados."""
        org = Organization(
            name=data["name"],
            description=data.get("description", ""),
            nit=data.get("nit"),
            contact=data.get("contact"),
            address=data.get("address"),
            phone=data.get("phone"),
        )
        if "reseller_id" in data:
            claims = get_jwt()
            if claims.get("rol") == RoleEnum.ADMINISTRATOR.value:
                reseller_user = User.query.get(data["reseller_id"])
                if reseller_user:
                    reseller_package = ResellerPackage.query.filter_by(
                        reseller_id=reseller_user.id
                    ).first()
                    if reseller_package:
                        if reseller_package.add_client():
                            if org.reseller_id:
                                old_reseller_package = ResellerPackage.query.get(
                                    org.reseller_id
                                )
                                old_reseller_package.decrease_client()
                            org.reseller_id = reseller_package.id
                            reseller_package.increase_client()
                        else:
                            raise BadRequest(
                                "Reseller has reached the maximum number of clients."
                            )
                    else:
                        raise BadRequest(
                            "The reseller does not have a reseller package."
                        )
                else:
                    pass
            else:
                raise Forbidden("Only administrators can change reseller assignments.")
        db.session.add(org)
        db.session.commit()
        return jsonify(self._serialize_organization(org)), 201

    def _update_organization(self, org_id, data):
        """Actualiza los datos de una organización existente."""
        org = Organization.query.get_or_404(org_id)
        if "name" in data and data["name"]:
            org.name = data["name"]
        if "description" in data and data["description"] is not None:
            org.description = data["description"]
        if "nit" in data:
            org.nit = data["nit"]
        if "contact" in data:
            org.contact = data["contact"]
        if "address" in data:
            org.address = data["address"]
        if "phone" in data:
            org.phone = data["phone"]
        if "reseller_id" in data:
            claims = get_jwt()
            if claims.get("rol") == RoleEnum.ADMINISTRATOR.value:
                reseller_user = User.query.get(data["reseller_id"])
                if reseller_user:
                    reseller_package = ResellerPackage.query.filter_by(
                        reseller_id=reseller_user.id
                    ).first()
                    if reseller_package:
                        if reseller_package.add_client():
                            if org.reseller_id:
                                old_reseller_package = ResellerPackage.query.get(
                                    org.reseller_id
                                )
                                old_reseller_package.decrease_client()
                            org.reseller_id = reseller_package.id
                            reseller_package.increase_client()
                        else:
                            raise BadRequest(
                                "Reseller has reached the maximum number of clients."
                            )
                    else:
                        raise BadRequest(
                            "The reseller does not have a reseller package."
                        )
                else:
                    pass
            else:
                raise Forbidden("Only administrators can change reseller assignments.")
        db.session.commit()
        return jsonify(self._serialize_organization(org)), 200

    def _delete_organization(self, org_id=None, org_ids=None):
        """
        Elimina una o varias organizaciones marcándolas como inactivas.

        Args:
            org_id (int, optional): ID de la organización a eliminar.
            org_ids (list, optional): Lista de IDs de organizaciones a eliminar.

        Returns:
            JSON: Mensaje de confirmación.
        """
        if org_id and org_ids:
            raise BadRequest("Solo se puede especificar org_id o org_ids, no ambos.")

        claims = get_jwt()
        user_role = claims.get("rol")
        user_id = claims.get("id")

        if org_id:
            org = Organization.query.get_or_404(org_id)
            if not self._has_access(org, claims):
                raise Forbidden("You do not have access to this organization.")
            org.active = False
            if org.reseller_id:
                reseller_package = ResellerPackage.query.get(org.reseller_id)
                if reseller_package:
                    reseller_package.decrease_client()
            db.session.commit()
            return jsonify({"message": "Organization deleted successfully"}), 200

        if org_ids:
            deleted_orgs = []
            for org_id in org_ids:
                org = Organization.query.get(org_id)
                if not org:
                    continue
                if not self._has_access(org, claims):
                    continue
                org.active = False
                if org.reseller_id:
                    reseller_package = ResellerPackage.query.get(org.reseller_id)
                    if reseller_package:
                        reseller_package.decrease_client()
                deleted_orgs.append(org.name)

            if not deleted_orgs:
                return (
                    jsonify(
                        {
                            "error": "No organizations were deleted due to permission restrictions"
                        }
                    ),
                    403,
                )

            db.session.commit()
            deleted_orgs_str = ", ".join(deleted_orgs)
            return (
                jsonify(
                    {
                        "message": f"Organizations {deleted_orgs_str} deleted successfully"
                    }
                ),
                200,
            )

        raise BadRequest("Missing org_id or org_ids.")

    def _has_access(self, org, claims):
        """Verifica si el usuario actual tiene acceso al recurso."""
        user_role = claims.get("rol")
        user_id = claims.get("id")

        if user_role == RoleEnum.ADMINISTRATOR.value:
            return True
        if user_role == RoleEnum.RESELLER.value:
            reseller_package = ResellerPackage.query.filter_by(
                reseller_id=user_id
            ).first()
            return reseller_package and org.reseller_id == reseller_package.id
        return verify_user_in_organization(user_id, org.id)

    def _serialize_organization(self, org):
        """Serializa un objeto Organization a un diccionario."""
        return {
            "id": org.id,
            "name": org.name,
            "description": org.description,
            "nit": org.nit,
            "contact": org.contact,
            "address": org.address,
            "phone": org.phone,
            "reseller_id": org.get_reseller.id if org.get_reseller else "",
            "reseller": org.get_reseller.full_name if org.get_reseller else "",
            "active": org.active,
            "created_at": org.created_at.isoformat(),
            "updated_at": org.updated_at.isoformat(),
        }


class ForgotPasswordRequestView(MethodView):
    """Handles the request for password reset."""

    def post(self):
        """
        Handles POST request to initiate password reset.
        Expects an email in the JSON payload.
        """
        try:
            data = request.get_json()
            email = None

            if data and "email" in data:
                email = data.get("email", "").strip()

            # Even if email is missing or empty, log it but proceed to generic response
            # to prevent an attacker from distinguishing between bad request and non-existent email.
            if not email:
                current_app.logger.info(
                    "Password reset attempt with missing or empty email."
                )
                # Fall through to the generic response

            # Only proceed with email logic if an email was actually provided
            if email:
                user = User.get_by_email(email)

                if user and user.active:
                    serializer = URLSafeTimedSerializer(
                        current_app.config["SECRET_KEY"]
                    )
                    # Salt is recommended for tokens that are not one-time use or have other security implications.
                    # For a password reset token, it adds an extra layer of security.
                    token = serializer.dumps(user.email, salt="password-reset-salt")
                    # base_url = request.host_url.rstrip("/")
                    # reset_url = f"{base_url}{url_for('core.reset_password_form', token=token, _external=True)}"
                    reset_url = url_for(
                        "core.reset_password_form", token=token, _external=True
                    )

                    subject = "Password Reset Request"
                    body = (
                        f"Hello {user.username},\n\n"
                        f"You requested a password reset. Click the link below to reset your password:\n"
                        f"{reset_url}\n\n"
                        f"This link will expire in 1 hour (3600 seconds).\n\n"
                        f"If you did not request this, please ignore this email.\n\n"
                        f"Thanks,\nThe Support Team"
                    )

                    try:
                        send_email(recipients=user.email, subject=subject, message=body)
                        current_app.logger.info(
                            f"Password reset email sent to {user.email}"
                        )
                    except Exception as e:
                        current_app.logger.error(
                            f"Failed to send password reset email to {user.email}: {e}"
                        )
                        # Do not re-raise, fall through to generic response

            # Generic response to prevent email enumeration and other leaks
            return (
                jsonify(
                    {
                        "msg": "If your email is registered, you will receive a password reset link."
                    }
                ),
                200,
            )

        except Exception as e:
            # Log any other unexpected errors during the process
            current_app.logger.error(
                f"Unexpected error in ForgotPasswordRequestView: {e}", exc_info=True
            )
            # Still return the generic success message to the client
            return (
                jsonify(
                    {
                        "msg": "If your email is registered, you will receive a password reset link."
                    }
                ),
                200,
            )


class ResetPasswordFormView(MethodView):
    """Handles rendering the password reset form after token validation."""

    def get(self, token):
        """
        Validates the password reset token and renders the reset form.
        """
        serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        try:
            # max_age is 3600 seconds (1 hour), matching token generation
            email = serializer.loads(token, salt="password-reset-salt", max_age=3600)
        except SignatureExpired:
            flash(
                "The password reset link has expired. Please request a new one.",
                "error",
            )
            return redirect(url_for("core.forgot_password"))
        except BadTimeSignature:  # This catches BadSignature, BadHeader, BadPayload
            flash(
                "The password reset link is invalid or has been tampered with.", "error"
            )
            return redirect(url_for("core.forgot_password"))
        except Exception as e:
            current_app.logger.error(
                f"Unexpected error during password reset token decoding: {e}"
            )
            flash(
                "An unexpected error occurred with the reset link. Please try again.",
                "error",
            )
            return redirect(url_for("core.forgot_password"))

        user = User.get_by_email(email)
        if not user or not user.active:
            flash(
                "Invalid user or reset link. The user may not exist or may be inactive.",
                "error",
            )
            return redirect(url_for("core.forgot_password"))

        # If token is valid and user exists, render the form to reset the password
        # The 'token' is passed to the form so it can be submitted along with the new password
        return render_template("reset_password_form.j2", token=token)


class ResetPasswordSubmitView(MethodView):
    """Handles the submission of the new password."""

    def post(self, token):
        """
        Handles POST request to reset the password using the provided token
        and new password data from the form.
        """
        serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
        try:
            email = serializer.loads(token, salt="password-reset-salt", max_age=3600)
        except SignatureExpired:
            # Flash message for UI, JSON for API-like response
            flash(
                "The password reset link has expired. Please request a new one.",
                "error",
            )
            return jsonify({"error": "The password reset link has expired."}), 400
        except BadTimeSignature:
            flash(
                "The password reset link is invalid or has been tampered with.", "error"
            )
            return jsonify({"error": "The password reset link is invalid."}), 400
        except Exception as e:
            current_app.logger.error(
                f"Unexpected error during password reset token decoding (submission): {e}"
            )
            flash(
                "An unexpected error occurred with the reset link. Please try again.",
                "error",
            )
            return (
                jsonify({"error": "An unexpected error occurred with the reset link."}),
                400,
            )

        user = User.get_by_email(email)
        if not user or not user.active:
            flash(
                "Invalid user or reset link. The user may not exist or may be inactive.",
                "error",
            )
            return jsonify({"error": "Invalid user or reset link."}), 400

        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")

        if not new_password or not confirm_password:
            flash("New password and confirmation are required.", "error")
            return (
                jsonify({"error": "New password and confirmation are required."}),
                400,
            )

        if new_password != confirm_password:
            flash("Passwords do not match. Please try again.", "error")
            return jsonify({"error": "Passwords do not match."}), 400

        if len(new_password) < 8:  # Basic length check
            flash("Password must be at least 8 characters long.", "error")
            return (
                jsonify({"error": "Password must be at least 8 characters long."}),
                400,
            )

        # Optional: Check if the new password is the same as the old one
        # This might be desirable for security to ensure they actually change it.
        if user.check_password(new_password):
            flash("New password cannot be the same as the current password.", "error")
            return (
                jsonify(
                    {
                        "error": "New password cannot be the same as the current password."
                    }
                ),
                400,
            )

        try:
            user.set_password(new_password)
            db.session.add(user)  # Ensure changes are staged
            db.session.commit()

            flash(
                "Your password has been reset successfully. Please log in.", "success"
            )
            # The client-side JS will handle redirection based on this response.
            return (
                jsonify(
                    {
                        "message": "Password reset successfully. You can now log in.",
                        "redirect_url": url_for("core.login"),
                    }
                ),
                200,
            )
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(
                f"Error saving new password for user {user.email}: {e}"
            )
            flash(
                "An error occurred while saving your new password. Please try again.",
                "error",
            )
            return (
                jsonify({"error": "Failed to update password due to a server error."}),
                500,
            )


class ProfileView(MethodView):
    """Handles fetching and updating the current user's profile."""

    decorators = [jwt_required()]

    def get(self):
        """Fetch the current logged-in user's profile data."""
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            raise NotFound("User not found.")

        # Serialize relevant data (excluding sensitive info like password hash)
        serialized_data = {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value,
            "organizations": [
                {"id": org.id, "name": org.name} for org in user.organizations.all()
            ],
            # Add other non-sensitive fields from User model if needed
        }
        return jsonify(serialized_data), 200

    def put(self):
        """Update the current logged-in user's profile data."""
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            raise NotFound("User not found.")

        data = request.get_json()
        if not data:
            raise BadRequest("No data provided.")

        updated = False
        # Allow updating specific fields (e.g., full_name, email)
        if "full_name" in data and data["full_name"] != user.full_name:
            user.full_name = data["full_name"].strip()
            if not user.full_name:
                raise BadRequest("Full name cannot be empty.")
            updated = True

        if "email" in data and data["email"] != user.email:
            new_email = data["email"].strip().lower()
            if not new_email:
                raise BadRequest("Email cannot be empty.")
            # Optional: Add email format validation
            existing_user = User.query.filter(
                User.email == new_email, User.id != user_id
            ).first()
            if existing_user:
                raise BadRequest("Email address is already in use.")
            user.email = new_email
            updated = True

        # Add other updatable fields here if necessary

        if updated:
            try:
                db.session.commit()
                return jsonify({"msg": "Profile updated successfully."}), 200
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(
                    f"Error updating profile for user {user_id}: {e}"
                )
                raise InternalServerError("Failed to update profile.")
        else:
            return jsonify({"msg": "No changes detected."}), 200


class ChangePasswordView(MethodView):
    """Handles changing the current user's password."""

    decorators = [jwt_required()]

    def post(self):
        """Change the current user's password."""
        user_id = get_jwt_identity()
        user = User.query.get(user_id)
        if not user:
            raise NotFound("User not found.")

        data = request.get_json()
        if not data or not all(
            k in data for k in ["current_password", "new_password", "confirm_password"]
        ):
            raise BadRequest(
                "Missing required fields: current_password, new_password, confirm_password."
            )

        current_password = data.get("current_password")
        new_password = data.get("new_password")
        confirm_password = data.get("confirm_password")

        # 1. Verify current password
        if not user.check_password(current_password):
            raise Unauthorized("Incorrect current password.")

        # 2. Check if new password and confirm match
        if new_password != confirm_password:
            raise BadRequest("New password and confirmation do not match.")

        # 3. Optional: Add password strength validation (reuse validator if needed)
        if len(new_password) < 8:  # Example basic check
            raise BadRequest("New password must be at least 8 characters long.")
        # Add more complex checks from validators.py if desired

        # 4. Check if the new password is the same as the old one
        if user.check_password(new_password):
            raise BadRequest("New password cannot be the same as the current password.")

        # 5. Set the new password
        try:
            user.set_password(new_password)
            db.session.commit()
            return jsonify({"msg": "Password updated successfully."}), 200
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error changing password for user {user_id}: {e}")
            raise InternalServerError("Failed to change password.")


class InstallationView(MethodView):
    """Application installation system with improved error handling and transaction management."""

    def __init__(self):
        self.status = {
            "current_step": 0,
            "steps": [
                {
                    "name": "Verificando pre-instalación",
                    "status": "pending",
                    "error": None,
                },
                {"name": "Creando tablas", "status": "pending", "error": None},
                {
                    "name": "Creando usuario administrador",
                    "status": "pending",
                    "error": None,
                },
                {
                    "name": "Creando organizaciones base",
                    "status": "pending",
                    "error": None,
                },
                {"name": "Generando datos demo", "status": "pending", "error": None},
            ],
            "completed": False,
        }

    def get(self):
        """Render installation progress page."""

        return render_template("installer.j2", status=self.status)

    def _execute_step(self, step_index, func, *args):
        """Execute a single installation step with status tracking."""
        self._update_step(step_index, "in_progress")
        try:
            func(*args)
            self._update_step(step_index, "completed")
        except Exception as e:
            self._update_step(step_index, "failed", str(e))
            raise

    def _update_step(self, step_index, status, error=None):
        """Update installation progress status."""
        self.status["steps"][step_index]["status"] = status
        self.status["steps"][step_index]["error"] = error
        self.status["current_step"] = step_index

    def _check_pre_installation(self):
        """Verify system is already installed."""
        inspector = inspect(db.engine)
        if (
            inspector.has_table("users")
            and User.query.filter_by(role=RoleEnum.ADMINISTRATOR).first()
        ):
            raise Exception("El sistema ya está instalado")
        return True

    def _create_tables(self):
        """Create database schema."""
        try:
            db.create_all()
        except Exception as e:
            raise Exception("Error creando tablas: Verifica la conexión a BD") from e

    def _create_admin_user(self, form_data):
        """Create initial administrator account with validated credentials."""
        credentials = {
            "username": form_data.get("admin_username", "merlin").strip(),
            "password": form_data.get("admin_password", "Strong_Pass123!").strip(),
            "use_custom": "use_custom_creds" in form_data,
        }

        if credentials["use_custom"]:
            if not credentials["username"]:
                raise ValueError("Nombre de usuario requerido")
            if len(credentials["password"]) < 8:
                raise ValueError("La contraseña debe tener mínimo 8 caracteres")

        if User.get_by_username(credentials["username"]):
            raise ValueError(f'Usuario {credentials["username"]} ya existe')

        email = f"{credentials['username']}@system.local"
        if User.get_by_email(email):
            raise ValueError(f"Email {email} ya registrado")

        admin = User(
            username=credentials["username"],
            email=email,
            full_name=f"Admin ({credentials['username']})",
            role=RoleEnum.ADMINISTRATOR,
            active=True,
        )
        admin.set_password(credentials["password"])
        db.session.add(admin)
        db.session.flush()

    def _create_base_organizations(self):
        """Create default system organizations."""
        default_org = {
            "name": "Organización Principal",
            "description": "Organización principal",
            "reseller_id": None,
        }

        if Organization.query.filter_by(name=default_org["name"]).first():
            raise ValueError(f'Organización {default_org["name"]} ya existe')

        db.session.add(Organization(**default_org))
        db.session.flush()

    def _create_demo_data(self):
        """Generate sample data with reseller and organization users."""
        try:
            # Crear usuario reseller
            reseller_data = {
                "username": "demo_reseller",
                "email": "reseller@demo.local",
                "full_name": "Reseller Demo",
                "role": RoleEnum.RESELLER,
                "password": "SecureResellerPass123!",
            }

            if User.get_by_username(reseller_data["username"]):
                raise ValueError(f"User {reseller_data['username']} already exists")

            reseller = User(
                **{k: v for k, v in reseller_data.items() if k != "password"}
            )
            reseller.set_password(reseller_data["password"])
            db.session.add(reseller)
            db.session.flush()

            # Crear paquete de reseller
            reseller_package = ResellerPackage(
                reseller_id=reseller.id, max_clients=15, current_clients=0
            )
            db.session.add(reseller_package)
            db.session.flush()

            # Crear organización demo
            demo_org = Organization(
                name="Organización Demo",
                description="Cliente de demostración",
                profile_data={"demo": True},
            )
            db.session.add(demo_org)
            db.session.flush()

            if not reseller_package.assign_client(demo_org):
                raise RuntimeError("Failed to assign organization to reseller")

            # Crear usuarios de organización
            org_users = [
                {
                    "username": "org_admin",
                    "email": "admin@org.demo",
                    "role": RoleEnum.ORG_ADMIN,
                    "password": "OrgAdminSecure123!",
                },
                {
                    "username": "org_editor",
                    "email": "editor@org.demo",
                    "role": RoleEnum.ORG_EDITOR,
                    "password": "EditorSecure123!",
                },
                {
                    "username": "demo_viewer",
                    "email": "viewer@org.demo",
                    "role": RoleEnum.ORG_VIEWER,
                    "password": "ViewerSecure123!",
                },
            ]

            for user_data in org_users:
                if User.get_by_username(user_data["username"]):
                    raise ValueError(f"User {user_data['username']} already exists")

                user = User(
                    username=user_data["username"],
                    email=user_data["email"],
                    full_name=f"{user_data['role'].description} Demo",
                    role=user_data["role"],
                    active=True,
                )
                user.set_password(user_data["password"])
                user.organizations.append(demo_org)
                db.session.add(user)

            db.session.flush()

        except IntegrityError as e:
            current_app.logger.error(f"Demo data integrity error: {str(e)}")
            raise RuntimeError("Duplicate demo data detected") from e

    def post(self):
        """Handle installation process with transactional integrity."""
        try:
            db.session.begin_nested()

            self._execute_step(0, self._check_pre_installation)
            self._execute_step(1, self._create_tables)
            self._execute_step(2, self._create_admin_user, request.form)
            self._execute_step(3, self._create_base_organizations)

            if request.form.get("create_demo") == "true":
                self._execute_step(4, self._create_demo_data)

            from app.modules.foliage.helpers import initialize_nutrients

            initialize_nutrients()

            db.session.commit()
            self.status["completed"] = True
            return jsonify(
                {
                    "success": True,
                    "redirect": url_for("core.login"),
                    "status": self.status,
                }
            )

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Installation failed: {str(e)}", exc_info=True)
            return (
                jsonify({"success": False, "error": str(e), "status": self.status}),
                500,
            )
