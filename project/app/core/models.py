"""
User model roles, permissions and actions
module for Yet Another Flask Survival Kit (YAFSK)
Author: Johnny De Castro
Email: j@jdcastro.co
Copyright (c) 2024 - 2025 Johnny De Castro.
All rights reserved.

Licensed under the Apache License, Version 2.0
http://www.apache.org/licenses/LICENSE-2.0
"""

import time
import uuid
import weakref

# Python standard library imports
from datetime import datetime
from enum import Enum
from functools import lru_cache
from threading import Timer
from typing import List

from sqlalchemy.orm import joinedload

# Third party imports
from werkzeug.security import check_password_hash, generate_password_hash

from app.core.constants import ProfileDataKeys

# Local application imports
from app.extensions import db

__doc__ = """
Documentation of the model:
This SQLAlchemy model implements a role and permission-based access control system, designed to manage users, their roles, permissions, and associated actions within a reseller schema. It also includes models for clients (organizations), reseller limits, and system modules.

Permission Management:
The roles, actions, and permissions model is managed statically with enumerations.
The definition of roles, actions, and permissions is done using enums to make the structure very clear and easy to maintain.
Changes to permissions or roles can be managed centrally in the enums and associated dictionaries.
"""


# 1. Enumeraciones (Enums):
class RoleEnum(Enum):
    """Enumeration of the predefined roles available in the system.

    Roles include administrator, reseller, organization administrator,
    organization editor and organization viewer.
    """

    ADMINISTRATOR = ("administrator", "Administrador")
    RESELLER = ("reseller", "Revendedor")
    ORG_ADMIN = ("org_admin", "Administrador de Organización")
    ORG_EDITOR = ("org_editor", "Editor de Organización")
    ORG_VIEWER = ("org_viewer", "Visor de Organización")

    def __init__(self, id, description):
        self.id = id
        self.description = description

    @property
    def value(self):
        """Return the role identifier."""
        return self.id


class ActionEnum(Enum):
    """Enumeration of the actions allowed in the system."""

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    MANAGE = "manage"


class PermissionEnum(Enum):
    """Enumeration of the permissions supported by the system."""

    FULL_MANAGEMENT = "full_management"
    ORG_MANAGEMENT = "org_management"
    CONTENT_MANAGEMENT = "content_management"
    REPORTING = "reporting"
    SYSTEM_SETTINGS = "system_settings"
    LIMITED_REPORTS = "limited_reports"


# Definir permisos por rol
ROLE_PERMISSIONS = {
    RoleEnum.ADMINISTRATOR: [PermissionEnum.FULL_MANAGEMENT],
    RoleEnum.RESELLER: [PermissionEnum.ORG_MANAGEMENT],
    RoleEnum.ORG_ADMIN: [PermissionEnum.CONTENT_MANAGEMENT, PermissionEnum.REPORTING],
    RoleEnum.ORG_EDITOR: [PermissionEnum.REPORTING],
    RoleEnum.ORG_VIEWER: [PermissionEnum.REPORTING],
}
# Definir acciones permitidas por permiso
PERMISSION_ACTIONS = {
    PermissionEnum.FULL_MANAGEMENT: [action for action in ActionEnum],
    PermissionEnum.ORG_MANAGEMENT: [
        ActionEnum.CREATE,
        ActionEnum.READ,
        ActionEnum.UPDATE,
        ActionEnum.DELETE,
    ],
    PermissionEnum.CONTENT_MANAGEMENT: [
        ActionEnum.CREATE,
        ActionEnum.READ,
        ActionEnum.UPDATE,
    ],
    PermissionEnum.REPORTING: [ActionEnum.READ],
}

