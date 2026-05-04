"""
Custom API Validator for Flask routes using Marshmallow
module for Yet Another Flask Survival Kit (YAFSK)

Author:
    Johnny De Castro <j@jdcastro.co>

Copyright:
    (c) 2024 - 2025 Johnny De Castro. All rights reserved.

License:
    Apache License 2.0 - http://www.apache.org/licenses/LICENSE-2.0
"""

import logging
import re

# Python standard library imports
from functools import wraps

# Third party imports
from flask import jsonify, request
from marshmallow import Schema, ValidationError, fields, validate


class APIValidator:
    """
    Class to validate input data in Flask routes using Marshmallow.
    Provides a decorator to specify required fields and validations.
    """

    @staticmethod
    def validate_form(**field_rules):
        """
        Decorator to validate input data of an API request.

        :param field_rules: Dictionary with validation rules for each field.
        """

        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                try:
                    json_data = APIValidator._get_request_data()
                    if not json_data:
                        return jsonify({"error": "No data provided"}), 400

                    schema = APIValidator._create_dynamic_schema(field_rules)
                    data = schema.load(json_data)
                    request.validated_data = data
                    return f(*args, **kwargs)
                except ValidationError as err:
                    return (
                        jsonify(
                            {"error": "Validation failed", "details": err.messages}
                        ),
                        400,
                    )
                except Exception as e:
                    logging.error(f"An error occurred: {e}")
                    return jsonify({"error": "Internal Server Error"}), 500

            return decorated_function

        return decorator

    @staticmethod
    def _get_request_data():
        """Helper method to get request data based on HTTP method."""
        if request.method in ["POST", "PUT", "PATCH"]:
            return request.get_json(silent=True) or dict(request.form)
        elif request.method == "GET":
            return dict(request.args)
        return {}

    @staticmethod
    def _create_dynamic_schema(field_rules):
        """Helper method to create a dynamic Marshmallow Schema."""
        schema_fields = {}

        for field_name, rules in field_rules.items():
            field_type = fields.String
            field_params = {"required": True}
            validators = []

            if isinstance(rules, dict):
                # Extract type, required status, and other parameters
                if "type" in rules:
                    field_type = rules["type"]
                if "required" in rules:
                    field_params["required"] = rules["required"]
                # Extract any other field parameters (e.g., truthy/falsy for Boolean)
                field_params.update(
                    {
                        k: v
                        for k, v in rules.items()
                        if k not in ["type", "validators", "required"]
                    }
                )
                # Extract validators
                if "validators" in rules:
                    val = rules["validators"]
                    validators = val if isinstance(val, list) else [val]
            else:
                # Handle cases where rules are a single validator or list
                if callable(rules):
                    validators = [rules]
                elif isinstance(rules, list):
                    validators = rules

            # Apply validators
            if validators:
                field_params["validate"] = validators

            # Create the field
            schema_fields[field_name] = field_type(**field_params)

        return type("DynamicSchema", (Schema,), schema_fields)()

    @staticmethod
    def validate_boolean(required=True):
        """Validator for boolean fields with custom truthy/falsy values."""
        return {
            "type": fields.Boolean,
            "truthy": {True},
            "falsy": {False},
            "required": required,
        }

    @staticmethod
    def validate_number(min_value=None, max_value=None, required=True):
        """Validator for numeric fields with optional range constraints."""
        validators = []
        if min_value is not None:
            validators.append(validate.Range(min=min_value))
        if max_value is not None:
            validators.append(validate.Range(max=max_value))
        return {"validators": validators, "required": required}

    @staticmethod
    def validate_username(required=True):
        """Validator for usernames (3-20 alphanumeric/underscore characters)."""
        return {
            "validators": [
                validate.Regexp(
                    r"^[a-zA-Z0-9_]{3,20}$", error="Invalid username format."
                )
            ],
            "required": required,
        }

    @staticmethod
    def validate_email(required=True):
        """Validator for email addresses."""
        return {
            "validators": [validate.Email(error="Invalid email format.")],
            "required": required,
        }

    @staticmethod
    def validate_password_strength(
        min_length=8,
        require_upper=True,
        require_lower=True,
        require_digit=True,
        require_special=True,
        required=True,
    ):
        """Validator for password strength requirements."""

        def validator(value):
            errors = []
            if len(value) < min_length:
                errors.append("Must be at least 8 characters.")
            if require_upper and not any(c.isupper() for c in value):
                errors.append("Must contain uppercase letters.")
            if require_lower and not any(c.islower() for c in value):
                errors.append("Must contain lowercase letters.")
            if require_digit and not any(c.isdigit() for c in value):
                errors.append("Must contain digits.")
            if require_special and not any(c in '!@#$%^&*(),.?":{}|<>' for c in value):
                errors.append("Must contain special characters.")
            if errors:
                raise ValidationError(" ".join(errors))

        return {"validators": [validator], "required": required}

    @staticmethod
    def validate_textarea(max_length=None, required=True):
        """Validator for long text fields with optional max length."""
        validators = []
        if max_length:
            validators.append(validate.Length(max=max_length))
        return {"validators": validators, "required": required}

    @staticmethod
    def validate_phone(required=True):
        """Validator for phone numbers (E.164 format)."""
        return {
            "validators": [
                validate.Regexp(
                    r"^\+?[1-9]\d{1,14}$", error="Invalid phone number format."
                )
            ],
            "required": required,
        }

    @staticmethod
    def validate_url(required=True):
        """Validator for URLs (RFC 3986-compliant)."""
        return {
            "validators": [validate.URL(error="Invalid URL format.")],
            "required": required,
        }

    @staticmethod
    def validate_ip(required=True):
        """Validator for IPv4 addresses."""
        return {"type": fields.IPv4, "required": required}

    @staticmethod
    def validate_ipv6(required=True):
        """Validator for IPv6 addresses."""
        return {"type": fields.IPv6, "required": required}

    @staticmethod
    def validate_mac_address(required=True):
        """Validator for MAC addresses (standard format)."""
        return {
            "validators": [
                validate.Regexp(
                    r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$",
                    error="Invalid MAC address format.",
                )
            ],
            "required": required,
        }

    @staticmethod
    def validate_credit_card(required=True):
        """Validator for credit card numbers using Luhn algorithm."""

        def luhn_check(value):
            stripped = value.replace(" ", "").replace("-", "")
            if not stripped.isdigit():
                raise ValidationError("Invalid characters.")
            total = 0
            for i, digit in enumerate(str(stripped)[::-1]):
                d = int(digit)
                if i % 2 == 0:
                    total += d
                else:
                    total += d * 2 if d * 2 < 10 else (d * 2 - 9)
            return total % 10 == 0

        def validator(value):
            if not luhn_check(value):
                raise ValidationError("Invalid credit card number.")

        return {"validators": [validator], "required": required}

    @staticmethod
    def validate_date(required=True):
        """Validator for dates (YYYY-MM-DD)."""
        return {"type": fields.Date, "required": required}

    @staticmethod
    def validate_datetime(required=True):
        """Validator for ISO8601 datetimes."""
        return {"type": fields.DateTime, "required": required}

    @staticmethod
    def validate_time(required=True):
        """Validator for times (HH:MM:SS)."""
        return {"type": fields.Time, "required": required}

    @staticmethod
    def validate_color(required=True):
        """Validator for hexadecimal color codes."""
        return {
            "validators": [
                validate.Regexp(
                    r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$", error="Invalid color format."
                )
            ],
            "required": required,
        }

    @staticmethod
    def validate_radio(choices, required=True):
        """Validator for radio fields with predefined choices."""
        return {
            "validators": [
                validate.OneOf(
                    choices, error="Value must be one of the allowed options."
                )
            ],
            "required": required,
        }

    @staticmethod
    def validate_select(choices, required=True):
        """Validator for select fields with predefined choices."""
        return {
            "validators": [
                validate.OneOf(
                    choices, error="Value must be one of the allowed options."
                )
            ],
            "required": required,
        }

    @staticmethod
    def validate_isbn(required=True):
        """Validator for ISBN-10 and ISBN-13 numbers."""

        def validator(value):
            cleaned = re.sub(r"[^0-9X]", "", value.upper())
            if len(cleaned) == 10:
                total = 0
                for i, c in enumerate(cleaned):
                    if c == "X":
                        if i != 9:
                            raise ValidationError("Invalid ISBN-10.")
                        total += 10
                    else:
                        total += int(c) * (10 - i)
                if total % 11 != 0:
                    raise ValidationError("Invalid ISBN-10.")
            elif len(cleaned) == 13:
                total = 0
                for i, c in enumerate(cleaned):
                    digit = int(c)
                    total += digit if i % 2 == 0 else 3 * digit
                if total % 10 != 0:
                    raise ValidationError("Invalid ISBN-13.")
            else:
                raise ValidationError("Invalid ISBN length.")

        return {"validators": [validator], "required": required}

    @staticmethod
    def validate_enum(enum_class, value, required=True):
        """Validate if value belongs to the enum_class"""

        def validator(value):
            try:
                enum_class(value)
            except ValueError:
                raise ValidationError(
                    f"Value must be one of {enum_class.__name__} members."
                )

        return {"validators": [validator], "required": required}

    @staticmethod
    def validate_range(min_value=None, max_value=None, required=True):
        """Validator for numeric range fields."""

        def validator():
            return validate.Range(min=min_value, max=max_value)

        return {"validators": [validator], "required": required}

    @staticmethod
    def validate_month(required=True):
        """Validator for month fields in YYYY-MM format."""

        def validator():
            return fields.String(
                validate=validate.Regexp(r"^\d{4}-(0[1-9]|1[0-2])$"),
                error="Invalid month format. Use YYYY-MM.",
            )

        return {"validators": [validator], "required": required}

    @staticmethod
    def validate_week(required=True):
        """Validator for week fields in YYYY-Www format."""

        def validator():
            return fields.String(
                validate=validate.Regexp(
                    r"^\d{4}-W(0[1-9]|[1-4][0-9]|5[0-3])$",
                    error="Invalid week. Use the format YYYY-Www.",
                )
            )

        return {"validators": [validator], "required": required}

    @staticmethod
    def validate_datetime_local(required=True):
        """Validator for local datetime fields without timezone."""

        def validator():
            return fields.DateTime(
                format="%Y-%m-%dT%H:%M",
                error="Invalid datetime. Use the format YYYY-MM-DDTHH:MM.",
            )

        return {"validators": [validator], "required": required}
