"""Application core blueprints and route imports."""

import os
from flask import Blueprint, send_from_directory, current_app

from .controller import login_required
from .services.avatar_service import AvatarService

core = Blueprint("core", __name__, url_prefix="/", template_folder="templates")

core_api = Blueprint("core_api", __name__, url_prefix="/api/core")
core_api_v1 = Blueprint("core_api_v1", __name__, url_prefix="/api/v1/core")


# Avatar serving route
@core.route('/avatars/<path:key>')
@login_required
def serve_avatar(key: str):
    """Serve avatar files from storage directory.

    Args:
        key: Relative path to avatar file (e.g., user_id/filename)

    Returns:
        The avatar image file with cache headers.
    """
    # Get base storage directory (handles Docker env properly)
    base = AvatarService.ensure_storage_directory()

    # Extract directory and filename from the key path
    directory = os.path.join(str(base), os.path.dirname(key))
    filename = os.path.basename(key)

    # send_from_directory handles path security validation
    response = send_from_directory(directory, filename)
    # Add cache headers (1 day for avatars)
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response


from . import api_routes, web_routes
from .api.v1 import routes as v1_routes