# tables
user_organization = db.Table(
    "user_organization",
    db.Column("user_id", db.String(36), db.ForeignKey("users.id"), primary_key=True),
    db.Column(
        "organization_id",
        db.Integer,
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Index("ix_user_organization_user_id", "user_id"),
    db.Index("ix_user_organization_organization_id", "organization_id"),
    # "Tabla de relación entre usuarios y organizaciones.",
)


def short_uuid():
    """Return a short uppercase hexadecimal UUID."""

    return hex(uuid.uuid4().int & 0xFFFFFFFF)[2:].upper()


# Clases
class User(db.Model):
    """User model representing system users.

    It stores personal information, credentials, roles and organization
    membership.
    """

    __tablename__ = "users"
    id = db.Column(
        db.String(8),
        primary_key=True,
        unique=True,
        default=short_uuid,
        doc="Clave primaria única del usuario en formato UUID.",
    )
    username = db.Column(
        db.String(80),
        unique=True,
        nullable=False,
        index=True,
        doc="Nombre de usuario (String, único, no nulo, indexado). Utilizado para el login.",
    )
    email = db.Column(
        db.String(120),
        unique=True,
        nullable=False,
        index=True,
        doc="Dirección de correo electrónico (String, único, no nulo, indexado).",
    )
    full_name = db.Column(
        db.String(128),
        nullable=False,
        doc="Nombre completo del usuario (String, no nulo).",
    )
    password_hash = db.Column(
        db.String(255),
        nullable=False,
        doc="Hash de la contraseña (String). Almacena la contraseña de forma segura.",
    )
    profile_data = db.Column(
        db.JSON,
        nullable=False,
        default=dict,
        doc="Datos adicionales del perfil (JSON, valor por defecto: diccionario vacío). Permite almacenar información extra específica del usuario.",
    )
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        doc="Fecha de creación del usuario (DateTime).",
    )
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        doc="Fecha de última actualización del usuario (DateTime). Se actualiza automáticamente.",
    )
    active = db.Column(
        db.Boolean,
        default=True,
        doc="Estado de la cuenta (Boolean, valor por defecto: True). Indica si la cuenta está activa o inactiva.",
    )
    role = db.Column(
        db.Enum(RoleEnum),
        nullable=False,
        default=RoleEnum.ORG_VIEWER,
        doc="Rol del usuario (Enum, no nulo, valor por defecto: ORG_VIEWER). Define el rol del usuario en el sistema.",
    )
    # Relaciones
    reseller_packages = db.relationship(
        "ResellerPackage", backref="reseller", lazy="dynamic"
    )

    organizations = db.relationship(
        "Organization", secondary=user_organization, backref="users", lazy="dynamic"
    )

    def __repr__(self):
        """Representación en cadena del objeto User.
        Returns:
            str: Representación en cadena del usuario.
        """
        return f"<User {self.username}>"

    def set_password(self, password):
        """Set a secure hash for the user's password.

        Args:
            password (str): The plain text password.
        Raises:
            ValueError: If the password does not meet security requirements.
        """
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify whether a given password matches the stored hash.

        Args:
            password (str): Plain text password to verify.
        Returns:
            bool: ``True`` if the password matches, otherwise ``False``.
        """
        return check_password_hash(self.password_hash, password)

    def has_permission(self, permission_name, action_name, client_id=None):
        """Check whether the user has a specific permission and action.

        Args:
            permission_name (str): Permission name to check (e.g. ``full_management``).
            action_name (str): Action name to verify (e.g. ``create``).
            client_id (int, optional): Organization ID to check within.
        Returns:
            bool: ``True`` if the user has the permission and action, otherwise ``False``.
        """
        try:
            perm_enum = PermissionEnum(permission_name)
            action_enum = ActionEnum(action_name)

            # Verificar si el permiso está asignado al rol del usuario
            if perm_enum in ROLE_PERMISSIONS.get(self.role, []):
                # Verificar si la acción está permitida para ese permiso
                if action_enum in PERMISSION_ACTIONS.get(perm_enum, []):
                    if client_id:
                        return self.client_id == client_id or self.is_admin()
                    return True
        except ValueError:
            # Si alguno de los valores no está en las enumeraciones, retornar False
            return False
        return False

    def is_admin(self):
        """
        Verifica si el usuario tiene el rol de administrador.
        Returns:
            bool: True si el usuario tiene el rol de administrador, False en caso contrario.
        """
        return self.role == RoleEnum.ADMINISTRATOR

    def is_reseller(self):
        """
        Verifica si el usuario tiene el rol de reseller.
        Returns:
            bool: True si el usuario tiene el rol de reseller, False en caso contrario.
        """
        return self.role == RoleEnum.RESELLER

    def is_org_manager(self):
        """
        Verifica si es un administrador de organización.
        Returns:
            bool: True si es un administrador de organización, False en caso contrario.
        """
        return self.role == RoleEnum.ORG_ADMIN

    def is_client_user(self, client_id):
        """
        Verifica si el usuario pertenece a un cliente específico.
        Args:
            client_id (int): El ID del cliente a verificar.
        Returns:
            bool: True si el usuario pertenece al cliente, False en caso contrario.
        """
        return self.client_id == client_id

    def have_role(self, role):
        """
        Verifica si el usuario tiene un rol específico.
        Args:
            role (RoleEnum): El rol a verificar.
        Returns:
            bool: True si el usuario tiene el rol especificado, False en caso contrario.
        """
        return self.role == role

    def get_role(self):
        """Mostrar el nombre descriptivo del rol"""
        return self.role.description

    @classmethod
    def get_by_username(self, username):
        """
        Obtiene un usuario por su nombre de usuario.
        Args:
            username (str): Nombre de usuario.
        Returns:
            User or None: El usuario si existe, None en caso contrario.
        """
        return self.query.filter_by(username=username).first()

    @classmethod
    # @lru_cache(maxsize=32)
    def get_by_email(self, email):
        """
        Obtiene un usuario por su correo electrónico.
        Args:
            email (str): Correo electrónico.
        Returns:
            User or None: El usuario si existe, None en caso contrario.
        """
        return self.query.filter_by(email=email).first()

    def assign_organization(self, organization_id):
        """
        Asigna una organización a este usuario.
        Args:
            organization_id (int): ID de la organización a asignar.
        """
        organization = Organization.query.get(organization_id)
        if organization:
            self.organizations.append(organization)

    def unassign_organization(self, organization_id):
        """
        Desasigna una organización de este usuario.
        Args:
            organization_id (int): ID de la organización a desasignar.
        """
        organization = Organization.query.get(organization_id)
        if organization in self.organizations:
            self.organizations.remove(organization)

    # Extended profile properties
    def _ensure_profile_data(self):
        """Ensure profile_data is a dict."""
        if self.profile_data is None:
            self.profile_data = {}

    @property
    def avatar_path(self) -> str:
        """Get avatar path from profile_data."""
        if self.profile_data is None:
            return None
        return self.profile_data.get(ProfileDataKeys.AVATAR_PATH)

    @avatar_path.setter
    def avatar_path(self, value: str):
        """Set avatar path in profile_data."""
        self._ensure_profile_data()
        # Create new dict to ensure change detection
        new_data = {**self.profile_data}
        if value is None:
            new_data.pop(ProfileDataKeys.AVATAR_PATH, None)
        else:
            new_data[ProfileDataKeys.AVATAR_PATH] = value
        self.profile_data = new_data

    @property
    def birthday(self) -> str:
        """Get birthday from profile_data (YYYY-MM-DD format)."""
        if self.profile_data is None:
            return None
        return self.profile_data.get(ProfileDataKeys.BIRTHDAY)

    @birthday.setter
    def birthday(self, value: str):
        """Set birthday in profile_data (YYYY-MM-DD format)."""
        self._ensure_profile_data()
        new_data = {**self.profile_data}
        if value is None:
            new_data.pop(ProfileDataKeys.BIRTHDAY, None)
        else:
            new_data[ProfileDataKeys.BIRTHDAY] = value
        self.profile_data = new_data

    @property
    def last_access(self) -> str:
        """Get last access timestamp (ISO format)."""
        if self.profile_data is None:
            return None
        return self.profile_data.get(ProfileDataKeys.LAST_ACCESS)

    @last_access.setter
    def last_access(self, value: str):
        """Set last access timestamp (ISO format)."""
        self._ensure_profile_data()
        new_data = {**self.profile_data}
        if value is None:
            new_data.pop(ProfileDataKeys.LAST_ACCESS, None)
        else:
            new_data[ProfileDataKeys.LAST_ACCESS] = value
        self.profile_data = new_data

    @property
    def avatar_url(self) -> str:
        """Get full avatar URL (or default if no avatar)."""
        from flask import current_app

        from app.core.services.avatar_service import AvatarService

        avatar_path = self.avatar_path
        if not avatar_path:
            try:
                return current_app.config.get("AVATAR_DEFAULT", "/img/avatar.png")
            except RuntimeError:
                # No app context
                return "/img/avatar.png"

        # Use AvatarService to generate URL
        try:
            url = AvatarService.get_avatar_url(avatar_path)
            if url:
                return url
        except RuntimeError:
            # Fallback if no app context
            pass

        # Fallback default
        try:
            return current_app.config.get("AVATAR_DEFAULT", "/img/avatar.png")
        except RuntimeError:
            return "/img/avatar.png"

    def update_last_access(self):
        """Update last_access timestamp to current UTC time."""
        from datetime import datetime

        self.last_access = datetime.utcnow().isoformat()


class Organization(db.Model):
    """Modelo que representa a los clientes u organizaciones en el sistema."""

    __tablename__ = "organizations"
    id = db.Column(
        db.Integer, primary_key=True, doc="Clave primaria única del cliente."
    )
    name = db.Column(
        db.String(100), nullable=False, doc="Nombre del cliente (String, no nulo)."
    )
    description = db.Column(
        db.String(255),
        doc="Descripción del cliente. Proporciona información adicional sobre el cliente u organización.",
    )
    nit = db.Column(
        db.String(50),
        nullable=True,
        doc="Número de identificación tributaria de la organización (opcional).",
    )
    contact = db.Column(
        db.String(100),
        nullable=True,
        doc="Nombre de la persona de contacto de la organización (opcional).",
    )
    address = db.Column(
        db.String(150),
        nullable=True,
        doc="Dirección física de la organización (opcional).",
    )
    phone = db.Column(
        db.String(50),
        nullable=True,
        doc="Número de teléfono de la organización (opcional).",
    )
    profile_data = db.Column(
        db.JSON,
        default=dict,
        doc="Datos adicionales del cliente (JSON, valor por defecto: diccionario vacío). Permite almacenar información extra específica del cliente.",
    )
    reseller_id = db.Column(
        db.Integer,
        db.ForeignKey("reseller_packages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Relación opcional con el paquete de reseller",
    )
    created_at = db.Column(
        db.DateTime, default=datetime.utcnow, doc="Fecha de creación del cliente."
    )
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        doc="Fecha de última actualización del cliente.",
    )
    active = db.Column(
        db.Boolean,
        default=True,
        doc="Estado del cliente (Boolean, valor por defecto: True). Indica si el cliente está activo o inactivo.",
    )
    # Relación con ResellerPackage
    reseller_package = db.relationship("ResellerPackage", backref="organizations")

    def __repr__(self):
        """Representación en cadena del objeto Organization.
        Returns:
            str: Representación en cadena del cliente.
        """
        return f"<Organization {self.name}>"

    @property
    def get_reseller(self):
        """
        Obtiene el usuario reseller asociado a la organización, si existe.
        Returns:
            User or None: El usuario reseller si existe, None en caso contrario
        """
        if self.reseller_package:
            return User.query.get(self.reseller_package.reseller_id)
        return None

    def get_users(self):
        """
        Devuelve los ID de los usuarios asociados a este cliente.
        Returns:
            list: Lista de IDs de usuarios.
        """
        return [user.id for user in self.users]


class ResellerPackage(db.Model):
    __tablename__ = "reseller_packages"
    id = db.Column(
        db.Integer,
        primary_key=True,
        doc="Clave primaria única del paquete de reseller.",
    )
    reseller_id = db.Column(
        db.String(8),
        db.ForeignKey("users.id"),
        nullable=False,
        doc="ID del usuario reseller (UUID).",
    )

    max_clients = db.Column(
        db.Integer,
        default=5,
        nullable=False,
        doc="Número máximo de clientes permitidos en este paquete de reseller.",
    )
    current_clients = db.Column(
        db.Integer,
        default=0,
        nullable=False,
        doc="Total de clientes asignados hasta el momento a ese reseller.",
    )

    # Constraint a nivel de base de datos
    __table_args__ = (
        db.CheckConstraint("current_clients <= max_clients", name="check_client_limit"),
    )

    def add_client(self):
        """
        Verifica si el reseller puede crear más clientes.
        Returns:
            bool: True si puede crear más clientes, False en caso contrario.
        """
        return self.current_clients < self.max_clients

    def increase_client(self):
        """
        Incrementa el contador de clientes.
        """
        self.current_clients += 1
        db.session.commit()

    def decrease_client(self):
        """
        Decrementa el contador de clientes.
        """
        if self.current_clients > 0:
            self.current_clients -= 1
            db.session.commit()

    def get_available_slots(self):
        """
        Obtiene el número de espacios disponibles para nuevos clientes.
        Returns:
            int: Número de espacios disponibles
        """
        return max(0, self.max_clients - self.current_clients)

    def assign_client(self, organization):
        """
        Asigna un cliente a este reseller si hay espacios disponibles.
        Args:
            client (Client): Cliente a asignar
        Returns:
            bool: True si se asignó correctamente, False en caso contrario
        """
        if not self.add_client():
            return False

        organization.reseller_id = self.id
        self.increase_client()
        return True

    def unassign_client(self, organizarion):
        """
        Desasigna un cliente de este reseller.
        Args:
            client (Client): Cliente a desasignar
        Returns:
            bool: True si se desasignó correctamente, False en caso contrario
        """
        if not self.reseller_id == organizarion.reseller_id:
            return False

        organizarion.reseller_package_id = None
        self.decrease_client()
        return True

    def get_all_users_clients(self):
        """
        Obtiene el listado de todos los usuarios que son parte de los clientes de este reseller.

        Returns:
            list: Lista de usuarios asociados a los clientes del reseller.
        """
        users = []
        for organization in self.organizations:
            users.append(organization.users)
        return users


class MaintenanceDrone(db.Model):
    """Drone registered for maintenance and flight-hour tracking."""

    __tablename__ = "maintenance_drones"

    id = db.Column(db.Integer, primary_key=True)
    serial_number = db.Column(db.String(80), nullable=False, unique=True, index=True)
    brand = db.Column(db.String(80), nullable=False)
    model = db.Column(db.String(120), nullable=False)
    flight_hours = db.Column(db.Numeric(10, 1), nullable=False, default=0)
    status = db.Column(db.String(40), nullable=False, default="Aeronavegable")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    def __repr__(self):
        return f"<MaintenanceDrone {self.brand} {self.model} {self.serial_number}>"


class PilotProfile(db.Model):
    """Operational pilot profile used by the calendar module."""

    __tablename__ = "pilot_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(8), db.ForeignKey("users.id"), nullable=True, index=True)
    username = db.Column(db.String(80), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(40), nullable=False, default="pilot")
    first_name = db.Column(db.String(90), nullable=False)
    last_name = db.Column(db.String(90), nullable=False)
    document_number = db.Column(db.String(50), nullable=True, index=True)
    phone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    certification_status = db.Column(db.String(40), nullable=False, default="Vigente")
    status = db.Column(db.String(30), nullable=False, default="active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    user = db.relationship("User", backref="pilot_profiles")
    certifications = db.relationship(
        "PilotCertification",
        back_populates="pilot",
        cascade="all, delete-orphan",
    )
    activities = db.relationship("OperationalActivity", back_populates="pilot")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


class PilotCertification(db.Model):
    __tablename__ = "pilot_certifications"

    id = db.Column(db.Integer, primary_key=True)
    pilot_id = db.Column(db.Integer, db.ForeignKey("pilot_profiles.id"), nullable=False, index=True)
    name = db.Column(db.String(140), nullable=False)
    issuer = db.Column(db.String(120), nullable=True)
    certificate_number = db.Column(db.String(90), nullable=True)
    issued_at = db.Column(db.Date, nullable=True)
    expires_at = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(40), nullable=False, default="Vigente")
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    pilot = db.relationship("PilotProfile", back_populates="certifications")


class OperationalActivity(db.Model):
    __tablename__ = "operational_activities"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(140), nullable=False)
    operation_type = db.Column(db.String(80), nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False, index=True)
    ends_at = db.Column(db.DateTime, nullable=False, index=True)
    duration_minutes = db.Column(db.Integer, nullable=False)
    place = db.Column(db.String(180), nullable=False)
    client_project = db.Column(db.String(160), nullable=True)
    farm_name = db.Column(db.String(160), nullable=True)
    paddocks = db.Column(db.Text, nullable=True)
    area_hectares = db.Column(db.Numeric(10, 2), nullable=True)
    rest_days = db.Column(db.Integer, nullable=True)
    lot_code = db.Column(db.String(80), nullable=True)
    pilot_id = db.Column(db.Integer, db.ForeignKey("pilot_profiles.id"), nullable=False, index=True)
    drone_id = db.Column(db.Integer, db.ForeignKey("maintenance_drones.id"), nullable=False, index=True)
    observations = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="scheduled", index=True)
    created_by_id = db.Column(db.String(8), db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    cancelled_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    pilot = db.relationship("PilotProfile", back_populates="activities")
    drone = db.relationship("MaintenanceDrone", backref="operational_activities")
    created_by = db.relationship("User", backref="created_operational_activities")
    logs = db.relationship(
        "OperationalActivityLog",
        back_populates="activity",
        cascade="all, delete-orphan",
    )


class OperationalActivityLog(db.Model):
    __tablename__ = "operational_activity_logs"

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("operational_activities.id"), nullable=False, index=True)
    user_id = db.Column(db.String(8), db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(40), nullable=False)
    message = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    activity = db.relationship("OperationalActivity", back_populates="logs")
    user = db.relationship("User", backref="operational_activity_logs")


class OperationBillingRecord(db.Model):
    """Billing data linked to a completed operational activity."""

    __tablename__ = "operation_billing_records"

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("operational_activities.id"), nullable=False, unique=True, index=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=True, index=True)
    source_item = db.Column(db.Integer, nullable=True, unique=True, index=True)
    farm_name = db.Column(db.String(160), nullable=True, index=True)
    paddock_name = db.Column(db.String(160), nullable=True)
    area_hectares = db.Column(db.Numeric(10, 2), nullable=True)
    scheduled_date = db.Column(db.Date, nullable=True, index=True)
    executed_date = db.Column(db.Date, nullable=True, index=True)
    billing_cut = db.Column(db.String(40), nullable=True, index=True)
    billing_month = db.Column(db.String(40), nullable=True, index=True)
    unit_price = db.Column(db.Numeric(14, 2), nullable=True)
    invoice_total = db.Column(db.Numeric(14, 2), nullable=True)
    invoice_number = db.Column(db.String(80), nullable=True, index=True)
    pilot_name = db.Column(db.String(160), nullable=True)
    operation_hours = db.Column(db.Numeric(8, 2), nullable=True)
    hectares_per_hour = db.Column(db.Numeric(8, 2), nullable=True)
    observations = db.Column(db.Text, nullable=True)
    raw_payload = db.Column(db.JSON, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    activity = db.relationship("OperationalActivity", backref=db.backref("billing_record", uselist=False))
    organization = db.relationship("Organization", backref="operation_billing_records")


class PilotDevice(db.Model):
    __tablename__ = "pilot_devices"

    id = db.Column(db.Integer, primary_key=True)
    pilot_id = db.Column(db.Integer, db.ForeignKey("pilot_profiles.id"), nullable=False, index=True)
    device_fingerprint = db.Column(db.String(128), nullable=False, index=True)
    user_agent = db.Column(db.String(255), nullable=True)
    is_authorized = db.Column(db.Boolean, nullable=False, default=True)
    first_access_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_access_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    pilot = db.relationship("PilotProfile", backref="devices")


class PilotFlightLog(db.Model):
    __tablename__ = "pilot_flight_logs"

    id = db.Column(db.Integer, primary_key=True)
    pilot_id = db.Column(db.Integer, db.ForeignKey("pilot_profiles.id"), nullable=False, index=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("operational_activities.id"), nullable=True, index=True)
    drone_id = db.Column(db.Integer, db.ForeignKey("maintenance_drones.id"), nullable=False, index=True)
    flight_date = db.Column(db.Date, nullable=False, index=True)
    started_at = db.Column(db.DateTime, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=False)
    flight_minutes = db.Column(db.Integer, nullable=False)
    takeoff_location = db.Column(db.String(180), nullable=True)
    landing_location = db.Column(db.String(180), nullable=True)
    weather = db.Column(db.String(120), nullable=True)
    battery_cycles = db.Column(db.Integer, nullable=True)
    total_hectares = db.Column(db.Numeric(10, 2), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    pilot = db.relationship("PilotProfile", backref="flight_logs")
    activity = db.relationship("OperationalActivity", backref="flight_logs")
    drone = db.relationship("MaintenanceDrone", backref="pilot_flight_logs")


class PilotOperationReport(db.Model):
    __tablename__ = "pilot_operation_reports"

    id = db.Column(db.Integer, primary_key=True)
    pilot_id = db.Column(db.Integer, db.ForeignKey("pilot_profiles.id"), nullable=False, index=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("operational_activities.id"), nullable=True, index=True)
    report_type = db.Column(db.String(60), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="open", index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    pilot = db.relationship("PilotProfile", backref="operation_reports")
    activity = db.relationship("OperationalActivity", backref="pilot_reports")


# Funciones de utilidad.
# Funciones de utilidad adicionales


@lru_cache(maxsize=128)
def check_permission(user_id, permission_name, action_name, client_id=None):
    """
    Verifica permisos de forma centralizada y cacheada.
    Args:
        user_id: (int): ID del usuario
        permission_name (str): Nombre del permiso a verificar (ej: 'full_management')
        action_name (str): Nombre de la acción a verificar (ej: 'create')
        client_id (int): ID de la organización (opcional)

    Returns:
        bool: True si el usuario tiene el permiso, False en caso contrario

    """
    user = User.query.get(user_id)
    if not user:
        return False

    return user.has_permission(permission_name, action_name, client_id)


def verify_user_credentials(username, password):
    """
    Verifica las credenciales de un usuario de forma segura.

    Args:
        username (str): Nombre de usuario
        password (str): Contraseña en texto plano

    Returns:
        User or None: El usuario si las credenciales son correctas, None en caso contrario
    """
    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password) and user.active:
        return user
    return None


def verify_user_in_organization(user_id: str, org_id: int) -> bool:
    """
    Verifica si un usuario pertenece a una organización específica.

    Args:
        user_id (str): ID del usuario (UUID en formato string).
        org_id (int): ID de la organización.

    Returns:
        bool: True si el usuario pertenece a la organización o tiene permisos especiales,
              False en caso contrario.
    """
    # Obtener el usuario por su ID
    user = User.query.get(user_id)
    if not user:
        return False  # El usuario no existe, retorna False

    # Si el usuario es administrador, tiene acceso implícito a todas las organizaciones
    if user.is_admin():
        return True

    # Verificar si el usuario es un reseller y la organización pertenece a su paquete
    if user.is_reseller():
        # Obtener el paquete del reseller asociado al usuario
        reseller_package = ResellerPackage.query.filter_by(reseller_id=user_id).first()
        if reseller_package:
            # Verificar si la organización está en las organizaciones del paquete del reseller
            organization = Organization.query.filter_by(
                id=org_id, reseller_id=reseller_package.id
            ).first()
            if organization:
                return True  # La organización pertenece al reseller

    # Verificar si el usuario está directamente asociado a la organización
    # Usamos la relación 'organizations' del modelo User
    return any(org.id == org_id for org in user.organizations)


def get_clients_for_user(user_id: str):
    """
    Obtiene el listado de clientes asignados a un usuario específico.
    Args:
        user_id (str): ID del usuario (UUID en formato string).
    Returns:
        list: Lista de organizaciones asignadas al usuario.
    """
    # Obtener el usuario por su ID
    user = User.query.get(user_id)
    if not user:
        return []
    # Si el usuario es administrador, obtener todas las organizaciones
    if user.is_admin():
        return Organization.query.all()
    # Si el usuario es reseller, obtener las organizaciones asignadas a su paquete
    if user.is_reseller():
        reseller_package = (
            ResellerPackage.query.options(joinedload(ResellerPackage.organizations))
            .filter_by(reseller_id=user_id)
            .first()
        )
        if reseller_package:
            return reseller_package.organizations
    # Si el usuario no es administrador ni reseller, obtener las organizaciones a las que está directamente asignado
    # ``User.organizations`` usa ``lazy="dynamic"`` y no admite joinedload.
    # Ejecutar la consulta dinamica evita el error 500 al cargar el dashboard.
    return user.organizations.all()
