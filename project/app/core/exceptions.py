"""Core module exceptions.

This module defines custom exceptions for the core module,
used for error handling in services and API endpoints.
"""


class CoreException(Exception):
    """Base exception for core module."""

    pass


class AvatarValidationError(CoreException):
    """Raised when avatar validation fails."""

    pass


class AvatarStorageError(CoreException):
    """Raised when avatar file operations fail."""

    pass


class ProfileDataError(CoreException):
    """Raised when profile data is invalid or inconsistent."""

    pass


class ProfileUpdateError(CoreException):
    """Raised when profile update fails due to validation or constraints."""

    pass


class RateLimitExceededError(CoreException):
    """Raised when API rate limit is exceeded."""

    pass
