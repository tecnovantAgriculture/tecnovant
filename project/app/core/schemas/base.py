from marshmallow import fields
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema

from app.core.models import Organization, ResellerPackage, RoleEnum, User


class UserSchema(SQLAlchemyAutoSchema):
    role = fields.Enum(RoleEnum, by_value=True, dump_only=True)
    organizations = fields.List(fields.Integer(), dump_only=True)
    reseller_packages = fields.List(
        fields.Nested(
            lambda: ResellerPackageSchema(
                only=("id", "max_clients", "current_clients")
            ),
            dump_only=True,
        ),
        dump_only=True,
    )
    profile_data = fields.Raw(dump_only=True)

    class Meta:
        model = User
        exclude = ["password_hash"]
        include_relationships = False
        load_instance = False


class OrganizationSchema(SQLAlchemyAutoSchema):
    users = fields.List(
        fields.String(),
        attribute=lambda obj: [str(u.id) for u in obj.users],
        dump_only=True,
    )
    reseller_package = fields.Nested(
        lambda: ResellerPackageSchema(only=("id", "reseller", "max_clients")),
        dump_only=True,
    )
    nit = fields.String(allow_none=True)
    contact = fields.String(allow_none=True)
    address = fields.String(allow_none=True)
    phone = fields.String(allow_none=True)

    class Meta:
        model = Organization
        exclude = []
        load_instance = False


class ResellerPackageSchema(SQLAlchemyAutoSchema):
    reseller = fields.Nested(
        lambda: UserSchema(only=("id", "username")), dump_only=True
    )

    class Meta:
        model = ResellerPackage
        exclude = []
        load_instance = False
