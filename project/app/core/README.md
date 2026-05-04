# Core Module

## Overview

The Core module provides fundamental user management, authentication, profile data, and avatar handling for the TecnoAgro application. It extends the existing user profile system with avatar upload functionality and enriched profile data display.

## Features

- **User Authentication**: Login, logout, JWT token management, password reset
- **User Management**: CRUD operations for users and organizations
- **Extended Profile**: Birthday, last access timestamp, avatar storage
- **Avatar Handling**: File upload, validation, storage, and cleanup
- **Role-Based Access Control**: Predefined roles with permissions
- **Versioned API**: Separate API v1 endpoints for extended profile features

## Architecture

### Blueprints

| Blueprint | Prefix | Type | Description |
|-----------|--------|------|-------------|
| `core` | `/` | UI | Web interface routes (templates) |
| `core_api` | `/api/core` | API | Legacy unversioned API endpoints |
| `core_api_v1` | `/api/v1/core` | API | Versioned API for extended profile and avatar |

### Directory Structure

```
core/
├── __init__.py              # Blueprint registration
├── config.py                # Module-specific configuration
├── constants.py             # Module constants
├── exceptions.py            # Custom exceptions
├── models.py                # SQLAlchemy models (existing)
├── schemas.py               # Marshmallow schemas (existing)
├── schemas/                 # Extended schemas
│   ├── __init__.py
│   └── extended_user_schema.py
├── services/                # Business logic services
│   ├── __init__.py
│   ├── avatar_service.py
│   └── profile_service.py
├── api/                     # API layer
│   ├── __init__.py
│   └── v1/
│       ├── __init__.py
│       └── routes.py       # Versioned API endpoints
├── ui/                      # UI layer (optional)
├── templates/               # Jinja2 templates (existing)
├── api_routes.py           # Legacy API routes (existing)
├── web_routes.py           # UI routes (existing)
├── controller.py           # View classes (existing)
├── module.json             # Module metadata
└── README.md               # This file
```

## API Endpoints (v1)

### Profile

- `GET /api/v1/core/profile` - Get extended profile data
- `PUT /api/v1/core/profile` - Update profile fields (full_name, email, birthday)

### Avatar

- `POST /api/v1/core/profile/avatar` - Upload avatar image
- `DELETE /api/v1/core/profile/avatar` - Remove current avatar

## Configuration

The module can be configured via environment variables:

- `AVATAR_UPLOAD_DIR`: Filesystem path for avatar storage (default: `/var/www/avatars`)
- `AVATAR_MAX_SIZE`: Maximum file size in bytes (default: 5MB)
- `AVATAR_ALLOWED_EXTENSIONS`: Comma-separated list of allowed extensions

See `config.py` for all available options.

## Services

### AvatarService

Handles avatar file operations:
- File validation (type, size, dimensions)
- Storage and path generation
- File cleanup and deletion
- URL generation

### ProfileService

Manages extended profile data:
- Serialization of extended profile fields
- Profile update validation
- Last access timestamp updates
- Avatar path management

## Data Model

The `User` model is extended through its existing `profile_data` JSON column with three new optional fields:

1. **avatar_path**: Relative filesystem path to avatar image
2. **birthday**: ISO 8601 date string (YYYY-MM-DD)
3. **last_access**: ISO 8601 datetime string of last authenticated access

No database schema changes are required.

## Security

- **File Validation**: All uploaded avatars are validated for type, size, and content
- **Rate Limiting**: API endpoints have configurable rate limits
- **Authorization**: All endpoints require JWT authentication
- **Input Validation**: All user input is validated using Marshmallow schemas

## Dependencies

- Flask & Flask extensions (JWT, SQLAlchemy)
- Marshmallow for serialization/validation
- Pillow (optional) for image dimension validation

## Testing

Run tests with pytest:

```bash
pytest tests/core/
```

## Migration Notes

- Existing `profile_data` JSON may be `None` or empty; code handles gracefully
- Avatar files are stored separately from database; cleanup is handled by `AvatarService`
- Backward compatibility maintained with legacy `/api/core/profile` endpoint

## References

- [Architecture Design](./docs_internal/module/core/architecture.md)
- [Model Design](./docs_internal/module/core/models.md)
- [API Contracts](./docs_internal/module/core/api_contracts.md)