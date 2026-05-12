"""Services for core module.

This package contains service classes for business logic related to
user profiles, avatar management, and other core functionality.
"""

from .avatar_service import AvatarService
from .profile_service import ProfileService

__all__ = ["AvatarService", "ProfileService"]
