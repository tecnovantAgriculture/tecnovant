"""Reusable CRUD mixin with role-based access controls."""

import json
from typing import Any, Dict, List

from flask import Response, json, request
from flask.views import MethodView
from flask_jwt_extended import get_jwt, jwt_required
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import BadRequest, Forbidden, NotFound

from app.core.models import ResellerPackage, RoleEnum, User
from app.extensions import db


class CRUDMixin(MethodView):
    """Generic mixin for CRUD operations with customization support."""

    decorators = [jwt_required()]

    def __init__(self, model, schema, service, required_roles=None):
        """Initialize CRUD operations with model, schema, service, and access control.

        Args:
            model: SQLAlchemy model class for database operations.
            schema: Marshmallow schema for serialization/deserialization.
            service: Business logic service for model operations.
            required_roles: List of roles allowed to access resources (default: ['administrator']).
        """
        self.model = model
        self.schema = schema
        self.service = service
        self.required_roles = required_roles or ["administrator"]

    def get(self, resource_id=None):
        """Retrieve a single resource or a list of resources.

        Args:
            resource_id: ID of the resource to retrieve (optional).

        Returns:
            Response: JSON response with the resource or list of resources.
        """
        if resource_id:
            return self._get_resource(resource_id)
        return self._get_resource_list()

    def post(self):
        """Create a new resource with validated input data.

        Returns:
            Response: JSON response with the created resource.

        Raises:
            BadRequest: If required fields are missing in the data.
        """
        data = self.schema.load(request.get_json())
        if not data or not self._validate_required_fields(data):
            raise BadRequest("Missing required fields.")
        return self._create_resource(data)

    def put(self, resource_id):
        """Update an existing resource by ID.

        Args:
            resource_id: ID of the resource to update.

        Returns:
            Response: JSON response with the updated resource.

        Raises:
            BadRequest: If resource_id or data is missing.
        """
        data = request.get_json()
        if not data or not resource_id:
            raise BadRequest("Missing resource_id or data.")
        return self._update_resource(resource_id, data)

    def delete(self, resource_id=None):
        """Delete one or multiple resources by ID(s).

        Args:
            resource_id: ID of the resource to delete (optional).

        Returns:
            Response: JSON response confirming the deletion.

        Raises:
            BadRequest: If neither resource_id nor a list of IDs is provided.
        """
        data = request.get_json()
        if data and "ids" in data:
            return self._delete_resources(data["ids"])
        if resource_id:
            return self._delete_resource(resource_id)
        raise BadRequest("Missing resource_id.")

    def _get_resource_list(self):
        """Retrieve all resources filtered by user access with optional pagination.

        Returns:
            Response: JSON response with the list of accessible resources.

        Raises:
            BadRequest: If pagination parameters are invalid.
            Forbidden: If the user has no access to any resources.
        """
        claims = get_jwt()
        page = request.args.get("page", type=int)
        per_page = request.args.get("per_page", type=int)
        pagination_requested = page is not None or per_page is not None

        if pagination_requested:
            page = page if page is not None else 1
            per_page = per_page if per_page is not None else 10

            if page < 1:
                raise BadRequest("Page number must be 1 or greater.")
            if per_page < 1 or per_page > 100:
                raise BadRequest("Per_page must be between 1 and 100.")

            pagination = self.service.get_all_paginated(page, per_page)
            accessible_items = [
                item for item in pagination.items if self._has_access(item, claims)
            ]

            if pagination.items and not accessible_items:
                raise Forbidden("You do not have access to any resources.")

            data = {
                "items": [self._serialize_resource(item) for item in accessible_items],
                "total": len(accessible_items),
                "pages": (
                    (len(accessible_items) + per_page - 1) // per_page
                    if accessible_items
                    else 1
                ),
                "page": page,
                "per_page": per_page,
            }
            return self._build_success_response(
                "Resources retrieved successfully", data
            )
        else:
            resources = self.service.get_all()
            accessible_resources = [
                resource for resource in resources if self._has_access(resource, claims)
            ]

            if resources and not accessible_resources:
                raise Forbidden("You do not have access to any resources.")

            data = [
                self._serialize_resource(resource) for resource in accessible_resources
            ]
            return self._build_success_response(
                "Resources retrieved successfully", data
            )

    def _get_resource(self, resource_id):
        """Retrieve a specific resource by ID with access control.

        Args:
            resource_id: ID of the resource to retrieve.

        Returns:
            Response: JSON response with the resource.

        Raises:
            NotFound: If the resource does not exist.
            Forbidden: If the user has no access to the resource.
        """
        resource = self.service.get_by_id(resource_id)
        if not resource:
            raise NotFound(f"Resource {resource_id} not found.")
        claims = get_jwt()
        if not self._has_access(resource, claims):
            raise Forbidden("You do not have access to this resource.")
        data = self._serialize_resource(resource)
        return self._build_success_response(
            f"Resource {resource_id} retrieved successfully", data
        )

    def _create_resource(self, data):
        """Create and return a new resource instance with access check.

        Args:
            data: Data for the resource to create.

        Returns:
            Response: JSON response with the created resource.

        Raises:
            Forbidden: If the user lacks permission to create the resource.
        """
        claims = get_jwt()
        temp_resource = self.model(**data)
        if not self._has_access(temp_resource, claims):
            raise Forbidden("You do not have permission to create this resource.")
        resource = self.service.create(data)
        data = self._serialize_resource(resource)
        return self._build_success_response(
            "Resource created successfully", data, status_code=201
        )

    def _update_resource(self, resource_id, data):
        """Update an existing resource with provided data and access check.

        Args:
            resource_id: ID of the resource to update.
            data: Data to update the resource with.

        Returns:
            Response: JSON response with the updated resource.

        Raises:
            NotFound: If the resource does not exist.
            Forbidden: If the user lacks access to the resource or the changes.
        """
        claims = get_jwt()
        resource = self.service.get_by_id(resource_id)
        if not resource:
            raise NotFound(f"Resource {resource_id} not found.")
        if not self._has_access(resource, claims):
            raise Forbidden("You do not have access to update this resource.")

        temp_resource = self.model(**{**self.schema.dump(resource), **data})
        if not self._has_access(temp_resource, claims):
            raise Forbidden(
                "You do not have permission to update this resource with these changes."
            )

        updated_resource = self.service.update(resource_id, data)
        data = self._serialize_resource(updated_resource)
        return self._build_success_response(
            f"Resource {resource_id} updated successfully", data
        )

    def _delete_resource(self, resource_id):
        """Delete a single resource by ID with access check.

        Args:
            resource_id: ID of the resource to delete.

        Returns:
            Response: JSON response confirming the deletion.

        Raises:
            NotFound: If the resource does not exist.
            Forbidden: If the user lacks access to delete the resource.
        """
        claims = get_jwt()
        resource = self.service.get_by_id(resource_id)
        if not resource:
            raise NotFound(f"Resource {resource_id} not found.")
        if not self._has_access(resource, claims):
            raise Forbidden("You do not have access to delete this resource.")

        self.service.delete(resource_id)
        return self._build_success_response(
            f"Resource {resource_id} deleted successfully"
        )

    def _delete_resources(self, resource_ids):
        """Delete multiple resources by a list of IDs with access check.

        Args:
            resource_ids: List of resource IDs to delete.

        Returns:
            Response: JSON response confirming the deletion.

        Raises:
            Forbidden: If no resources were deleted due to permission restrictions.
        """
        deleted_resources = self.service.delete_multiple(resource_ids)
        if not deleted_resources:
            raise Forbidden("No resources were deleted due to permission restrictions.")

        deleted_resources_str = ", ".join(map(str, deleted_resources))
        return self._build_success_response(
            f"Resources {deleted_resources_str} deleted successfully"
        )

    def _validate_required_fields(self, data):
        """Validate the presence of required fields in incoming data.

        Args:
            data: Data to validate.

        Returns:
            bool: True if the data is valid, False otherwise.

        Note:
            Override this method to implement custom validation checks.
        """
        return True

    def _serialize_resource(self, resource):
        """Serialize a resource using the configured schema.

        Args:
            resource: Resource to serialize.

        Returns:
            dict: Serialized representation of the resource.
        """
        return self.schema.dump(resource)

    def _has_access(self, resource, claims):
        """Check user authorization to access a specific resource.

        Args:
            resource: Resource to check.
            claims: JWT claims of the user.

        Returns:
            bool: True if the user has access, False otherwise.
        """
        user_role = claims.get("rol")

        if user_role == RoleEnum.ADMINISTRATOR.value:
            return True

        if user_role == RoleEnum.RESELLER.value:
            reseller_package = ResellerPackage.query.filter_by(
                reseller_id=claims.get("org_id")
            ).first()
            if not reseller_package:
                return False
            return any(
                org.id == getattr(resource, "org_id", None)
                for org in reseller_package.organizations
            )

        if (
            user_role == RoleEnum.ORG_ADMIN.value
            or user_role == RoleEnum.ORG_EDITOR.value
            or user_role == RoleEnum.ORG_VIEWER.value
        ):
            user_id = claims.get("user_id")
            if not user_id:
                return False
            user = User.query.get(user_id)
            if not user:
                return False
            resource_org_id = getattr(resource, "org_id", None)
            if resource_org_id is None:
                return False
            return any(org.id == resource_org_id for org in user.organizations)

        return False

    def _build_success_response(self, message, data=None, status_code=200):
        """Build a successful JSON response.

        Args:
            message: Success message.
            data: Data to include in the response (optional).
            status_code: HTTP status code (default: 200).

        Returns:
            Response: JSON response with the standardized format.
        """
        response_data = {"status": "success", "message": message}
        if data is not None:
            response_data["data"] = data
        return Response(
            json.dumps(response_data, ensure_ascii=False, indent=4),
            status=status_code,
            mimetype="application/json",
        )


