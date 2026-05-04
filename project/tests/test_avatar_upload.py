"""Unit tests for avatar upload transaction handling.

These tests verify the atomic replacement behavior of avatar upload,
ensuring no orphaned files are left in normal success case, and proper
rollback on database failures.
"""

import io
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from flask import Flask
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import BadRequest, InternalServerError

# Import the route functions directly for testing
from app.core.api.v1.routes import upload_avatar, delete_avatar


class AvatarUploadTestCase(unittest.TestCase):
    """Test case for avatar upload atomic transaction handling."""

    def setUp(self):
        """Set up test fixtures."""
        self.app = Flask(__name__)
        self.app.config.update(
            AVATAR_UPLOAD_DIR=tempfile.mkdtemp(prefix="avatar-test-"),
            AVATAR_URL_PREFIX="/avatars",
            AVATAR_ALLOWED_EXTENSIONS={"jpg", "jpeg", "png", "gif", "webp"},
            AVATAR_MAX_SIZE=5 * 1024 * 1024,
            SECRET_KEY="test-secret",
        )
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        """Clean up after tests."""
        self.app_context.pop()

    @patch("app.core.api.v1.routes.get_jwt_identity")
    @patch("app.core.api.v1.routes.User")
    @patch("app.core.api.v1.routes.AvatarService")
    @patch("app.core.api.v1.routes.ProfileService")
    @patch("app.core.api.v1.routes.db")
    def test_upload_avatar_success_with_existing_avatar(
        self, mock_db, mock_profile_service, mock_avatar_service, mock_user_class, mock_jwt
    ):
        """Test successful avatar replacement with existing old avatar."""
        # Mock user and identity
        mock_jwt.return_value = "user123"
        mock_user = MagicMock()
        mock_user.id = "user123"
        mock_user.avatar_path = "user123/old_avatar.jpg"
        mock_user_class.query.get.return_value = mock_user
        
        # Mock validation
        mock_avatar_service.validate_avatar.return_value = (True, "")
        
        # Mock file save
        mock_avatar_service.save_avatar.return_value = "user123/new_avatar.jpg"
        
        # Mock database commit
        mock_db.session.commit.return_value = None
        
        # Mock old avatar deletion
        mock_avatar_service.delete_avatar.return_value = True
        
        # Mock avatar URL generation
        mock_avatar_service.get_avatar_url.return_value = "/avatars/user123/new_avatar.jpg"
        
        # Create mock file
        file = FileStorage(stream=io.BytesIO(b"fake image data"), filename="avatar.jpg")
        
        # Call the route function (need to mock request.files)
        with patch("app.core.api.v1.routes.request") as mock_request:
            mock_request.files = {"file": file}
            
            # Import jsonify locally to avoid mocking issues
            with patch("app.core.api.v1.routes.jsonify") as mock_jsonify:
                mock_jsonify.return_value = {"avatar_url": "/avatars/user123/new_avatar.jpg", "message": "success"}
                
                # Execute
                response = upload_avatar()
                
                # Verify
                mock_avatar_service.validate_avatar.assert_called_once_with(file)
                mock_avatar_service.save_avatar.assert_called_once_with("user123", file)
                mock_profile_service.set_avatar.assert_called_once_with(mock_user, "user123/new_avatar.jpg")
                mock_db.session.commit.assert_called_once()
                mock_avatar_service.delete_avatar.assert_called_once_with("user123/old_avatar.jpg")
                mock_avatar_service.get_avatar_url.assert_called_once_with("user123/new_avatar.jpg")
                self.assertIsNotNone(response)

    @patch("app.core.api.v1.routes.get_jwt_identity")
    @patch("app.core.api.v1.routes.User")
    @patch("app.core.api.v1.routes.AvatarService")
    @patch("app.core.api.v1.routes.ProfileService")
    @patch("app.core.api.v1.routes.db")
    def test_upload_avatar_rollback_on_commit_failure(
        self, mock_db, mock_profile_service, mock_avatar_service, mock_user_class, mock_jwt
    ):
        """Test rollback when database commit fails."""
        # Mock user and identity
        mock_jwt.return_value = "user123"
        mock_user = MagicMock()
        mock_user.id = "user123"
        mock_user.avatar_path = None
        mock_user_class.query.get.return_value = mock_user
        
        # Mock validation
        mock_avatar_service.validate_avatar.return_value = (True, "")
        
        # Mock file save
        mock_avatar_service.save_avatar.return_value = "user123/new_avatar.jpg"
        
        # Mock database commit failure
        mock_db.session.commit.side_effect = Exception("Database constraint violation")
        
        # Mock delete_avatar for cleanup
        mock_avatar_service.delete_avatar.return_value = True
        
        # Create mock file
        file = FileStorage(stream=io.BytesIO(b"fake image data"), filename="avatar.jpg")
        
        with patch("app.core.api.v1.routes.request") as mock_request:
            mock_request.files = {"file": file}
            
            # Expect InternalServerError
            with self.assertRaises(InternalServerError):
                upload_avatar()
            
            # Verify rollback was called
            mock_db.session.rollback.assert_called_once()
            # Verify cleanup of new file
            mock_avatar_service.delete_avatar.assert_called_once_with("user123/new_avatar.jpg")

    @patch("app.core.api.v1.routes.get_jwt_identity")
    @patch("app.core.api.v1.routes.User")
    @patch("app.core.api.v1.routes.AvatarService")
    @patch("app.core.api.v1.routes.ProfileService")
    @patch("app.core.api.v1.routes.db")
    def test_delete_avatar_success(self, mock_db, mock_profile_service, mock_avatar_service, mock_user_class, mock_jwt):
        """Test successful avatar deletion."""
        # Mock user and identity
        mock_jwt.return_value = "user123"
        mock_user = MagicMock()
        mock_user.id = "user123"
        mock_user.avatar_path = "user123/old_avatar.jpg"
        mock_user_class.query.get.return_value = mock_user
        
        # Mock database commit
        mock_db.session.commit.return_value = None
        
        # Mock file deletion
        mock_avatar_service.delete_avatar.return_value = True
        
        # Call delete_avatar route function
        with patch("app.core.api.v1.routes.jsonify") as mock_jsonify:
            mock_jsonify.return_value = {"message": "success"}
            
            response = delete_avatar()
            
            # Verify
            mock_profile_service.set_avatar.assert_called_once_with(mock_user, None)
            mock_db.session.commit.assert_called_once()
            mock_avatar_service.delete_avatar.assert_called_once_with("user123/old_avatar.jpg")
            self.assertIsNotNone(response)

    @patch("app.core.api.v1.routes.get_jwt_identity")
    @patch("app.core.api.v1.routes.User")
    @patch("app.core.api.v1.routes.AvatarService")
    @patch("app.core.api.v1.routes.ProfileService")
    @patch("app.core.api.v1.routes.db")
    def test_delete_avatar_rollback_on_commit_failure(
        self, mock_db, mock_profile_service, mock_avatar_service, mock_user_class, mock_jwt
    ):
        """Test rollback when avatar deletion commit fails."""
        # Mock user and identity
        mock_jwt.return_value = "user123"
        mock_user = MagicMock()
        mock_user.id = "user123"
        mock_user.avatar_path = "user123/old_avatar.jpg"
        mock_user_class.query.get.return_value = mock_user
        
        # Mock database commit failure
        mock_db.session.commit.side_effect = Exception("Database error")
        
        with self.assertRaises(InternalServerError):
            delete_avatar()
        
        # Verify rollback was called
        mock_db.session.rollback.assert_called_once()
        # Verify file deletion was NOT attempted (since commit failed)
        mock_avatar_service.delete_avatar.assert_not_called()


if __name__ == "__main__":
    unittest.main()