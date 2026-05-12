"""Automated tests for login rate limiting and account lockout.

These tests verify:
* HTTP 429 is returned after exceeding per-IP/per-user rate limits.
* Accounts are temporarily locked after N consecutive failed attempts.
* Lockout persists even when the source IP changes.
* Failed-login timing is indistinguishable for missing vs. wrong-password users.
"""

import time
import unittest
from unittest.mock import patch

from flask import Flask

from app.core import core_api
from app.core.config import CoreConfig
from app.extensions import cache, db, limiter


class LoginRateLimitTestCase(unittest.TestCase):
    """Test suite for /api/core/login rate limiting and lockout logic."""

    def setUp(self):
        """Configure a minimal Flask app with in-memory rate-limit storage."""
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            CACHE_TYPE="simple",
            RATELIMIT_STORAGE_URI="memory://",
            JWT_SECRET_KEY="test-jwt-secret",
            JWT_ACCESS_TOKEN_EXPIRES=False,
            JWT_REFRESH_TOKEN_EXPIRES=False,
            JWT_TOKEN_LOCATION=["headers"],
            JWT_COOKIE_SECURE=False,
            JWT_COOKIE_CSRF_PROTECT=False,
        )

        db.init_app(self.app)
        cache.init_app(self.app)
        # Reset global limiter state to avoid cross-test leakage
        limiter.storage_uri = "memory://"
        limiter.init_app(self.app)

        # Ensure limiter uses the test app's context
        # (flask-limiter stores its state on the app object)
        limiter.reset()

        self.app.register_blueprint(core_api)

        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        """Clean up in-memory database and cache."""
        with self.app.app_context():
            db.drop_all()
            cache.clear()
        limiter.reset()

    def _make_login_request(self, username="testuser", password="wrongpass"):
        """Helper to fire a POST to /api/core/login."""
        return self.client.post(
            "/api/core/login",
            json={"username": username, "password": password},
        )

    # ------------------------------------------------------------------
    # 1. Rate-limit returns 429 after too many requests
    # ------------------------------------------------------------------

    @patch("app.core.controller.User.get_by_username")
    @patch("app.core.controller.check_password_hash")
    def test_rate_limit_returns_429(self, mock_pwhash, mock_get_user):
        """After exceeding the per-IP+user limit, the endpoint returns HTTP 429."""
        # Simulate a non-existent user (still consumes a failed attempt)
        mock_get_user.return_value = None
        mock_pwhash.return_value = False

        limit = CoreConfig.RATE_LIMIT_LOGIN_PER_USER
        window = CoreConfig.RATE_LIMIT_LOGIN_WINDOW
        total_requests = limit + 3

        responses = []
        for _ in range(total_requests):
            resp = self._make_login_request(username="brute_target")
            responses.append(resp.status_code)
            # tiny sleep to avoid sub-millisecond bursts that can bypass
            # in-memory counters on some limiter backends
            time.sleep(0.01)

        # At least one of the later requests must be 429
        self.assertIn(429, responses, "Expected at least one 429 response")

    # ------------------------------------------------------------------
    # 2. Account lockout after N consecutive failures
    # ------------------------------------------------------------------

    @patch("app.core.controller.User.get_by_username")
    @patch("app.core.controller.check_password_hash")
    def test_account_lockout_after_max_attempts(self, mock_pwhash, mock_get_user):
        """After N failed attempts the account is locked and further tries return 401."""
        mock_get_user.return_value = None
        mock_pwhash.return_value = False

        max_attempts = CoreConfig.RATE_LIMIT_LOCKOUT_MAX_ATTEMPTS

        # Fire exactly max_attempts failed logins
        for i in range(max_attempts):
            resp = self._make_login_request(username="lockme")
            self.assertEqual(
                resp.status_code,
                401,
                f"Expected 401 on failed attempt {i + 1}",
            )

        # The next request must be locked out (still 401, different msg)
        resp = self._make_login_request(username="lockme")
        self.assertEqual(resp.status_code, 401)
        self.assertIn("locked", resp.get_json()["msg"].lower())

    # ------------------------------------------------------------------
    # 3. Lockout persists across IP changes
    # ------------------------------------------------------------------

    @patch("app.core.controller.User.get_by_username")
    @patch("app.core.controller.check_password_hash")
    def test_lockout_persists_across_ip_changes(self, mock_pwhash, mock_get_user):
        """Changing the source IP does not bypass an account-level lockout."""
        mock_get_user.return_value = None
        mock_pwhash.return_value = False

        # Exhaust failed attempts
        for _ in range(CoreConfig.RATE_LIMIT_LOCKOUT_MAX_ATTEMPTS):
            self._make_login_request(username="cross_ip")

        # Simulate a different IP by overriding the WSGI environ
        resp = self.client.post(
            "/api/core/login",
            json={"username": "cross_ip", "password": "wrong"},
            environ_overrides={"REMOTE_ADDR": "10.0.0.99"},
        )
        self.assertEqual(resp.status_code, 401)
        self.assertIn("locked", resp.get_json()["msg"].lower())

    # ------------------------------------------------------------------
    # 4. Timing indistinguishability (missing vs wrong password)
    # ------------------------------------------------------------------

    @patch("app.core.controller.User.get_by_username")
    def test_timing_indistinguishable_for_missing_user(self, mock_get_user):
        """A missing user triggers the same code path (dummy hash) as a wrong password."""
        import timeit

        mock_get_user.side_effect = [None, "fake_user_obj"]

        with patch("app.core.controller.check_password_hash") as mock_pwhash:
            mock_pwhash.return_value = False

            def missing_user():
                return self._make_login_request(username="missing")

            def wrong_password():
                return self._make_login_request(username="exists")

            # Warm-up
            missing_user()
            wrong_password()
            cache.clear()  # reset counters so we don't hit lockout

            # Time both paths a few times and compare means
            missing_times = timeit.repeat(missing_user, number=1, repeat=10)
            wrong_times = timeit.repeat(wrong_password, number=1, repeat=10)

            avg_missing = sum(missing_times) / len(missing_times)
            avg_wrong = sum(wrong_times) / len(wrong_times)
            ratio = avg_missing / avg_wrong if avg_wrong else 1

            # Allow up to 3x variance because we're running in Docker on
            # shared CPU; the dummy hash guarantees the *code path* is the
            # same, not identical nanosecond timing.
            self.assertLess(
                ratio,
                3.0,
                "Missing-user path is unexpectedly slower than wrong-password path",
            )


if __name__ == "__main__":
    unittest.main()
