"""Tenant-aware access helpers for media assets."""

from flask_jwt_extended import get_jwt_identity

from app.core.models import User, get_clients_for_user

from .models import Asset


def current_organization_ids() -> set[int] | None:
    """Return None for platform administrators, otherwise accessible org IDs."""
    user_id = get_jwt_identity()
    user = User.query.get(user_id) if user_id else None
    if user and user.is_admin():
        return None
    return (
        {organization.id for organization in get_clients_for_user(user_id)}
        if user_id
        else set()
    )


def accessible_asset_query():
    organization_ids = current_organization_ids()
    if organization_ids is None:
        return Asset.query
    if not organization_ids:
        return Asset.query.filter(Asset.id.is_(None))
    return Asset.query.filter(Asset.organization_id.in_(organization_ids))


def default_upload_organization_id() -> int | None:
    organization_ids = current_organization_ids()
    if organization_ids is not None and len(organization_ids) == 1:
        return next(iter(organization_ids))
    return None

def accessible_asset_for_storage_key(key: str):
    normalized = key.replace("\\", "/").strip("/")
    query = accessible_asset_query()
    asset = query.filter(Asset.storage_key == key).first()
    if asset:
        return asset
    asset = query.join(Asset.variants).filter_by(storage_key=key).first()
    if asset:
        return asset
    parts = normalized.split("/")
    if len(parts) >= 2 and parts[0] in {"cache", "display"}:
        return query.filter(Asset.uuid == parts[1]).first()
    return None