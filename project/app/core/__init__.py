# -*-coding:utf-8-*-
"""Core module for Yet Another Flask Survival Kit (YAFSK)

Author:
    Johnny De Castro <j@jdcastro.co>

Copyright:
    (c) 2024 - 2025 Johnny De Castro. All rights reserved.

License:
    Apache License 2.0 - http://www.apache.org/licenses/LICENSE-2.0

"""
"""Application core blueprints and route imports."""

from pathlib import Path

from flask import Blueprint, current_app, send_from_directory

from .controller import login_required
from .services.avatar_service import AvatarService

core = Blueprint("core", __name__, url_prefix="/", template_folder="templates")

core_api = Blueprint("core_api", __name__, url_prefix="/api/core")
core_api_v1 = Blueprint("core_api_v1", __name__, url_prefix="/api/v1/core")


def _serve_static_asset(folder: str, key: str):
    base = Path(current_app.root_path) / "static" / "assets" / folder
    response = send_from_directory(str(base), key)
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response


@core.route("/css/<path:key>")
def serve_css(key: str):
    return _serve_static_asset("css", key)


@core.route("/js/<path:key>")
def serve_js(key: str):
    return _serve_static_asset("js", key)


@core.route("/img/<path:key>")
def serve_img(key: str):
    return _serve_static_asset("img", key)


@core.route("/webfonts/<path:key>")
def serve_webfont(key: str):
    return _serve_static_asset("webfonts", key)


# Avatar serving route
@core.route("/avatars/<path:key>")
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

    # Pass the full key so send_from_directory/safe_join rejects any
    # path traversal (e.g. "../../etc/passwd") with a 404.
    response = send_from_directory(str(base), key)
    # Add cache headers (1 day for avatars)
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


from . import api_routes, web_routes
from .api.v1 import routes as v1_routes
