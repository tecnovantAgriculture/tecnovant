"""
Custom error handler module for Yet Another Flask Survival Kit (YAFSK)

Author:
    Johnny De Castro <j@jdcastro.co>

Copyright:
    (c) 2024 - 2025 Johnny De Castro. All rights reserved.

License:
    Apache License 2.0 - http://www.apache.org/licenses/LICENSE-2.0

"""

import json

# Python standard library imports
import logging
import traceback
from logging.handlers import RotatingFileHandler

# Third party imports
from flask import Flask, Response, render_template, request
from werkzeug.exceptions import HTTPException


def setup_logging(log_file="errors.log"):
    """
    Configures logging with a rotating file handler.

    Args:
        log_file (str): Path to the log file.

    Returns:
        logging.Logger: Configured logger instance.
    """
    handler = RotatingFileHandler(
        log_file,
        maxBytes=1024 * 1024,  # 1MB per file
        backupCount=10,  # Keep up to 10 backup files
    )
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger = logging.getLogger(__name__)
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR)

    return logger


def error_handler(app: Flask, logger) -> None:
    """Register global error handlers for the Flask application.

    Args:
        app: Flask application instance.
        logger: Configured logger instance for error logging.
    """

    def _is_api_request() -> bool:
        """Determine if the request is for an API endpoint.

        Returns:
            bool: True if the request expects JSON (e.g., Accept header or URL pattern), False otherwise.
        """
        accept_header = request.headers.get("Accept", "").lower()
        return "application/json" in accept_header or request.path.startswith("/api/")

    @app.errorhandler(Exception)
    def handle_exception(e: Exception) -> tuple:
        """Handle global exceptions, log them, and return appropriate responses.

        Args:
            e: The exception instance to handle.

        Returns:
            tuple: Response (JSON or HTML) and HTTP status code.
        """
        # Log the error with additional request context
        logger.error(
            f"Error occurred: {str(e)}\n"
            f"Method: {request.method}, Path: {request.path}, "
            f"Headers: {request.headers}, Body: {request.get_data(as_text=True)}\n"
            f"Traceback: {traceback.format_exc()}"
        )

        # Determine error details based on exception type
        if isinstance(e, HTTPException):
            error_code = e.code
            error_description = e.name
            error_details = e.description if hasattr(e, "description") else str(e)
        else:
            error_code = 500
            error_description = "Internal Server Error"
            error_details = "An unexpected error occurred on the server."

        # Choose response format based on request type
        if _is_api_request():
            # JSON response for API requests
            response_data = {
                "status": "error",
                "message": error_description,
                "code": error_code,
                "details": error_details,
            }
            return Response(
                json.dumps(response_data, ensure_ascii=False, indent=4),
                status=error_code,
                mimetype="application/json",
            )
        else:
            # HTML response for web requests
            try:
                return (
                    render_template(
                        "layouts/error_handler.j2",
                        e=error_code,
                        e_description=error_description,
                        e_details=error_details,
                    ),
                    error_code,
                )
            except Exception as template_error:
                # Fallback if template rendering fails
                logger.error(f"Template rendering failed: {str(template_error)}")
                return (
                    f"Error {error_code}: {error_description} - {error_details}",
                    error_code,
                )
