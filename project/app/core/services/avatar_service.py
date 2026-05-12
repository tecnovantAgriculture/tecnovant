"""Avatar service for handling avatar upload, validation, and storage.

This service manages avatar file operations including validation,
storage, path generation, and cleanup. It ensures secure handling
of user-uploaded avatar images.
"""

import os
import shutil
import time
from pathlib import Path
from typing import Optional, Tuple

from flask import current_app
from werkzeug.datastructures import FileStorage

from app.core.constants import AvatarConstants, ProfileDataKeys
from app.core.exceptions import AvatarStorageError, AvatarValidationError

# Try to import PIL for image validation (optional)
try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None


class AvatarService:
    """Service for avatar file operations."""

    @classmethod
    def validate_avatar(cls, file: FileStorage) -> Tuple[bool, str]:
        """Validate uploaded avatar file.

        Args:
            file: The uploaded file object.

        Returns:
            Tuple of (is_valid, error_message). If valid, error_message is empty.
        """
        # Check file exists
        if not file or file.filename == "":
            return False, "No file uploaded"

        # Validate file extension
        ext = cls._get_extension(file.filename)
        allowed_extensions = current_app.config.get(
            "AVATAR_ALLOWED_EXTENSIONS", AvatarConstants.ALLOWED_MIME_TYPES
        )
        if ext.lower() not in allowed_extensions:
            return (
                False,
                f"File type not allowed. Allowed: {', '.join(allowed_extensions)}",
            )

        # Validate MIME type
        mime_type = file.mimetype.lower() if file.mimetype else ""
        allowed_mime = AvatarConstants.ALLOWED_MIME_TYPES
        if mime_type not in allowed_mime:
            # Not a recognized MIME type, but we'll still try to validate via content
            pass

        # Validate file size
        max_size = current_app.config.get("AVATAR_MAX_SIZE", 5 * 1024 * 1024)
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        if size > max_size:
            mb = max_size / (1024 * 1024)
            return False, f"File size exceeds limit ({mb} MB)"

        # Validate image content and dimensions (if PIL available)
        if PIL_AVAILABLE:
            try:
                file.seek(0)
                img = Image.open(file)
                # Load image to validate it's valid (no need for verify() which closes file)
                img.load()
                width, height = img.size
                if (
                    width > AvatarConstants.MAX_DIMENSION
                    or height > AvatarConstants.MAX_DIMENSION
                ):
                    return (
                        False,
                        f"Image dimensions exceed {AvatarConstants.MAX_DIMENSION}px",
                    )
                if (
                    width < AvatarConstants.MIN_DIMENSION
                    or height < AvatarConstants.MIN_DIMENSION
                ):
                    return (
                        False,
                        f"Image dimensions below {AvatarConstants.MIN_DIMENSION}px",
                    )
                img.close()
            except Exception as e:
                return False, f"Invalid image: {str(e)}"
            finally:
                file.seek(0)
        else:
            # Fallback: attempt to read first few bytes to check magic numbers
            # For simplicity, we'll trust the extension and size validation
            # Could add basic magic number check for JPEG, PNG, WEBP
            pass

        return True, ""

    @classmethod
    def save_avatar(cls, user_id: str, file: FileStorage) -> str:
        """Save avatar file and return relative path.

        Args:
            user_id: The ID of the user.
            file: Validated avatar file.

        Returns:
            Relative path to the saved avatar (to be stored in profile_data).
        """
        # Ensure storage directory exists
        upload_dir = cls.ensure_storage_directory()

        # Generate unique filename
        timestamp = int(time.time())
        ext = cls._get_extension(file.filename).lower()
        filename = f"{user_id}_avatar_{timestamp}.{ext}"

        # Create user-specific subdirectory (optional)
        user_dir = upload_dir / user_id
        user_dir.mkdir(exist_ok=True)

        # Save file
        destination = user_dir / filename
        try:
            file.seek(0)  # Ensure we're at the start of the file
            file.save(destination)
        except Exception as e:
            raise AvatarStorageError(f"Failed to save avatar: {str(e)}")

        # Return relative path (user_id/filename)
        relative_path = f"{user_id}/{filename}"
        return relative_path

    @classmethod
    def delete_avatar(cls, avatar_path: str) -> bool:
        """Delete avatar file from storage.

        Args:
            avatar_path: Relative path to avatar file.

        Returns:
            True if file was deleted or doesn't exist, False on error.
        """
        if not avatar_path:
            return True

        upload_dir = Path(
            current_app.config.get("AVATAR_UPLOAD_DIR", "/var/www/avatars")
        )
        absolute_path = upload_dir / avatar_path

        # Ensure the path is within the upload directory (security)
        try:
            absolute_path.resolve().relative_to(upload_dir.resolve())
        except ValueError:
            # Path traversal attempt
            current_app.logger.warning(
                f"Invalid avatar path outside upload directory: {avatar_path}"
            )
            return False

        if absolute_path.exists():
            try:
                absolute_path.unlink()
                # Optionally remove empty user directory
                user_dir = absolute_path.parent
                if user_dir.exists() and not any(user_dir.iterdir()):
                    user_dir.rmdir()
                return True
            except Exception as e:
                current_app.logger.error(
                    f"Failed to delete avatar {avatar_path}: {str(e)}"
                )
                return False
        return True  # File doesn't exist, consider deletion successful

    @classmethod
    def get_avatar_url(cls, avatar_path: Optional[str]) -> Optional[str]:
        """Generate URL for avatar path.

        Args:
            avatar_path: Relative path stored in profile_data.

        Returns:
            Full URL to access the avatar, or None if no avatar.
        """
        if not avatar_path:
            return None

        url_prefix = current_app.config.get("AVATAR_URL_PREFIX", "/avatars")
        # Ensure no double slashes
        url_prefix = url_prefix.rstrip("/")
        avatar_path = avatar_path.lstrip("/")
        return f"{url_prefix}/{avatar_path}"

    @classmethod
    def ensure_storage_directory(cls) -> Path:
        """Ensure avatar storage directory exists.

        Defaults to <project-root>/storage/profile/avatars (same pattern as media).
        Can be overridden via AVATAR_UPLOAD_DIR env var.

        Returns:
            Path object for the storage directory.
        """
        # Check if env var is set AND is not empty
        env_upload_dir = os.environ.get("AVATAR_UPLOAD_DIR", "").strip()
        if env_upload_dir:
            upload_dir = Path(env_upload_dir)
        else:
            # Project root is one level above app/ (same pattern as media)
            project_root = os.path.abspath(
                os.path.join(current_app.root_path, os.pardir)
            )
            upload_dir = Path(
                os.path.join(project_root, "storage", "profile", "avatars")
            )

        upload_dir.mkdir(parents=True, exist_ok=True)
        return upload_dir

    @staticmethod
    def _get_extension(filename: str) -> str:
        """Extract file extension from filename."""
        return filename.rsplit(".", 1)[1].lower() if "." in filename else ""