class BaseService:
    """Base service class for business logic operations (CRUD operations)."""

    def __init__(self, model: Any) -> None:
        """Initialize the service with an associated SQLAlchemy model.

        Args:
            model: SQLAlchemy model class for database operations.
        """
        self.model = model

    def get_all(self) -> List[Any]:
        """Retrieve all resources from the database.

        Returns:
            List[Any]: List of all resource instances.
        """
        return self.model.query.all()

    def get_all_paginated(self, page: int, per_page: int) -> Any:
        """Retrieve all resources with pagination.

        Args:
            page: Page number to retrieve (1-based).
            per_page: Number of items per page.

        Returns:
            Any: Pagination object containing the resources.
        """
        return self.model.query.paginate(page=page, per_page=per_page, error_out=False)

    def get_by_id(self, resource_id: Any) -> Any:
        """Retrieve a single resource by its primary key.

        Args:
            resource_id: ID of the resource to retrieve.

        Returns:
            Any: Resource instance if found.

        Raises:
            NotFound: If the resource with the given ID does not exist.
        """
        resource = self.model.query.get(resource_id)
        if not resource:
            raise NotFound(f"Resource {resource_id} not found.")
        return resource

    def get_by_filter(self, filter_data: Dict[str, Any]) -> List[Any]:
        """Retrieve a list of resources matching the provided filter.

        Args:
            filter_data: Dictionary of filter criteria (e.g., {'org_id': 1}).

        Returns:
            List[Any]: List of resource instances matching the filter.
        """
        return self.model.query.filter_by(**filter_data).all()

    def get_by_reseller(self, reseller_id: Any) -> List[Any]:
        """Retrieve resources linked to a reseller account.

        Args:
            reseller_id: ID of the reseller account.

        Returns:
            List[Any]: List of resources associated with the reseller's organizations.

        Raises:
            NotFound: If the reseller package is not found.
        """

        reseller_package = ResellerPackage.query.filter_by(
            reseller_id=reseller_id
        ).first()
        if not reseller_package:
            raise NotFound("Reseller package not found.")

        resources = []
        for organization in reseller_package.organizations:
            resources.extend(self.model.query.filter_by(org_id=organization.id).all())
        return resources

    def get_by_reseller_paginated(
        self, reseller_id: Any, page: int, per_page: int
    ) -> Any:
        """Retrieve paginated resources linked to a reseller account.

        Args:
            reseller_id: ID of the reseller account.
            page: Page number to retrieve (1-based).
            per_page: Number of items per page.

        Returns:
            Any: Pagination object containing the resources.

        Raises:
            NotFound: If the reseller package is not found.
        """

        reseller_package = ResellerPackage.query.filter_by(
            reseller_id=reseller_id
        ).first()
        if not reseller_package:
            raise NotFound("Reseller package not found.")

        query = self.model.query.filter(
            self.model.org_id.in_([org.id for org in reseller_package.organizations])
        )
        return query.paginate(page=page, per_page=per_page, error_out=False)

    def create(self, data: Dict[str, Any]) -> Any:
        """Create a new resource instance.

        Args:
            data: Dictionary of data to create the resource.

        Returns:
            Any: Newly created resource instance.
        """

        try:
            resource = self.model(**self._prepare_create_data(data))
            db.session.add(resource)
            db.session.commit()
            return resource
        except SQLAlchemyError as e:
            db.session.rollback()
            raise e

    def update(self, resource_id: Any, data: Dict[str, Any]) -> Any:
        """Update an existing resource with provided data.

        Args:
            resource_id: ID of the resource to update.
            data: Dictionary of data to update the resource.

        Returns:
            Any: Updated resource instance.

        Raises:
            NotFound: If the resource with the given ID does not exist.
        """
        resource = self.get_by_id(resource_id)
        self._update_resource(resource, data)
        db.session.commit()
        return resource

    def delete(self, resource_id: Any) -> None:
        """Delete a single resource by its ID or deactivate it if it has an active flag.

        Args:
            resource_id: ID of the resource to delete.

        Raises:
            NotFound: If the resource with the given ID does not exist.
        """
        resource = self.get_by_id(resource_id)
        if hasattr(resource, "active"):
            resource.active = False
            db.session.commit()
        else:
            db.session.delete(resource)
            db.session.commit()

    def delete_multiple(self, resource_ids: List[Any]) -> List[Any]:
        """Delete multiple resources by a list of IDs or deactivate them if they have an active flag.

        Args:
            resource_ids: List of resource IDs to delete.

        Returns:
            List[Any]: List of IDs of resources that were successfully processed (deleted or deactivated).
        """
        processed_ids = []
        try:
            for resource_id in resource_ids:
                resource = self.model.query.get(resource_id)
                if resource:
                    if hasattr(resource, "active"):
                        resource.active = False
                    else:
                        db.session.delete(resource)
                    processed_ids.append(resource_id)
            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            raise e
        return processed_ids

    def _prepare_create_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare data before resource creation.

        Args:
            data: Raw data to prepare.

        Returns:
            Dict[str, Any]: Prepared data for resource creation.

        Note:
            Override this method to implement custom validation or data transformation.
        """
        return data

    def _update_resource(self, resource: Any, data: Dict[str, Any]) -> None:
        """Update resource attributes with provided data.

        Args:
            resource: Resource instance to update.
            data: Dictionary of data to apply to the resource.

        Note:
            Override this method to restrict or edit fields as needed.
        """
        allowed_fields = self.model._sa_class_manager.mapper.column_attrs.keys()
        for key, value in data.items():
            if key in allowed_fields:
                setattr(resource, key, value)
