"""Extended User Schema for versioned API endpoints.

This schema extends the base UserSchema with additional fields
for avatar, birthday, last_access, and computed properties.
"""

from datetime import date as _date

from marshmallow import fields, pre_dump, validate
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema

from app.core.constants import ProfileDataKeys
from app.core.models import User
from app.core.services.avatar_service import AvatarService

from .base import UserSchema as BaseUserSchema


class ExtendedUserSchema(BaseUserSchema):
    """Extended User Schema for v1 API endpoints.

    Includes:
    - avatar_url: Computed URL to user's avatar
    - birthday: Optional ISO 8601 date
    - last_access: Optional ISO 8601 datetime (read-only)
    - role_display: Human-readable role description
    - organizations: List of organization IDs
    """

    avatar_url = fields.String(attribute="avatar_url", dump_only=True)
    birthday = fields.Date(
        attribute="birthday",
        allow_none=True,
        validate=validate.Range(max=_date.today()),
    )
    last_access = fields.DateTime(attribute="last_access", dump_only=True)
    role_display = fields.String(attribute="get_role", dump_only=True)
    organizations = fields.List(fields.Integer(), dump_only=True)

    class Meta(BaseUserSchema.Meta):
        # Exclude raw profile_data field as we have separate fields
        exclude = ["profile_data"]
