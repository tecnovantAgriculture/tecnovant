"""Version 1 API routes for core module.

This module defines the versioned API endpoints for extended profile
and avatar functionality. All endpoints are registered under the
core_api_v1 blueprint with prefix /api/v1/core.
"""

from flask import jsonify, request, current_app
from flask_jwt_extended import get_jwt_identity, jwt_required
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import BadRequest, NotFound, InternalServerError

from . import core_api_v1
from app.extensions import db, limiter
from app.core.services.avatar_service import AvatarService
from app.core.services.profile_service import ProfileService
from app.core.models import User
from app.core.constants import ProfileDataKeys
from app.core.config import CoreConfig
from app.core.exceptions import AvatarValidationError, AvatarStorageError, ProfileUpdateError, ProfileDataError


def get_limit_key():
    """Return JWT identity for authenticated users, else remote address."""
    identity = get_jwt_identity()
    if identity:
        return str(identity)
    # fallback to IP address (should not happen for these endpoints)
    return get_remote_address()


# Extended Profile endpoints
@core_api_v1.route("/profile", methods=["GET"])
@jwt_required()
@limiter.limit(f"{CoreConfig.RATE_LIMIT_PROFILE_GET} per minute", key_func=get_limit_key)
def get_profile_v1():
    """Get extended profile data.

    Returns:
        JSON with extended user profile including avatar_url, birthday,
        last_access, organizations, role_display.
    """
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        raise NotFound("User not found")
    
    # Update last access timestamp
    ProfileService.update_last_access(user)
    db.session.commit()
    
    profile_data = ProfileService.get_extended_profile(user)
    return jsonify(profile_data), 200


@core_api_v1.route("/profile", methods=["PUT"])
@jwt_required()
@limiter.limit(f"{CoreConfig.RATE_LIMIT_PROFILE_UPDATE} per minute", key_func=get_limit_key)
def update_profile_v1():
    """Update profile fields (full_name, email, birthday).

    Request body:
        {
            "full_name": "string (optional)",
            "email": "string (optional)",
            "birthday": "string (ISO 8601 date, optional)"
        }

    Returns:
        JSON success message.
    """
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        raise NotFound("User not found")
    
    data = request.get_json()
    if not data:
        raise BadRequest("No data provided")
    
    try:
        updated = ProfileService.update_profile(user, data)
        if updated:
            db.session.commit()
            return jsonify({"msg": "Profile updated successfully"}), 200
        else:
            return jsonify({"msg": "No changes detected"}), 200
    except ProfileUpdateError as e:
        raise BadRequest(str(e))
    except ProfileDataError as e:
        raise BadRequest(str(e))
    except Exception as e:
        db.session.rollback()
        raise InternalServerError("Failed to update profile")


# Avatar endpoints
@core_api_v1.route("/profile/avatar", methods=["POST"])
@jwt_required()
@limiter.limit(f"{CoreConfig.RATE_LIMIT_AVATAR_UPLOAD} per minute", key_func=get_limit_key)
def upload_avatar():
    """Upload avatar image.

    Expects multipart/form-data with 'file' field containing image.

    Returns:
        JSON with avatar_url and success message.
    """
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        raise NotFound("User not found")
    
    if 'file' not in request.files:
        raise BadRequest("No file part")
    
    file = request.files['file']
    if not file or file.filename == '':
        raise BadRequest("No selected file")
    
    # Validate avatar
    is_valid, error_msg = AvatarService.validate_avatar(file)
    if not is_valid:
        raise BadRequest(error_msg)
    
    # Replace avatar atomically (saves file, updates user in session)
    try:
        new_avatar_path, old_avatar_path = ProfileService.replace_avatar(user, file)
    except AvatarStorageError as e:
        raise InternalServerError(f"Failed to save avatar: {str(e)}")
    
    try:
        db.session.commit()
    except Exception as e:
        # Rollback database changes
        db.session.rollback()
        # Clean up the newly saved file since update failed
        AvatarService.delete_avatar(new_avatar_path)
        # Log the error
        current_app.logger.error(f"Failed to commit avatar update for user {user.id}: {str(e)}")
        raise InternalServerError("Failed to update avatar in database")
    
    # After successful commit, delete old avatar file if exists and different
    if old_avatar_path and old_avatar_path != new_avatar_path:
        deleted = AvatarService.delete_avatar(old_avatar_path)
        if not deleted:
            current_app.logger.warning(f"Failed to delete old avatar file: {old_avatar_path}")
    
    # Generate avatar URL
    avatar_url = AvatarService.get_avatar_url(new_avatar_path)
    
    return jsonify({
        "avatar_url": avatar_url,
        "message": "Avatar uploaded successfully"
    }), 200


@core_api_v1.route("/profile/avatar", methods=["DELETE"])
@jwt_required()
@limiter.limit(f"{CoreConfig.RATE_LIMIT_AVATAR_DELETE} per minute", key_func=get_limit_key)
def delete_avatar():
    """Remove current avatar.

    Returns:
        JSON success message.
    """
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        raise NotFound("User not found")
    
    avatar_path = user.avatar_path
    
    # If no avatar, just return success
    if not avatar_path:
        return jsonify({"message": "No avatar to remove"}), 200
    
    # Remove avatar atomically (updates user in session)
    old_avatar_path = ProfileService.remove_avatar(user)
    
    try:
        db.session.commit()
    except Exception as e:
        # Rollback database changes
        db.session.rollback()
        current_app.logger.error(f"Failed to commit avatar removal for user {user.id}: {str(e)}")
        raise InternalServerError("Failed to remove avatar from database")
    
    # After successful commit, delete file from storage
    success = AvatarService.delete_avatar(old_avatar_path)
    if not success:
        # Log warning but continue (file may already be missing)
        current_app.logger.warning(f"Failed to delete avatar file: {old_avatar_path}")
    
    return jsonify({"message": "Avatar removed successfully"}), 200