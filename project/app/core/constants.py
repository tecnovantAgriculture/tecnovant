"""Core module constants.

This module defines constants used throughout the core module,
including role values, permission strings, and configuration defaults.
"""

from enum import Enum


class ProfileDataKeys(str, Enum):
    """Keys used in user.profile_data JSON."""

    AVATAR_PATH = "avatar_path"
    BIRTHDAY = "birthday"
    LAST_ACCESS = "last_access"


class AvatarConstants:
    """Constants related to avatar handling."""

    DEFAULT_EXTENSION = "png"
    MAX_DIMENSION = 2048  # pixels (supports high-DPI displays)
    MIN_DIMENSION = 32
    ALLOWED_MIME_TYPES = {
        "image/jpeg",
        "image/png",
        "image/webp",
    }


class RateLimitBuckets:
    """Rate limit bucket identifiers for core endpoints."""

    PROFILE_GET = "core.profile.get"
    PROFILE_UPDATE = "core.profile.update"
    AVATAR_UPLOAD = "core.avatar.upload"
    AVATAR_DELETE = "core.avatar.delete"


# Default values for profile fields
DEFAULT_PROFILE_DATA = {
    ProfileDataKeys.AVATAR_PATH: None,
    ProfileDataKeys.BIRTHDAY: None,
    ProfileDataKeys.LAST_ACCESS: None,
}

# Validation regex patterns
USERNAME_PATTERN = r"^[a-zA-Z0-9_\-\.]+$"
AVATAR_PATH_PATTERN = r"^[a-zA-Z0-9_\-\.\/]+$"
EMAIL_PATTERN = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
