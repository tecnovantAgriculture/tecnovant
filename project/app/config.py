# -*-coding:utf-8-*-
"""Custom configuration file for Yet Another Flask Survival Kit (YAFSK)

Author:
    Johnny De Castro <j@jdcastro.co>

Copyright:
    (c) 2024 - 2025 Johnny De Castro. All rights reserved.

License:
    Apache License 2.0 - http://www.apache.org/licenses/LICENSE-2.0

"""
# Python standard library imports
import os
from datetime import timedelta
from pathlib import Path
from typing import Literal

# Third party imports
from dotenv import load_dotenv

dotenv_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path)


def validate_mail_config():
    """Validate that all required mail configuration variables are set."""
    required_vars = ["MAIL_SERVER", "MAIL_USERNAME", "MAIL_PASSWORD"]
    for var in required_vars:
        if not os.getenv(var):
            raise ValueError(f"Missing required mail configuration: {var}")


DB_TYPE = Literal["sqlite", "mysql", "mariadb", "postgresql"]


def get_database_url(db_type: DB_TYPE) -> str:
    """Generate the database URL based on the provided database type."""
    db_types = {
        "sqlite": "sqlite:////{DB_NAME}.db",
        "mysql": "mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}",
        "mariadb": "mariadb+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}",
        "postgresql": "postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}",
    }
    if db_type not in db_types:
        raise ValueError(f"Unsupported database type: {db_type}")
    return db_types[db_type].format(
        DB_USER=os.getenv("DB_USER"),
        DB_PASSWORD=os.getenv("DB_PASSWORD"),
        DB_HOST=os.getenv("DB_HOST"),
        DB_NAME=os.getenv("DB_NAME"),
    )


def get_environment_config():
    """Get environment-specific configuration settings for production or development environments."""
    env = os.getenv("ENV", "development")
    return {
        "DEBUG": env == "development",
        "TEMPLATES_AUTO_RELOAD": env == "development",
        "JWT_COOKIE_SECURE": env == "production",
        "JWT_COOKIE_CSRF_PROTECT": env == "production",
    }


class Config:
    """
    Configuration class for the Flask application.
    Handles environment variables, database settings, mail configuration, and JWT settings.
    """

    CORE = True
    MODULES = ["foliage", "foliage_report"]
    THEME = "default"
    TITLE = os.getenv("TITLE")
    SECRET_KEY = os.getenv("SECRET_KEY")
    SECURITY_SALT = os.getenv("SECURITY_SALT")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    DB_TYPE = os.getenv("DB_TYPE", "sqlite")
    SQLALCHEMY_DATABASE_URI = (
        get_database_url(DB_TYPE) if DB_TYPE != "sqlite" else "sqlite:///app.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False  # Disable Flask-SQLAlchemy event system

    env_config = get_environment_config()
    DEBUG = env_config["DEBUG"]
    TEMPLATES_AUTO_RELOAD = env_config["TEMPLATES_AUTO_RELOAD"]

    # Email configuration
    MAIL_SERVER = os.getenv("MAIL_SERVER")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "465"))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "False").lower() == "true"
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "True").lower() == "true"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER")
    CONTACT_EMAIL = os.getenv("CONTACT_EMAIL")

    # Validate mail configuration
    validate_mail_config()

    # JWT configuration
    JWT_SECRET_KEY = SECRET_KEY
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=2)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=7)
    JWT_TOKEN_LOCATION = ["cookies"]
    JWT_ACCESS_COOKIE_PATH = "/"
    JWT_COOKIE_SECURE = env_config["JWT_COOKIE_SECURE"]
    JWT_COOKIE_CSRF_PROTECT = env_config["JWT_COOKIE_CSRF_PROTECT"]
    # redis cache
    CACHE_TYPE = os.getenv("CACHE_TYPE", "simple")
    CACHE_REDIS_URL = os.getenv("CACHE_REDIS_URL")
    CACHE_REDIS_PASSWORD = os.getenv("CACHE_REDIS_PASSWORD")
    CACHE_DEFAULT_TIMEOUT = int(os.getenv("CACHE_DEFAULT_TIMEOUT", "300"))
    CACHE_THRESHOLD = int(os.getenv("CACHE_THRESHOLD", "1000"))
    CACHE_IGNORE_ERRORS = os.getenv("CACHE_IGNORE_ERRORS", "True").lower() == "true"

    # JSON configuration  UTF-8
    JSON_AS_ASCII = False
    JSONIFY_PRETTYPRINT_REGULAR = False

    # overwrite for testing development purposes
    JWT_COOKIE_SECURE = True  # development purposes
    JWT_COOKIE_CSRF_PROTECT = True  # development purposes

    @classmethod
    def validate_config(cls):
        """Validate that all required environment variables are set."""
        required_vars = ["SECRET_KEY", "SECURITY_SALT"]
        if cls.DB_TYPE != "sqlite":
            required_vars.extend(["DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME"])

        for var in required_vars:
            if not os.getenv(var):
                raise ValueError(f"Missing required environment variable: {var}")


# Validate configuration on class initialization
Config.validate_config()
