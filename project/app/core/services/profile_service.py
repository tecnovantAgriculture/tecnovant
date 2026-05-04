"""Profile service for extended user profile operations.

This service handles business logic for user profile updates,
avatar management, and extended profile data (birthday, last_access).
"""

import re
from datetime import datetime, date
from typing import Optional, Dict, Any, Tuple
from flask import current_app
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.core.models import User
from app.core.services.avatar_service import AvatarService
from app.core.constants import ProfileDataKeys
from app.core.exceptions import ProfileUpdateError, ProfileDataError, AvatarStorageError


class ProfileService:
    """Service for profile-related business logic."""

    @classmethod
    def get_extended_profile(cls, user: User) -> Dict[str, Any]:
        """Get extended profile data including avatar, birthday, last_access.

        Args:
            user: User instance.

        Returns:
            Dictionary with extended profile data.
        """
        # Get avatar URL
        avatar_path = user.avatar_path
        avatar_url = AvatarService.get_avatar_url(avatar_path)
        
        # Get extended fields
        birthday = user.birthday
        last_access = user.last_access
        
        # Organizations
        organizations = [
            {"id": org.id, "name": org.name}
            for org in user.organizations.all()
        ]
        
        # Role display
        role_display = user.get_role()
        
        # Build response matching legacy profile structure plus extensions
        result = {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value,
            "organizations": organizations,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "updated_at": user.updated_at.isoformat() if user.updated_at else None,
            # Extended fields
            "avatar_url": avatar_url,
            "birthday": birthday,
            "last_access": last_access,
            "role_display": role_display,
        }
        
        return result

    @classmethod
    def update_profile(cls, user: User, data: Dict[str, Any]) -> bool:
        """Update user profile fields.

        Args:
            user: User instance to update.
            data: Dictionary with fields to update (full_name, email, birthday).

        Returns:
            True if update successful, False otherwise.
        """
        updated = False
        
        # Validate allowed fields
        allowed_fields = {"full_name", "email", "birthday"}
        for key in data:
            if key not in allowed_fields:
                raise ProfileUpdateError(f"Field '{key}' is not allowed for profile update")
        
        # Update full_name
        if "full_name" in data:
            full_name = data["full_name"].strip()
            if not full_name:
                raise ProfileUpdateError("Full name cannot be empty")
            if full_name != user.full_name:
                user.full_name = full_name
                updated = True
        
        # Update email
        if "email" in data:
            new_email = data["email"].strip().lower()
            if not new_email:
                raise ProfileUpdateError("Email cannot be empty")
            # Basic email format validation
            if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", new_email):
                raise ProfileUpdateError("Invalid email format")
            if new_email != user.email:
                # Check uniqueness
                existing = User.query.filter(
                    User.email == new_email,
                    User.id != user.id
                ).first()
                if existing:
                    raise ProfileUpdateError("Email address is already in use")
                user.email = new_email
                updated = True
        
        # Update birthday
        if "birthday" in data:
            birthday_str = data["birthday"]
            validated_birthday = cls.validate_birthday(birthday_str)
            if validated_birthday != user.birthday:
                user.birthday = validated_birthday
                updated = True
        
        return updated

    @classmethod
    def update_last_access(cls, user: User) -> None:
        """Update user's last_access timestamp.

        Args:
            user: User instance.
        """
        now_iso = datetime.utcnow().isoformat()
        user.last_access = now_iso

    @classmethod
    def set_avatar(cls, user: User, avatar_path: Optional[str]) -> bool:
        """Set avatar path for user.

        Args:
            user: User instance.
            avatar_path: Relative path to avatar file (or None to remove).

        Returns:
            True if successful.
        """
        user.avatar_path = avatar_path
        return True

    @classmethod
    def replace_avatar(cls, user: User, file: FileStorage) -> Tuple[str, Optional[str]]:
        """Replace user's avatar with new file atomically.
        
        This method saves the new file, updates the user's avatar_path in the
        session, and returns the new and old avatar paths. The caller must
        commit the session. If the commit fails, the caller should delete the
        new file using AvatarService.delete_avatar(new_path). If commit succeeds,
        the caller should delete the old file (if different).
        
        Args:
            user: User instance.
            file: Validated avatar file.
            
        Returns:
            Tuple of (new_avatar_path, old_avatar_path).
            
        Raises:
            AvatarStorageError: If file save fails.
        """
        old_avatar_path = user.avatar_path
        new_avatar_path = AvatarService.save_avatar(user.id, file)
        user.avatar_path = new_avatar_path
        return new_avatar_path, old_avatar_path

    @classmethod
    def remove_avatar(cls, user: User) -> Optional[str]:
        """Remove user's avatar atomically.
        
        This method updates the user's avatar_path to None in the session
        and returns the old avatar path. The caller must commit the session.
        If commit succeeds, the caller should delete the old file.
        
        Args:
            user: User instance.
            
        Returns:
            Old avatar path, or None if no avatar.
        """
        old_avatar_path = user.avatar_path
        user.avatar_path = None
        return old_avatar_path

    @classmethod
    def validate_birthday(cls, birthday_str: Optional[str]) -> Optional[str]:
        """Validate birthday format and ensure it's not in the future.

        Args:
            birthday_str: Birthday in ISO 8601 date format (YYYY-MM-DD).

        Returns:
            Validated birthday string or None if invalid.
        """
        if not birthday_str:
            return None
        
        birthday_str = birthday_str.strip()
        if not birthday_str:
            return None
        
        try:
            # Parse date
            birth_date = datetime.strptime(birthday_str, "%Y-%m-%d").date()
            today = date.today()
            if birth_date > today:
                raise ProfileDataError("Birthday cannot be in the future")
            return birthday_str  # Already normalized YYYY-MM-DD
        except ValueError:
            raise ProfileDataError("Invalid date format. Use YYYY-MM-DD")