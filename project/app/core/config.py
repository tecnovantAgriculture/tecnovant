"""Core module configuration.

This module defines configuration specific to the core module,
such as avatar upload settings, profile data constraints, and
API rate limiting for core endpoints.
"""

import os
from datetime import timedelta


class CoreConfig:
    """Configuration for core module."""

    # Avatar upload settings
    # Default: project/storage/profile/avatars (can be overridden via AVATAR_UPLOAD_DIR env var)
    AVATAR_UPLOAD_DIR = os.environ.get("AVATAR_UPLOAD_DIR", "")
    AVATAR_ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
    AVATAR_MAX_SIZE = 5 * 1024 * 1024  # 5 MB
    AVATAR_URL_PREFIX = "/avatars"
    AVATAR_DEFAULT = "/img/avatar.png"

    # Profile data validation
    BIRTHDAY_DATE_FORMAT = "%Y-%m-%d"
    MAX_FULL_NAME_LENGTH = 128
    MAX_EMAIL_LENGTH = 120

    # API rate limiting (requests per minute)
    RATE_LIMIT_PROFILE_GET = 100
    RATE_LIMIT_PROFILE_UPDATE = 10
    RATE_LIMIT_AVATAR_UPLOAD = 5
    RATE_LIMIT_AVATAR_DELETE = 5

    # Login rate limiting
    RATE_LIMIT_LOGIN_PER_USER = 5
    RATE_LIMIT_LOGIN_PER_IP = 20
    RATE_LIMIT_LOGIN_WINDOW = 60  # segundos
    RATE_LIMIT_LOCKOUT_MAX_ATTEMPTS = 5
    RATE_LIMIT_LOCKOUT_DURATION = 300  # segundos (5 minutos)

    # Login rate limiting
    RATE_LIMIT_LOGIN_PER_USER = 5
    RATE_LIMIT_LOGIN_PER_IP = 20
    RATE_LIMIT_LOGIN_WINDOW = 60  # segundos
    RATE_LIMIT_LOCKOUT_MAX_ATTEMPTS = 5
    RATE_LIMIT_LOCKOUT_DURATION = 300  # segundos (5 minutos)

    # Security
    PROFILE_DATA_ALLOWED_KEYS = {"avatar_path", "birthday", "last_access"}
    PROFILE_UPDATE_ALLOWED_FIELDS = {"full_name", "email", "birthday"}

    # JWT token expiration (for reference)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=7)
