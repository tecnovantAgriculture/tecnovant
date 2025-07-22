# Python standard library imports
import json
from datetime import date, datetime, timedelta

from flask import Response, jsonify, request
from flask.views import MethodView

# Third party imports
from flask_jwt_extended import get_jwt, jwt_required
from sqlalchemy.orm import joinedload, selectinload
from werkzeug.exceptions import BadRequest, Conflict, Forbidden, NotFound, Unauthorized

from app.core.controller import check_permission, check_resource_access
from app.core.models import Organization, ResellerPackage, RoleEnum, User

# Local application imports
from app.extensions import db

from .models import (
    CommonAnalysis,
    Crop,
    Farm,
    LeafAnalysis,
    Lot,
    LotCrop,
    Nutrient,
    NutrientApplication,
    Objective,
    Product,
    ProductContribution,
    Production,
    ProductPrice,
    Recommendation,
    SoilAnalysis,
    leaf_analysis_nutrients,
    nutrient_application_nutrients,
    objective_nutrients,
    product_contribution_nutrients,
)

# helper


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)


# Vista para granjas (farms)
# 👌
class FarmView(MethodView):
    """Clase para gestionar operaciones CRUD sobre granjas."""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, farm_id=None):
        """
        Obtiene una lista de granjas o una granja específica.
        Args:
            farm_id (str, optional): ID de la granja a consultar.
        Returns:
            JSON: Lista de granjas o detalles de una granja específica.
        """
        if farm_id:
            return self._get_farm(farm_id)
        filter_by = request.args.get("filter_value", type=int)
        search = request.args.get("search")
        return self._get_farm_list(filter_by=filter_by, search=search)

    @check_permission(required_roles=["administrator", "reseller"])
    def post(self):
        """
        Crea una nueva granja.
        Returns:
            JSON: Detalles de la granja creada.
        """
        data = request.get_json()
        if not data or not all(k in data for k in ("name", "org_id")):
            raise BadRequest("Missing required fields.")
        return self._create_farm(data)

    @check_permission(resource_owner_check=True)
    def put(self, id: int):
        """
        Actualiza una granja existente.
        Args:
            id (int): ID de la granja a actualizar.
        Returns:
            JSON: Detalles de la granja actualizada.
        """
        data = request.get_json()
        farm_id = data.get("id")
        if not data or not farm_id:
            raise BadRequest("Missing farm_id or data.")
        return self._update_farm(farm_id, data)

    @check_permission(resource_owner_check=True)
    def delete(self, id=None):
        """
        Elimina una granja existente.
        Args:
            id (int, optional): ID de la granja a eliminar.
        Returns:
            JSON: Mensaje de confirmación.
        """
        data = request.get_json()
        farm_id = id
        if data and "ids" in data:
            return self._delete_farm(farm_ids=data["ids"])
        if farm_id:
            return self._delete_farm(farm_id=farm_id)
        raise BadRequest("Missing farm_id.")

    # Métodos auxiliares
    def _get_farm_list(self, filter_by=None, search=None):
        """Obtiene una lista de todas las granjas activas con filtros opcionales."""
        claims = get_jwt()

        query = Farm.query
        if hasattr(Farm, "active"):
            query = query.filter_by(active=True)
        if filter_by:
            query = query.filter_by(org_id=filter_by)
        if search:
            query = query.filter(Farm.name.ilike(f"%{search}%"))

        farms = query.all()
        accessible_farms = [farm for farm in farms if self._has_access(farm, claims)]

        if farms and not accessible_farms:
            raise Forbidden("You do not have access to any farms.")

        response_data = [self._serialize_farm(farm) for farm in farms]
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _get_farm(self, farm_id):
        """Obtiene los detalles de una granja específica."""
        farm = Farm.query.get_or_404(farm_id)
        claims = get_jwt()
        if not self._has_access(farm, claims):
            raise Forbidden("You do not have access to this farm.")
        response_data = self._serialize_farm(farm)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _create_farm(self, data):
        """Crea una nueva granja con los datos proporcionados."""
        if hasattr(Farm, "active"):
            if Farm.query.filter_by(
                name=data["name"], org_id=data["org_id"], active=True
            ).first():
                raise BadRequest("Name already exists.")
        else:
            if Farm.query.filter_by(name=data["name"], org_id=data["org_id"]).first():
                raise BadRequest("Name already exists.")
        farm = Farm(
            name=data["name"],
            org_id=data["org_id"],
        )
        db.session.add(farm)
        db.session.commit()
        response_data = self._serialize_farm(farm)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=201, mimetype="application/json")

    def _update_farm(self, farm_id, data):
        """Actualiza los datos de una granja existente."""
        farm = Farm.query.get_or_404(farm_id)
        if "name" in data and data["name"] != farm.name:
            if hasattr(Farm, "active"):
                if Farm.query.filter_by(
                    name=data["name"], org_id=farm.org_id, active=True
                ).first():
                    raise BadRequest("Name already exists.")
            else:
                if Farm.query.filter_by(name=data["name"], org_id=farm.org_id).first():
                    raise BadRequest("Name already exists.")
            farm.name = data["name"]
        if "org_id" in data:
            farm.org_id = data["org_id"]
        db.session.commit()
        response_data = self._serialize_farm(farm)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _delete_farm(self, farm_id=None, farm_ids=None):
        """Elimina una granja o varias granjas marcándolas como inactivas."""
        claims = get_jwt()
        deleted_farms = []

        if farm_id and farm_ids:
            raise BadRequest("Solo se puede especificar farm_id o farm_ids, no ambos.")

        if farm_id:
            farm = Farm.query.get_or_404(farm_id)
            if hasattr(farm, "active"):
                farm.active = False
            else:
                db.session.delete(farm)
            db.session.commit()
            deleted_farms.append(farm.name)

        if farm_ids is not None:
            for farm_id in farm_ids:
                farm = Farm.query.get(farm_id)
                if not farm:
                    continue
                if hasattr(farm, "active"):
                    farm.active = False
                else:
                    db.session.delete(farm)
                deleted_farms.append(farm.name)
                db.session.commit()

        if not deleted_farms:
            return (
                jsonify(
                    {"error": "No farms were deleted due to permission restrictions"}
                ),
                403,
            )

        deleted_farms_str = ", ".join(deleted_farms)
        return (
            jsonify({"message": f"Farms {deleted_farms_str} deleted successfully"}),
            200,
        )

    def _has_access(self, farm, claims):
        """Verifica si el usuario actual tiene acceso al recurso."""
        return check_resource_access(farm, claims)

    def _serialize_farm(self, farm):
        """Serializa un objeto Farm a un diccionario."""
        return {
            "id": farm.id,
            "name": farm.name,
            "org_id": farm.org_id,
            "org_name": farm.organization.name if farm.organization else "",
            "lots": [lot.name for lot in farm.lots],
            "created_at": farm.created_at.isoformat(),
            "updated_at": farm.updated_at.isoformat(),
        }


# Vista para lotes (lots)
# 👌
class LotView(MethodView):
    """Clase para gestionar operaciones CRUD sobre lotes."""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, lot_id=None):
        """
        Obtiene una lista de lotes o un lote específico.
        Args:
            lot_id (str, optional): ID del lote a consultar.
        Returns:
            JSON: Lista de lotes o detalles de un lote específico.
        """
        if lot_id:
            return self._get_lot(lot_id)
        filter_by = request.args.get("filter_value", type=int)
        search = request.args.get("search")
        return self._get_lot_list(filter_by=filter_by, search=search)

    @check_permission(required_roles=["administrator", "reseller"])
    def post(self):
        """
        Crea un nuevo lote.
        Returns:
            JSON: Detalles del lote creado.
        """
        data = request.get_json()
        if not data or not all(k in data for k in ("name", "area", "farm_id")):
            raise BadRequest("Missing required fields.")
        return self._create_lot(data)

    @check_permission(resource_owner_check=True)
    def put(self, id=None):
        """
        Actualiza un lote existente.
        Args:
            lot_id (str): ID del lote a actualizar.
        Returns:
            JSON: Detalles del lote actualizado.
        """
        data = request.get_json()
        lot_id = data.get("id")
        if not data or not lot_id:
            raise BadRequest("Missing lot_id or data.")
        return self._update_lot(lot_id, data)

    @check_permission(resource_owner_check=True)
    def delete(self, id=None):
        """
        Elimina un lote existente.
        Args:
            lot_id (str): ID del lote a eliminar.
        Returns:
            JSON: Mensaje de confirmación.
        """
        data = request.get_json()
        if data and "ids" in data:
            return self._delete_lot(lot_ids=data["ids"])
        if id:
            return self._delete_lot(lot_id=id)

        raise BadRequest("Missing lot_id.")

    # Métodos auxiliares
    def _get_lot_list(self, filter_by=None, search=None):
        """Obtiene una lista de lotes activos según el rol del usuario con filtros opcionales."""
        claims = get_jwt()
        user_role = claims.get("rol")
        user_id = claims.get("id")
        lots = []  # Lista de lotes que se devolverá
        if user_role == RoleEnum.ADMINISTRATOR.value:
            query = Lot.query
            if hasattr(Lot, "active"):
                query = query.filter_by(active=True)
            if filter_by:
                query = query.filter_by(farm_id=filter_by)
            if search:
                query = query.filter(Lot.name.ilike(f"%{search}%"))
            lots = query.all()
        elif user_role == RoleEnum.RESELLER.value:
            reseller_package = (
                ResellerPackage.query.options(
                    joinedload(ResellerPackage.organizations).joinedload("lots")
                )
                .filter_by(reseller_id=user_id)
                .first()
            )
            if not reseller_package:
                raise NotFound("Reseller package not found.")
            # Usamos un conjunto para evitar duplicados
            lots = {lot for org in reseller_package.organizations for lot in org.lots}
            # Convertimos a lista para la serialización final
            lots = list(lots)
            if filter_by:
                lots = [l for l in lots if l.farm_id == filter_by]
            if search:
                lots = [l for l in lots if search.lower() in l.name.lower()]
        else:
            raise Forbidden("Only administrators and resellers can list lots.")
        # Serialización y respuesta
        response_data = [self._serialize_lot(lot) for lot in lots]
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _get_lot(self, lot_id):
        """Obtiene los detalles de un lote específico."""
        lot = Lot.query.get_or_404(lot_id)
        claims = get_jwt()
        if not self._has_access(lot, claims):
            raise Forbidden("You do not have access to this lot.")
        response_data = self._serialize_lot(lot)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _create_lot(self, data):
        """Crea un nuevo lote con los datos proporcionados."""
        if hasattr(Lot, "active"):
            if Lot.query.filter_by(name=data["name"], active=True).first():
                raise BadRequest("Name already exists.")
        else:
            if Lot.query.filter_by(name=data["name"]).first():
                raise BadRequest("Name already exists.")
        lot = Lot(
            name=data["name"],
            area=data["area"],
            farm_id=data["farm_id"],
        )
        db.session.add(lot)
        db.session.commit()
        response_data = self._serialize_lot(lot)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=201, mimetype="application/json")

    def _update_lot(self, lot_id, data):
        """Actualiza los datos de un lote existente."""
        lot = Lot.query.get_or_404(lot_id)
        if "name" in data and data["name"] != lot.name:
            if hasattr(Lot, "active"):
                if Lot.query.filter_by(name=data["name"], active=True).first():
                    raise BadRequest("Name already exists.")
            else:
                if Lot.query.filter_by(name=data["name"]).first():
                    raise BadRequest("Name already exists.")
            lot.name = data["name"]
        if "area" in data:
            lot.area = data["area"]
        if "farm_id" in data:
            lot.farm_id = data["farm_id"]
        db.session.commit()
        response_data = self._serialize_lot(lot)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _delete_lot(self, lot_id=None, lot_ids=None):
        """Elimina un lote marcándolo como inactivo."""
        claims = get_jwt()
        if lot_id and lot_ids:
            raise BadRequest("Solo se puede especificar lot_id o lot_ids, no ambos.")

        if lot_id:
            lot = Lot.query.get_or_404(lot_id)
            if hasattr(lot, "active"):
                lot.active = False
            else:
                db.session.delete(lot)
            db.session.commit()
            return jsonify({"message": "Lot deleted successfully"}), 200

        if lot_ids is not None:
            deleted_lots = []
            for lot_id in lot_ids:
                lot = Lot.query.get(lot_id)
                if not lot:
                    continue
                if hasattr(lot, "active"):
                    lot.active = False
                else:
                    db.session.delete(lot)
                deleted_lots.append(lot.name)
                db.session.commit()

            if deleted_lots:
                deleted_lots_str = ", ".join(deleted_lots)
                return (
                    jsonify(
                        {"message": f"Lots {deleted_lots_str} deleted successfully"}
                    ),
                    200,
                )
            return (
                jsonify(
                    {"error": "No lots were deleted due to permission restrictions"}
                ),
                403,
            )

    def _has_access(self, lot, claims):
        """Verifica si el usuario actual tiene acceso al recurso."""
        return check_resource_access(lot, claims)

    def _serialize_lot(self, lot):
        """Serializa un objeto Lot a un diccionario."""
        return {
            "id": lot.id,
            "name": lot.name,
            "area": lot.area,
            "farm_id": lot.farm_id,
            "farm_name": lot.farm.name if lot.farm else "",
            "created_at": lot.created_at.isoformat(),
            "updated_at": lot.updated_at.isoformat(),
        }


# Vista para cultivos (crops)
# 👌
class CropView(MethodView):
    """Clase para gestionar operaciones CRUD sobre cultivos."""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, id=None):
        """
        Obtiene una lista de cultivos o un cultivo específico.
        Args:
            crop_id (str, optional): ID del cultivo a consultar.
        Returns:
            JSON: Lista de cultivos o detalles de un cultivo específico.
        """
        crop_id = id
        if crop_id:
            return self._get_crop(crop_id)
        return self._get_crop_list()

    @check_permission(required_roles=["administrator", "reseller"])
    def post(self):
        """
        Crea un nuevo cultivo.
        Returns:
            JSON: Detalles del cultivo creado.
        """
        data = request.get_json()
        if not data or not all(k in data for k in ("name",)):
            raise BadRequest("Missing required fields.")
        return self._create_crop(data)

    @check_permission(resource_owner_check=True)
    def put(self, id):
        """
        Actualiza un cultivo existente.
        Args:
            crop_id (str): ID del cultivo a actualizar.
        Returns:
            JSON: Detalles del cultivo actualizado.
        """
        data = request.get_json()
        crop_id = data.get("id")
        if not data or not crop_id:
            raise BadRequest("Missing crop_id or data.")
        return self._update_crop(crop_id, data)

    @check_permission(resource_owner_check=True)
    def delete(self, id=None):
        """
        Elimina un cultivo existente.
        Args:
            crop_id (str): ID del cultivo a eliminar.
        Returns:
            JSON: Mensaje de confirmación.
        """
        data = request.get_json()
        if data and "ids" in data:
            return self._delete_crop(crop_ids=data["ids"])
        crop_id = id
        if crop_id:
            return self._delete_crop(crop_id=crop_id)
        raise BadRequest("Missing crop_id.")

    # Métodos auxiliares
    def _get_crop_list(self):
        """Obtiene una lista de todos los cultivos activos."""
        claims = get_jwt()
        user_role = claims.get("rol")
        user_id = claims.get("id")
        if user_role == RoleEnum.ADMINISTRATOR.value:
            if hasattr(Crop, "active"):
                crops = Crop.query.filter_by(active=True).all()
            else:
                crops = Crop.query.all()
        elif user_role == RoleEnum.RESELLER.value:
            reseller_package = ResellerPackage.query.filter_by(
                reseller_id=user_id
            ).first()
            if not reseller_package:
                raise NotFound("Reseller package not found.")
            crops = []
            for org in reseller_package.organizations:
                crops.extend(org.crops)
        else:
            raise Forbidden("Only administrators and resellers can list crops.")
        response_data = [self._serialize_crop(crop) for crop in crops]
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _get_crop(self, crop_id):
        """Obtiene los detalles de un cultivo específico."""
        crop = Crop.query.get_or_404(crop_id)
        claims = get_jwt()
        if not self._has_access(crop, claims):
            raise Forbidden("You do not have access to this crop.")
        response_data = self._serialize_crop(crop)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _create_crop(self, data):
        """Crea un nuevo cultivo con los datos proporcionados."""
        if hasattr(Crop, "active"):
            if Crop.query.filter_by(name=data["name"], active=True).first():
                raise BadRequest("Name already exists.")
        else:
            if Crop.query.filter_by(name=data["name"]).first():
                raise BadRequest("Name already exists.")
        crop = Crop(
            name=data["name"],
        )
        db.session.add(crop)
        db.session.commit()
        response_data = self._serialize_crop(crop)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=201, mimetype="application/json")

    def _update_crop(self, crop_id, data):
        """Actualiza los datos de un cultivo existente."""
        crop = Crop.query.get_or_404(crop_id)
        if "name" in data and data["name"] != crop.name:
            if hasattr(Crop, "active"):
                if Crop.query.filter_by(name=data["name"], active=True).first():
                    raise BadRequest("Name already exists.")
            else:
                if Crop.query.filter_by(name=data["name"]).first():
                    raise BadRequest("Name already exists.")
            crop.name = data["name"]
        db.session.commit()
        response_data = self._serialize_crop(crop)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _delete_crop(self, crop_id=None, crop_ids=None):
        """Elimina un cultivo marcándolo como inactivo."""
        claims = get_jwt()
        if crop_id and crop_ids:
            raise BadRequest("Solo se puede especificar crop_id o crop_ids, no ambos.")

        if crop_id:
            crop = Crop.query.get_or_404(crop_id)
            if hasattr(crop, "active"):
                crop.active = False
            else:
                db.session.delete(crop)
            db.session.commit()
            return jsonify({"message": "Crop deleted successfully"}), 200

        if crop_ids is not None:
            deleted_crops = []
            for crop_id in crop_ids:
                crop = Crop.query.get(crop_id)
                if not crop:
                    continue
                if hasattr(crop, "active"):
                    crop.active = False
                else:
                    db.session.delete(crop)
                deleted_crops.append(crop.name)
                db.session.commit()

            if deleted_crops:
                deleted_crops_str = ", ".join(deleted_crops)
                return (
                    jsonify(
                        {"message": f"Crops {deleted_crops_str} deleted successfully"}
                    ),
                    200,
                )
            return (
                jsonify(
                    {"error": "No crops were deleted due to permission restrictions"}
                ),
                403,
            )

    def _has_access(self, crop, claims):
        """Verifica si el usuario actual tiene acceso al recurso."""
        return check_resource_access(crop, claims)

    def _serialize_crop(self, crop):
        """Serializa un objeto Crop a un diccionario."""
        # Obtener los objetivos asociados al cultivo
        objectives_data = []
        for (
            objective
        ) in crop.objectives:  # Asumiendo que crop.objectives es la relación
            nutrient_targets = (
                db.session.query(objective_nutrients)
                .filter_by(objective_id=objective.id)
                .all()
            )
            objectives_data.extend(
                [
                    {
                        "nutrient_id": target.nutrient_id,
                        "target_value": target.target_value,
                        "nutrient_name": Nutrient.query.get(target.nutrient_id).name,
                        "nutrient_symbol": Nutrient.query.get(
                            target.nutrient_id
                        ).symbol,
                        "nutrient_unit": Nutrient.query.get(target.nutrient_id).unit,
                    }
                    for target in nutrient_targets
                ]
            )

        return {
            "id": crop.id,
            "name": crop.name,
            "created_at": crop.created_at.isoformat(),
            "updated_at": crop.updated_at.isoformat(),
            "objective_nutrients": objectives_data,  # Añadir los nutrientes objetivo
        }


# Vista para nutrientes (nutrients)
# 👌
class NutrientView(MethodView):
    """Clase para gestionar operaciones CRUD sobre nutrientes."""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, nutrient_id=None):
        """
        Obtiene una lista de nutrientes o un nutriente específico.
        Args:
            nutrient_id (str, optional): ID del nutriente a consultar.
        Returns:
            JSON: Lista de nutrientes o detalles de un nutriente específico.
        """
        if nutrient_id:
            return self._get_nutrient(nutrient_id)
        return self._get_nutrient_list()

    @check_permission(required_roles=["administrator", "reseller"])
    def post(self):
        """
        Crea un nuevo nutriente.
        Returns:
            JSON: Detalles del nutriente creado.
        """
        data = request.get_json()
        if not data or not all(k in data for k in ("name", "symbol", "unit")):
            raise BadRequest("Missing required fields.")
        return self._create_nutrient(data)

    @check_permission(resource_owner_check=True)
    def put(self, id: int):
        """
        Actualiza un nutriente existente.
        Args:
            nutrient_id (str): ID del nutriente a actualizar.
        Returns:
            JSON: Detalles del nutriente actualizado.
        """
        data = request.get_json()
        nutrient_id = id
        if not data or not nutrient_id:
            raise BadRequest("Missing nutrient_id or data.")
        return self._update_nutrient(nutrient_id, data)

    @check_permission(resource_owner_check=True)
    def delete(self, id=None):
        """
        Elimina un nutriente existente.
        Args:
            nutrient_id (str): ID del nutriente a eliminar.
        Returns:
            JSON: Mensaje de confirmación.
        """
        data = request.get_json()
        nutrient_id = id
        if data and "ids" in data:
            return self._delete_nutrient(nutrient_ids=data["ids"])
        if nutrient_id:
            return self._delete_nutrient(nutrient_id=nutrient_id)
        raise BadRequest("Missing nutrient_id.")

    # Métodos auxiliares
    def _get_nutrient_list(self):
        """Obtiene una lista de todos los nutrientes activos."""
        claims = get_jwt()
        user_role = claims.get("rol")
        user_id = claims.get("id")
        if user_role == RoleEnum.ADMINISTRATOR.value:
            if hasattr(Nutrient, "active"):
                nutrients = Nutrient.query.filter_by(active=True).all()
            else:
                nutrients = Nutrient.query.all()
        elif user_role == RoleEnum.RESELLER.value:
            reseller_package = ResellerPackage.query.filter_by(
                reseller_id=user_id
            ).first()
            if not reseller_package:
                raise NotFound("Reseller package not found.")
            nutrients = []
            for org in reseller_package.organizations:
                nutrients.extend(org.nutrients)
        else:
            raise Forbidden("Only administrators and resellers can list nutrients.")
        response_data = [self._serialize_nutrient(nutrient) for nutrient in nutrients]
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _get_nutrient(self, nutrient_id):
        """Obtiene los detalles de un nutriente específico."""
        nutrient = Nutrient.query.get_or_404(nutrient_id)
        claims = get_jwt()
        if not self._has_access(nutrient, claims):
            raise Forbidden("You do not have access to this nutrient.")
        response_data = self._serialize_nutrient(nutrient)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _create_nutrient(self, data):
        """Crea un nuevo nutriente con los datos proporcionados."""
        if hasattr(Nutrient, "active"):
            if Nutrient.query.filter_by(name=data["name"], active=True).first():
                raise BadRequest("Name already exists.")
        else:
            if Nutrient.query.filter_by(name=data["name"]).first():
                raise BadRequest("Name already exists.")
        nutrient = Nutrient(
            name=data["name"],
            symbol=data["symbol"],
            unit=data["unit"],
            cv=data.get("cv"),
        )
        db.session.add(nutrient)
        db.session.commit()
        response_data = self._serialize_nutrient(nutrient)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=201, mimetype="application/json")

    def _update_nutrient(self, nutrient_id, data):
        """Actualiza los datos de un nutriente existente."""
        nutrient = Nutrient.query.get_or_404(nutrient_id)
        if "name" in data and data["name"] != nutrient.name:
            if hasattr(Nutrient, "active"):
                if Nutrient.query.filter_by(name=data["name"], active=True).first():
                    raise BadRequest("Name already exists.")
            else:
                if Nutrient.query.filter_by(name=data["name"]).first():
                    raise BadRequest("Name already exists.")
            nutrient.name = data["name"]
        if "symbol" in data:
            nutrient.symbol = data["symbol"]
        if "unit" in data:
            nutrient.unit = data["unit"]
        if "cv" in data:
            nutrient.cv = data["cv"]
        db.session.commit()
        response_data = self._serialize_nutrient(nutrient)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _delete_nutrient(self, nutrient_id=None, nutrient_ids=None):
        """Elimina un nutriente marcándolo como inactivo."""
        claims = get_jwt()
        if nutrient_id and nutrient_ids:
            raise BadRequest(
                "Solo se puede especificar nutrient_id o nutrient_ids, no ambos."
            )

        if nutrient_id:
            nutrient = Nutrient.query.get_or_404(nutrient_id)
            if hasattr(nutrient, "active"):
                nutrient.active = False
            else:
                db.session.delete(nutrient)
            db.session.commit()
            return jsonify({"message": "Nutrient deleted successfully"}), 200

        if nutrient_ids is not None:
            deleted_nutrients = []
            for nutrient_id in nutrient_ids:
                nutrient = Nutrient.query.get(nutrient_id)
                if not nutrient:
                    continue
                if hasattr(nutrient, "active"):
                    nutrient.active = False
                else:
                    db.session.delete(nutrient)
                deleted_nutrients.append(nutrient.name)
                db.session.commit()

            if deleted_nutrients:
                deleted_nutrients_str = ", ".join(deleted_nutrients)
                return (
                    jsonify(
                        {
                            "message": f"Nutrients {deleted_nutrients_str} deleted successfully"
                        }
                    ),
                    200,
                )
            return (
                jsonify(
                    {
                        "error": "No nutrients were deleted due to permission restrictions"
                    }
                ),
                403,
            )

    def _has_access(self, nutrient, claims):
        """Verifica si el usuario actual tiene acceso al recurso."""
        return check_resource_access(nutrient, claims)

    def _serialize_nutrient(self, nutrient):
        """Serializa un objeto Nutrient a un diccionario."""
        return {
            "id": nutrient.id,
            "name": nutrient.name,
            "symbol": nutrient.symbol,
            "unit": nutrient.unit,
            "description": nutrient.description,
            "cv": nutrient.cv,
            "created_at": nutrient.created_at.isoformat(),
            "updated_at": nutrient.updated_at.isoformat(),
        }


# 👌
class ObjectiveView(MethodView):
    """Class to manage CRUD operations for nutrient objectives tied to crops"""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, objective_id=None):
        """
        Retrieve a list of objectives or a specific objective.
        Args:
            objective_id (int, optional): ID of the objective to retrieve.
        Returns:
            JSON: List of objectives or details of a specific objective.
        """
        if objective_id:
            return self._get_objective(objective_id)
        return self._get_objective_list()

    @check_permission(required_roles=["administrator", "reseller"])
    def post(self):
        """
        Create a new objective with nutrient targets, protein, rest, and target value.
        Expected JSON data:
            {
                "crop_id": int,
                "target_value": float,
                "protein": float (optional),
                "rest": float (optional),
                "nutrient_targets": {"nutrient_<id>": float, ...} (e.g., "nutrient_1": 10.5)
            }
        Returns:
            JSON: Details of the created objective.
        """
        data = request.get_json()
        required_fields = ["crop_id", "target_value"]
        if not data or not all(k in data for k in required_fields):
            raise BadRequest("Missing required fields: crop_id and target_value.")
        return self._create_objective(data)

    @check_permission(resource_owner_check=True)
    def put(self, id: int):
        """
        Update an existing objective.
        Args:
            objective_id (int): ID of the objective to update.
        Expected JSON data: Same as POST, with optional fields.
        Returns:
            JSON: Details of the updated objective.
        """
        data = request.get_json()
        objective_id = id

        if not data or not objective_id:
            raise BadRequest("Missing objective_id or data.")
        return self._update_objective(objective_id, data)

    @check_permission(resource_owner_check=True)
    def delete(self, id=None):
        """
        Delete an existing objective.
        Args:
            objective_id (int): ID of the objective to delete.
        Returns:
            JSON: Confirmation message.
        """
        objective_id = id

        if not objective_id:
            raise BadRequest("Missing objective_id.")
        return self._delete_objective(objective_id)

    # Helper Methods
    def _get_objective_list(self):
        """Retrieve a list of all objectives based on user role"""
        claims = get_jwt()
        user_role = claims.get("rol")
        if user_role == RoleEnum.ADMINISTRATOR.value:
            objectives = Objective.query.all()
        elif user_role == RoleEnum.RESELLER.value:
            reseller_package = ResellerPackage.query.filter_by(
                reseller_id=claims.get("org_id")
            ).first()
            if not reseller_package:
                raise NotFound("Reseller package not found.")
            objectives = []
            for organization in reseller_package.organizations:
                for crop in organization.crops:
                    objectives.extend(crop.objectives)
        else:
            raise Forbidden("Only administrators and resellers can list objectives.")
        response_data = [self._serialize_objective(obj) for obj in objectives]
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _get_objective(self, objective_id):
        """Retrieve details of a specific objective"""
        objective = Objective.query.get_or_404(objective_id)
        claims = get_jwt()
        if not self._has_access(objective, claims):
            raise Forbidden("You do not have access to this objective.")
        response_data = self._serialize_objective(objective)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _create_objective(self, data):
        """Create a new objective with nutrient targets"""
        crop_id = data["crop_id"]
        try:
            target_value = float(data["target_value"])  # Convert to float
        except (ValueError, TypeError):
            target_value = 0.0
        protein = data.get("protein")  # Optional
        rest = data.get("rest")  # Optional

        # Validate crop exists
        crop = Crop.query.get(crop_id)
        if not crop:
            raise BadRequest("Invalid crop ID.")

        # Convert optional fields to float if provided
        protein = float(data.get("protein", 0)) if data.get("protein") else None
        rest = float(data.get("rest", 0)) if data.get("rest") else None

        # Create new objective
        new_objective = Objective(
            crop_id=crop_id, target_value=target_value, protein=protein, rest=rest
        )
        db.session.add(new_objective)
        db.session.flush()  # Ensure new_objective.id is available

        # Handle nutrient targets
        nutrient_targets = {k: v for k, v in data.items() if k.startswith("nutrient_")}
        for key, value in nutrient_targets.items():
            nutrient_id = int(key.split("_")[1])
            nutrient = Nutrient.query.get(nutrient_id)
            if not nutrient:
                raise BadRequest(f"Invalid nutrient ID: {nutrient_id}")

            # Handle null or empty values
            if value is None or value == "":
                continue  # Skip this nutrient target if value is null or empty

            try:
                target_value_float = float(value)  # Convert to float
                if target_value_float < 0:
                    raise BadRequest(
                        f"Target value for {nutrient.name} must be positive."
                    )
                insert_stmt = objective_nutrients.insert().values(
                    objective_id=new_objective.id,
                    nutrient_id=nutrient_id,
                    target_value=target_value_float,
                )
                db.session.execute(insert_stmt)
            except ValueError:
                raise BadRequest(
                    f"Invalid numeric value for {nutrient.name}: '{value}'"
                )

        db.session.commit()
        response_data = self._serialize_objective(new_objective)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=201, mimetype="application/json")

    def _update_objective(self, objective_id, data):
        """Update an existing objective"""
        objective = Objective.query.get_or_404(objective_id)

        # Update main fields if provided and valid
        if "crop_id" in data:
            crop = Crop.query.get(data["crop_id"])
            if not crop:
                raise BadRequest("Invalid crop ID.")
            objective.crop_id = data["crop_id"]

        if "target_value" in data and data["target_value"]:
            try:
                objective.target_value = float(data["target_value"])
                if objective.target_value < 0:
                    raise BadRequest("Target value must be positive.")
            except ValueError:
                raise BadRequest("Target value must be a valid number.")

        if "protein" in data and data["protein"]:
            try:
                objective.protein = float(data["protein"])
                if objective.protein <= 0:
                    raise BadRequest("Protein value must be positive.")
            except ValueError:
                raise BadRequest("Protein value must be a valid number.")

        if "rest" in data and data["rest"]:
            try:
                objective.rest = float(data["rest"])
                if objective.rest <= 0:
                    raise BadRequest("Rest value must be positive.")
            except ValueError:
                raise BadRequest("Rest value must be a valid number.")

        # Handle nutrient targets if provided
        nutrient_targets = {k: v for k, v in data.items() if k.startswith("nutrient_")}
        if nutrient_targets:
            # Delete existing nutrient targets
            db.session.query(objective_nutrients).filter_by(
                objective_id=objective.id
            ).delete()
            # Add new nutrient targets
            for key, value in nutrient_targets.items():
                nutrient_id = int(key.split("_")[1])
                nutrient = Nutrient.query.get(nutrient_id)
                if not nutrient:
                    raise BadRequest(f"Invalid nutrient ID: {nutrient_id}")
                # Convert value to float and validate
                if value:
                    try:
                        target_value = float(value)
                        if target_value < 0:
                            raise BadRequest(
                                f"Target value for {nutrient.name} must be positive."
                            )
                        insert_stmt = objective_nutrients.insert().values(
                            objective_id=objective.id,
                            nutrient_id=nutrient_id,
                            target_value=target_value,
                        )
                        db.session.execute(insert_stmt)
                    except ValueError:
                        raise BadRequest(
                            f"Target value for {nutrient.name} must be a valid number."
                        )

        db.session.commit()
        response_data = self._serialize_objective(objective)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _delete_objective(self, objective_id):
        """Delete an existing objective"""
        objective = Objective.query.get_or_404(objective_id)
        db.session.delete(objective)
        db.session.commit()
        return jsonify({"message": "Objective deleted successfully"}), 200

    def _has_access(self, objective, claims):
        """Check if the current user has access to the objective"""
        return check_resource_access(objective, claims)

    def _serialize_objective(self, objective):
        """Serialize an Objective object to a dictionary"""
        nutrient_targets = (
            db.session.query(objective_nutrients)
            .filter_by(objective_id=objective.id)
            .order_by(objective_nutrients.c.nutrient_id)
            .all()
        )
        nutrient_targets_dict = [
            {
                "nutrient_id": target.nutrient_id,
                "target_value": target.target_value,
                "nutrient_name": Nutrient.query.get(target.nutrient_id).name,
                "nutrient_symbol": Nutrient.query.get(target.nutrient_id).symbol,
                "nutrient_unit": Nutrient.query.get(target.nutrient_id).unit,
            }
            for target in nutrient_targets
        ]
        return {
            "id": objective.id,
            "crop_id": objective.crop_id,
            "crop_name": objective.crop.name,
            "target_value": objective.target_value,
            "protein": objective.protein,
            "rest": objective.rest,
            "created_at": objective.created_at.isoformat(),
            "updated_at": objective.updated_at.isoformat(),
            "nutrient_targets": nutrient_targets_dict,
        }


# Example Usage
# Create an Objective (POST)
# json

# {
#     "crop_id": 1,
#     "target_value": 100.0,
#     "protein": 20.5,
#     "rest": 15.0,
#     "nutrient_1": 10.5,  // Nitrogen target
#     "nutrient_2": 5.0    // Phosphorus target
# }

# Response
# json

# {
#     "id": 1,
#     "crop_id": 1,
#     "target_value": 100.0,
#     "protein": 20.5,
#     "rest": 15.0,
#     "created_at": "2025-03-13T12:00:00",
#     "updated_at": "2025-03-13T12:00:00",
#     "nutrient_targets": [
#         {
#             "nutrient_id": 1,
#             "target_value": 10.5,
#             "nutrient_name": "Nitrogen",
#             "nutrient_symbol": "N",
#             "nutrient_unit": "mg/L"
#         },
#         {
#             "nutrient_id": 2,
#             "target_value": 5.0,
#             "nutrient_name": "Phosphorus",
#             "nutrient_symbol": "P",
#             "nutrient_unit": "mg/L"
#         }
#     ]
# }

# Update an Objective (PUT)
# json

# {
#     "target_value": 120.0,
#     "nutrient_1": 12.0
# }


# 👌
class ProductView(MethodView):
    """Class to manage CRUD operations for products"""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, product_id=None):
        """
        Retrieve a list of products or a specific product
        Args:
            product_id (int, optional): ID of the product to retrieve
        Returns:
            JSON: List of products or details of a specific product
        """
        if product_id:
            return self._get_product(product_id)
        return self._get_product_list()

    @check_permission(required_roles=["administrator", "reseller"])
    def post(self):
        """
        Create a new product
        Returns:
            JSON: Details of the created product
        """
        data = request.get_json()
        required_fields = ["name", "description"]
        if not data or not all(k in data for k in required_fields):
            raise BadRequest("Missing required fields")
        return self._create_product(data)

    @check_permission(resource_owner_check=True)
    def put(self, id: int):
        """
        Update an existing product
        Args:
            product_id (int): ID of the product to update
        Returns:
            JSON: Details of the updated product
        """
        data = request.get_json()
        product_id = id
        if not data or not product_id:
            raise BadRequest("Missing product_id or data")
        return self._update_product(product_id, data)

    @check_permission(resource_owner_check=True)
    def delete(self, id=None):
        """
        Delete an existing product
        Args:
            product_id (int): ID of the product to delete
        Returns:
            JSON: Confirmation message
        """
        product_id = id
        if not product_id:
            raise BadRequest("Missing product_id")
        return self._delete_product(product_id)

    # Helper Methods
    def _get_product_list(self):
        """Retrieve a list of all products"""
        claims = get_jwt()
        user_role = claims.get("rol")
        if user_role == RoleEnum.ADMINISTRATOR.value:
            products = Product.query.all()
        elif user_role == RoleEnum.RESELLER.value:
            reseller_package = ResellerPackage.query.filter_by(
                reseller_id=claims.get("org_id")
            ).first()
            if not reseller_package:
                raise NotFound("Reseller package not found.")
            products = []
            for organization in reseller_package.organizations:
                products.extend(organization.products)
        else:
            raise Forbidden("Only administrators and resellers can list products")
        response_data = [self._serialize_product(p) for p in products]
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _get_product(self, product_id):
        """Retrieve details of a specific product"""
        product = Product.query.get_or_404(product_id)
        claims = get_jwt()
        if not self._has_access(product, claims):
            raise Forbidden("You do not have access to this product")
        response_data = self._serialize_product(product)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _create_product(self, data):
        """Create a new product"""
        name = data["name"]
        description = data["description"]
        product = Product(name=name, description=description)
        db.session.add(product)
        db.session.commit()
        response_data = self._serialize_product(product)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=201, mimetype="application/json")

    def _update_product(self, product_id, data):
        """Update an existing product"""
        product = Product.query.get_or_404(product_id)
        if "name" in data:
            product.name = data["name"]
        if "description" in data:
            product.description = data["description"]
        db.session.commit()
        response_data = self._serialize_product(product)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _delete_product(self, product_id):
        """Delete an existing product"""
        product = Product.query.get_or_404(product_id)
        db.session.delete(product)
        db.session.commit()
        return jsonify({"message": "Product deleted successfully"}), 200

    def _has_access(self, product, claims):
        """Check if the current user has access to the product"""
        return check_resource_access(product, claims)

    def _serialize_product(self, product):
        """Serialize a Product object to a dictionary"""
        return {
            "id": product.id,
            "name": product.name,
            "description": product.description,
            "created_at": product.created_at.isoformat(),
            "updated_at": product.updated_at.isoformat(),
        }


# 👌
class ProductContributionView(MethodView):
    """Class to manage CRUD operations for product contributions"""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator"])
    def get(self, product_contribution_id=None):
        """
        Retrieve a list of product contributions or a specific product contribution
        Args:
            product_contribution_id (int, optional): ID of the product contribution to retrieve
        Returns:
            JSON: List of product contributions or details of a specific product contribution
        """
        if product_contribution_id:
            return self._get_product_contribution(product_contribution_id)
        return self._get_product_contribution_list()

    @check_permission(required_roles=["administrator"])
    def post(self):
        """
        Create a new product contribution
        Expected JSON data:
            {
                "product_id": int,
                "nutrient_contributions": {"nutrient_<id>": float, ...} (e.g., "nutrient_1": 10.5)
            }
        Returns:
            JSON: Details of the created product contribution
        """
        data = request.get_json()
        required_fields = ["product_id"]
        if not data or not all(k in data for k in required_fields):
            raise BadRequest("Missing required fields: product_id")
        return self._create_product_contribution(data)

    @check_permission(required_roles=["administrator"])
    def put(self, id: int):
        """
        Update an existing product contribution
        Args:
            product_contribution_id (int): ID of the product contribution to update
        Expected JSON data: Same as POST, with optional fields
        Returns:
            JSON: Details of the updated product contribution
        """
        data = request.get_json()
        product_contribution_id = id
        if not data or not product_contribution_id:
            raise BadRequest("Missing product_contribution_id or data")
        return self._update_product_contribution(product_contribution_id, data)

    @check_permission(required_roles=["administrator"])
    def delete(self, id=None):
        """
        Delete an existing product contribution
        Args:
            product_contribution_id (int): ID of the product contribution to delete
        Returns:
            JSON: Confirmation message
        """
        product_contribution_id = id
        if not product_contribution_id:
            raise BadRequest("Missing product_contribution_id")
        return self._delete_product_contribution(product_contribution_id)

    # Helper Methods
    def _get_product_contribution_list(self):
        """Retrieve a list of all product contributions"""
        product_contributions = ProductContribution.query.all()
        response_data = [
            self._serialize_product_contribution(pc) for pc in product_contributions
        ]
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _get_product_contribution(self, product_contribution_id):
        """Retrieve details of a specific product contribution"""
        product_contribution = ProductContribution.query.get_or_404(
            product_contribution_id
        )
        response_data = self._serialize_product_contribution(product_contribution)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _create_product_contribution(self, data):
        """Create a new product contribution"""
        product_id = data["product_id"]
        product = Product.query.get(product_id)
        if not product:
            raise BadRequest("Invalid product ID")
        product_contribution = ProductContribution(product_id=product_id)
        db.session.add(product_contribution)
        db.session.flush()  # Ensure new_objective.id is available
        # Handle nutrient contributions
        nutrient_contributions = {
            k: v for k, v in data.items() if k.startswith("nutrient_")
        }
        for key, value in nutrient_contributions.items():
            if value in (None, "", "null"):
                continue
            nutrient_id = int(key.split("_")[1])
            nutrient = Nutrient.query.get(nutrient_id)
            if not nutrient:
                raise BadRequest(f"Invalid nutrient ID: {nutrient_id}")
            try:
                contribution = float(value)  # Convert to float
                if contribution < 0:
                    raise BadRequest(
                        f"Contribution for {nutrient.name} must be non-negative."
                    )
                insert_stmt = product_contribution_nutrients.insert().values(
                    product_contribution_id=product_contribution.id,
                    nutrient_id=nutrient_id,
                    contribution=contribution,
                )
                db.session.execute(insert_stmt)
            except ValueError:
                raise BadRequest(
                    f"Invalid numeric value for {nutrient.name}: '{value}'"
                )
        db.session.commit()
        response_data = self._serialize_product_contribution(product_contribution)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=201, mimetype="application/json")

    def _update_product_contribution(self, product_contribution_id, data):
        """Update an existing product contribution"""
        product_contribution = ProductContribution.query.get_or_404(
            product_contribution_id
        )
        # Update main fields if provided
        if "product_id" in data:
            product = Product.query.get(data["product_id"])
            if not product:
                raise BadRequest("Invalid product ID")
            product_contribution.product_id = data["product_id"]
        # Handle nutrient contributions if provided
        nutrient_contributions = {
            k: v for k, v in data.items() if k.startswith("nutrient_")
        }
        if nutrient_contributions:
            # Delete existing nutrient contributions
            db.session.query(product_contribution_nutrients).filter_by(
                product_contribution_id=product_contribution.id
            ).delete()
            # Add new nutrient contributions
            for key, value in nutrient_contributions.items():
                if value in (None, "", "null"):
                    continue
                nutrient_id = int(key.split("_")[1])
                nutrient = Nutrient.query.get(nutrient_id)
                if not nutrient:
                    raise BadRequest(f"Invalid nutrient ID: {nutrient_id}")
                # Convert value to float (or int) and validate
                try:
                    contribution = float(
                        value
                    )  # Use float to handle decimal values; use int if only integers are expected
                    if contribution < 0:
                        raise BadRequest(
                            f"Contribution for {nutrient.name} must be non-negative."
                        )
                    insert_stmt = product_contribution_nutrients.insert().values(
                        product_contribution_id=product_contribution.id,
                        nutrient_id=nutrient_id,
                        contribution=contribution,
                    )
                    db.session.execute(insert_stmt)
                except ValueError:
                    raise BadRequest(
                        f"Contribution for {nutrient.name} must be a valid number."
                    )
        db.session.commit()
        response_data = self._serialize_product_contribution(product_contribution)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _delete_product_contribution(self, product_contribution_id):
        """Delete an existing product contribution"""
        product_contribution = ProductContribution.query.get_or_404(
            product_contribution_id
        )
        db.session.delete(product_contribution)
        db.session.commit()
        return jsonify({"message": "Product contribution deleted successfully"}), 200

    def _serialize_product_contribution(self, product_contribution):
        """Serialize a ProductContribution object to a dictionary"""
        nutrient_contributions = (
            db.session.query(product_contribution_nutrients)
            .filter_by(product_contribution_id=product_contribution.id)
            .all()
        )
        nutrient_contributions_dict = [
            {
                "nutrient_id": contribution.nutrient_id,
                "contribution": contribution.contribution,
                "nutrient_name": Nutrient.query.get(contribution.nutrient_id).name,
                "nutrient_symbol": Nutrient.query.get(contribution.nutrient_id).symbol,
                "nutrient_unit": Nutrient.query.get(contribution.nutrient_id).unit,
            }
            for contribution in nutrient_contributions
        ]
        return {
            "id": product_contribution.id,
            "product_id": product_contribution.product_id,
            "product_name": product_contribution.product.name,
            "created_at": product_contribution.created_at.isoformat(),
            "updated_at": product_contribution.updated_at.isoformat(),
            "nutrient_contributions": nutrient_contributions_dict,
        }


# 👌
class ProductPriceView(MethodView):
    """Class to manage CRUD operations for product prices"""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, product_price_id=None):
        """
        Retrieve a list of product prices or a specific product price
        Args:
            product_price_id (int, optional): ID of the product price to retrieve
        Returns:
            JSON: List of product prices or details of a specific product price
        """
        if product_price_id:
            return self._get_product_price(product_price_id)
        return self._get_product_price_list()

    @check_permission(required_roles=["administrator"])
    def post(self):
        """
        Create a new product price
        Returns:
            JSON: Details of the created product price
        """
        data = request.get_json()
        required_fields = ["product_id", "price", "start_date", "end_date"]
        if not data or not all(k in data for k in required_fields):
            raise BadRequest("Missing required fields")
        return self._create_product_price(data)

    @check_permission(required_roles=["administrator"])
    def put(self, id: int):
        """
        Update an existing product price
        Args:
            product_price_id (int): ID of the product price to update
        Returns:
            JSON: Details of the updated product price
        """
        data = request.get_json()
        product_price_id = id
        if not data or not product_price_id:
            raise BadRequest("Missing product_price_id or data")
        return self._update_product_price(product_price_id, data)

    @check_permission(required_roles=["administrator"])
    def delete(self, id=None):
        """
        Delete an existing product price
        Args:
            product_price_id (int): ID of the product price to delete
        Returns:
            JSON: Confirmation message
        """
        product_price_id = id
        if not product_price_id:
            raise BadRequest("Missing product_price_id")
        return self._delete_product_price(product_price_id)

    # Helper Methods
    def _get_product_price_list(self):
        """Retrieve a list of all product prices"""
        claims = get_jwt()
        user_role = claims.get("rol")
        if user_role == RoleEnum.ADMINISTRATOR.value:
            product_prices = ProductPrice.query.all()
        elif user_role == RoleEnum.RESELLER.value:
            reseller_package = ResellerPackage.query.filter_by(
                reseller_id=claims.get("org_id")
            ).first()
            if not reseller_package:
                raise NotFound("Reseller package not found.")
            product_prices = []
            for organization in reseller_package.organizations:
                for product in organization.products:
                    product_prices.extend(product.product_prices)
        else:
            raise Forbidden("Only administrators and resellers can list product prices")
        response_data = [self._serialize_product_price(pp) for pp in product_prices]
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _get_product_price(self, product_price_id):
        """Retrieve details of a specific product price"""
        product_price = ProductPrice.query.get_or_404(product_price_id)
        claims = get_jwt()
        if not self._has_access(product_price, claims):
            raise Forbidden("You do not have access to this product price")
        response_data = self._serialize_product_price(product_price)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _create_product_price(self, data):
        """Create a new product price"""
        product_id = data["product_id"]
        # Verificar si ya existe un precio para el producto
        existing_price = ProductPrice.query.filter_by(product_id=product_id).first()
        if existing_price:
            raise Conflict("Ya existe un precio para este producto")
        price = data["price"]
        supplier = data.get("supplier")
        start_date_str = data.get("start_date")
        end_date_str = data.get("end_date")

        if start_date_str:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        else:
            start_date = date.today()

        if end_date_str:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        else:
            end_date = start_date + timedelta(days=365)

        product_price = ProductPrice(
            product_id=product_id,
            price=price,
            supplier=supplier,
            start_date=start_date,
            end_date=end_date,
        )
        db.session.add(product_price)
        db.session.commit()
        response_data = self._serialize_product_price(product_price)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=201, mimetype="application/json")

    def _update_product_price(self, product_price_id, data):
        """Update an existing product price"""
        product_price = ProductPrice.query.get_or_404(product_price_id)
        if "price" in data:
            product_price.price = data["price"]
        if "supplier" in data:
            product_price.supplier = data["supplier"]
        if "start_date" in data:
            product_price.start_date = datetime.strptime(
                data["start_date"], "%Y-%m-%d"
            ).date()
        if "end_date" in data:
            product_price.end_date = datetime.strptime(
                data["end_date"], "%Y-%m-%d"
            ).date()
        db.session.commit()
        response_data = self._serialize_product_price(product_price)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _delete_product_price(self, product_price_id):
        """Delete an existing product price"""
        product_price = ProductPrice.query.get_or_404(product_price_id)
        db.session.delete(product_price)
        db.session.commit()
        return jsonify({"message": "Product price deleted successfully"}), 200

    def _has_access(self, product_price, claims):
        """Check if the current user has access to the product price"""
        return check_resource_access(product_price, claims)

    def _serialize_product_price(self, product_price):
        """Serialize a ProductPrice object to a dictionary"""
        return {
            "id": product_price.id,
            "product_id": product_price.product_id,
            "product_name": product_price.product.name,
            "price": product_price.price,
            "supplier": product_price.supplier,
            "start_date": (
                product_price.start_date.isoformat()
                if product_price.start_date
                else None
            ),
            "end_date": (
                product_price.end_date.isoformat() if product_price.end_date else None
            ),
            "created_at": (
                product_price.created_at.isoformat()
                if product_price.created_at
                else None
            ),
            "updated_at": (
                product_price.updated_at.isoformat()
                if product_price.updated_at
                else None
            ),
        }


# 👌# Vista para análisis comunes (common_analyses)
class CommonAnalysisView(MethodView):
    """Clase para gestionar operaciones CRUD sobre análisis comunes."""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, common_analysis_id=None):
        """
        Obtiene una lista de análisis comunes o un análisis común específico.
        Args:
            common_analysis_id (str, optional): ID del análisis común a consultar.
        Returns:
            JSON: Lista de análisis comunes o detalles de un análisis común específico.
        """
        if common_analysis_id:
            return self._get_common_analysis(common_analysis_id)
        return self._get_common_analysis_list()

    @check_permission(required_roles=["administrator", "reseller"])
    def post(self):
        """
        Crea un nuevo análisis común.
        Returns:
            JSON: Detalles del análisis común creado.
        """
        data = request.get_json()
        if not data or not all(
            k in data
            for k in (
                "lot_id",
                "protein",
                "energy",
                "rest",
                "rest_days",
                "month",
            )
        ):
            raise BadRequest("Missing required fields.")
        return self._create_common_analysis(data)

    @check_permission(resource_owner_check=True)
    def put(self, id):
        """
        Actualiza un análisis común existente.
        Args:
            common_analysis_id (str): ID del análisis común a actualizar.
        Returns:
            JSON: Detalles del análisis común actualizado.
        """
        data = request.get_json()
        common_analysis_id = id
        if not data or not common_analysis_id:
            raise BadRequest("Missing common_analysis_id or data.")
        return self._update_common_analysis(common_analysis_id, data)

    @check_permission(resource_owner_check=True)
    def delete(self, id=None):
        """
        Elimina un análisis común existente.
        Args:
            common_analysis_id (str): ID del análisis común a eliminar.
        Returns:
            JSON: Mensaje de confirmación.
        """
        data = request.get_json()
        common_analysis_id = id
        if data and "ids" in data:
            return self._delete_common_analysis(common_analysis_ids=data["ids"])
        if common_analysis_id:
            return self._delete_common_analysis(common_analysis_id=common_analysis_id)
        raise BadRequest("Missing common_analysis_id.")

    # Métodos auxiliares
    def _get_common_analysis_list(self, filter_by=None):
        """
        Obtiene una lista de todos los análisis comunes activos según el rol del usuario.

        Args:
            filter_by (int): Filtro por ID de finca.

        Returns:
            Response: Lista de análisis comunes en formato JSON.
        """
        claims = get_jwt()
        user_role = claims.get("rol")
        user_id = claims.get("id")
        user_org = claims.get("organizations", [])

        common_analyses = []  # Lista de análisis comunes que se devolverá

        if user_role == RoleEnum.ADMINISTRATOR.value:
            query = CommonAnalysis.query
            if hasattr(CommonAnalysis, "active"):
                query = query.filter_by(active=True)
            if filter_by:
                query = query.join(Lot).join(Farm).filter(Farm.id == filter_by)
        elif user_role == RoleEnum.RESELLER.value:
            reseller_package = (
                ResellerPackage.query.options(
                    joinedload(ResellerPackage.organizations).joinedload("farms")
                )
                .filter_by(reseller_id=user_id)
                .first()
            )
            if not reseller_package:
                raise NotFound("Reseller package not found.")

            if filter_by:
                query = (
                    CommonAnalysis.query.join(Lot)
                    .join(Farm)
                    .filter(Farm.id == filter_by)
                    .join(
                        ResellerPackage.organizations,
                        Farm.organization_id == Organization.id,
                    )
                    .filter(Organization.id.in_(reseller_package.organization_ids))
                )
            else:
                query = (
                    CommonAnalysis.query.join(Lot)
                    .join(Farm)
                    .join(
                        ResellerPackage.organizations,
                        Farm.organization_id == Organization.id,
                    )
                    .filter(Organization.id.in_(reseller_package.organization_ids))
                )
        elif user_role == RoleEnum.ORG_ADMIN.value:
            org_ids = [org["id"] for org in user_org]
            if not org_ids:
                raise Forbidden("User is not associated with any organization.")

            if filter_by:
                query = (
                    CommonAnalysis.query.join(Lot)
                    .join(Farm)
                    .filter(Farm.id == filter_by)
                    .filter(Farm.org_id.in_(org_ids))
                )
            else:
                query = (
                    CommonAnalysis.query.join(Lot)
                    .join(Farm)
                    .filter(Farm.org_id.in_(org_ids))
                )
        else:
            raise Forbidden("You can't list common_analyses.")

        common_analyses = query.all()

        # Serialización y respuesta
        response_data = [
            self._serialize_common_analysis(common_analysis)
            for common_analysis in common_analyses
        ]
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _get_common_analysis(self, common_analysis_id):
        """Obtiene los detalles de un análisis común específico."""
        common_analysis = CommonAnalysis.query.get_or_404(common_analysis_id)
        claims = get_jwt()
        if not self._has_access(common_analysis, claims):
            raise Forbidden("You do not have access to this common_analysis.")
        response_data = self._serialize_common_analysis(common_analysis)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _create_common_analysis(self, data):
        """Crea un nuevo análisis común con los datos proporcionados."""
        date_str = data.get("date")
        if date_str:
            analysis_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        else:
            analysis_date = date.today()

        if CommonAnalysis.query.filter_by(
            date=analysis_date, lot_id=data["lot_id"]
        ).first():
            raise BadRequest("CommonAnalysis already exists.")
        common_analysis = CommonAnalysis(
            date=analysis_date,
            lot_id=data["lot_id"],
            protein=data["protein"],
            rest=data["rest"],
            energy=data["energy"],
            yield_estimate=data["yield_estimate"],
            rest_days=data["rest_days"],
            month=data["month"],
        )
        db.session.add(common_analysis)
        db.session.commit()
        response_data = self._serialize_common_analysis(common_analysis)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=201, mimetype="application/json")

    def _update_common_analysis(self, common_analysis_id, data):
        """Actualiza los datos de un análisis común existente."""
        common_analysis = CommonAnalysis.query.get_or_404(common_analysis_id)
        if "date" in data:
            common_analysis.date = datetime.strptime(data["date"], "%Y-%m-%d").date()
        if "lot_id" in data:
            common_analysis.lot_id = data["lot_id"]
        if "protein" in data:
            common_analysis.protein = data["protein"]
        if "rest" in data:
            common_analysis.rest = data["rest"]
        if "energy" in data:
            common_analysis.energy = data["energy"]
        if "yield_estimate" in data:
            common_analysis.yield_estimate = data["yield_estimate"]
        if "rest_days" in data:
            common_analysis.rest_days = data["rest_days"]
        if "month" in data:
            common_analysis.month = data["month"]
        db.session.commit()
        response_data = self._serialize_common_analysis(common_analysis)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _delete_common_analysis(
        self, common_analysis_id=None, common_analysis_ids=None
    ):
        """Elimina un análisis común marcándolo como inactivo."""
        claims = get_jwt()
        if common_analysis_id and common_analysis_ids:
            raise BadRequest(
                "Solo se puede especificar common_analysis_id o common_analysis_ids, no ambos."
            )
        if common_analysis_id:
            common_analysis = CommonAnalysis.query.get_or_404(common_analysis_id)
            db.session.delete(common_analysis)
            db.session.commit()
            return jsonify({"message": "CommonAnalysis deleted successfully"}), 200
        if common_analysis_ids:
            deleted_common_analyses = []
            for common_analysis_id in common_analysis_ids:
                common_analysis = CommonAnalysis.query.get(common_analysis_id)
                if not common_analysis:
                    continue
                db.session.delete(common_analysis)
                deleted_common_analyses.append(common_analysis.lot_id)
                db.session.commit()
                deleted_common_analyses_str = ", ".join(
                    map(str, deleted_common_analyses)
                )
            return (
                jsonify(
                    {
                        "message": f"CommonAnalyses {deleted_common_analyses_str} deleted successfully"
                    }
                ),
                200,
            )

    def _has_access(self, common_analysis, claims):
        """Verifica si el usuario actual tiene acceso al recurso."""
        return check_resource_access(common_analysis, claims)

    def _serialize_common_analysis(self, common_analysis):
        """Serializa un objeto CommonAnalysis a un diccionario."""
        return {
            "id": common_analysis.id,
            "date": common_analysis.date.isoformat() if common_analysis.date else None,
            "lot_id": common_analysis.lot_id,
            "lot_name": common_analysis.lot.name,
            "lot_area": common_analysis.lot.area,
            "farm_name": common_analysis.lot.farm.name,
            "protein": common_analysis.protein,
            "energy": common_analysis.energy,
            "rest": common_analysis.rest,
            "rest_days": common_analysis.rest_days,
            "yield_estimate": common_analysis.yield_estimate,
            "month": common_analysis.month,
            "created_at": (
                common_analysis.created_at.isoformat()
                if common_analysis.created_at
                else None
            ),
            "updated_at": (
                common_analysis.updated_at.isoformat()
                if common_analysis.updated_at
                else None
            ),
        }


# Vista para lotes de cultivos (lot_crops)
# 👌
class LotCropView(MethodView):
    """Clase para gestionar operaciones CRUD sobre la relación entre lotes y cultivos."""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, lot_crop_id=None):
        """
        Obtiene una lista de relaciones lot-crop o una relación específica.
        Args:
            lot_crop_id (int, optional): ID de la relación lot-crop a consultar.
        Returns:
            JSON: Lista de relaciones o detalles de una relación específica.
        """
        if lot_crop_id:
            return self._get_lot_crop(lot_crop_id)
        return self._get_lot_crop_list()

    @check_permission(required_roles=["administrator", "reseller"])
    def post(self):
        """
        Crea una nueva relación lot-crop.
        Returns:
            JSON: Detalles de la relación creada.
        """
        data = request.get_json()
        if not data or not all(k in data for k in ("lot_id", "crop_id", "start_date")):
            raise BadRequest("Missing required fields.")
        return self._create_lot_crop(data)

    @check_permission(resource_owner_check=True)
    def put(self, id: int):
        """
        Actualiza una relación lot-crop existente.
        Args:
            lot_crop_id (int): ID de la relación a actualizar.
        Returns:
            JSON: Detalles de la relación actualizada.
        """
        data = request.get_json()
        lot_crop_id = data.get("id")
        if not data or not lot_crop_id:
            raise BadRequest("Missing lot_crop_id or data.")
        return self._update_lot_crop(lot_crop_id, data)

    @check_permission(resource_owner_check=True)
    def delete(self, id=None):
        """
        Elimina una relación lot-crop existente.
        Args:
            lot_crop_id (int): ID de la relación a eliminar.
        Returns:
            JSON: Mensaje de confirmación.
        """
        data = request.get_json()
        lot_crop_id = id
        if data and "ids" in data:
            return self._delete_lot_crop(lot_crop_ids=data["ids"])
        if lot_crop_id:
            return self._delete_lot_crop(lot_crop_id=lot_crop_id)
        raise BadRequest("Missing lot_crop_id.")

    # Métodos auxiliares
    def _get_lot_crop_list(self):
        """Obtiene una lista de todas las relaciones lot-crop."""
        claims = get_jwt()
        user_role = claims.get("rol")
        org_id = claims.get("org_id")
        if user_role == RoleEnum.ADMINISTRATOR.value:
            lot_crops = LotCrop.query.all()
        elif user_role == RoleEnum.RESELLER.value:
            reseller_package = ResellerPackage.query.filter_by(
                reseller_id=org_id
            ).first()
            if not reseller_package:
                raise NotFound("Reseller package not found.")
            lot_crops = []
            for org in reseller_package.organizations:
                for farm in org.farms:
                    lot_crops.extend(farm.lot_crops)
        else:
            # Filtra por organización del usuario
            lot_crops = (
                LotCrop.query.join(Lot).join(Farm).filter(Farm.org_id == org_id).all()
            )
        response_data = [self._serialize_lot_crop(lot_crop) for lot_crop in lot_crops]
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _get_lot_crop(self, lot_crop_id):
        """Obtiene los detalles de una relación lot-crop específica."""
        lot_crop = LotCrop.query.get_or_404(lot_crop_id)
        claims = get_jwt()
        if not self._has_access(lot_crop, claims):
            raise Forbidden("You do not have access to this lot-crop.")
        response_data = self._serialize_lot_crop(lot_crop)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _create_lot_crop(self, data):
        """Crea una nueva relación lot-crop con los datos proporcionados."""
        # Verificar si el lote y el cultivo existen
        lot = Lot.query.get_or_404(data["lot_id"])
        crop = Crop.query.get_or_404(data["crop_id"])

        # Convertir las fechas de entrada a objetos datetime
        new_start_date = datetime.fromisoformat(data["start_date"])
        new_end_date = (
            datetime.fromisoformat(data["end_date"]) if data.get("end_date") else None
        )

        # Verificar si ya existe un cultivo activo (sin fecha de fin) en el lote
        active_crop = (
            LotCrop.query.filter_by(lot_id=data["lot_id"])
            .filter(LotCrop.end_date.is_(None))
            .first()
        )
        if active_crop:
            raise BadRequest(
                "There is an active crop in this lot. Please close it before starting a new one."
            )

        # Verificar solapamiento con cultivos existentes
        existing_crops = LotCrop.query.filter_by(lot_id=data["lot_id"]).all()
        for existing in existing_crops:
            existing_start = existing.start_date
            existing_end = (
                existing.end_date if existing.end_date else datetime.max
            )  # Si no hay end_date, asumir que sigue activo

            # Comprobar si hay solapamiento
            if (new_start_date <= existing_end) and (
                new_end_date is None or new_end_date >= existing_start
            ):
                raise BadRequest(
                    "The new crop dates overlap with an existing crop in this lot."
                )

        # Verificar duplicados (misma combinación de lote, cultivo y fecha de inicio)
        if LotCrop.query.filter_by(
            lot_id=data["lot_id"],
            crop_id=data["crop_id"],
            start_date=data["start_date"],
        ).first():
            raise BadRequest("This lot-crop relationship already exists.")

        # Crear el nuevo cultivo
        lot_crop = LotCrop(
            lot_id=data["lot_id"],
            crop_id=data["crop_id"],
            start_date=data["start_date"],
            end_date=data.get("end_date"),
        )
        db.session.add(lot_crop)
        db.session.commit()
        response_data = self._serialize_lot_crop(lot_crop)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=201, mimetype="application/json")

    def _update_lot_crop(self, lot_crop_id, data):
        """Actualiza los datos de una relación lot-crop existente."""
        lot_crop = LotCrop.query.get_or_404(lot_crop_id)

        # Nuevas fechas propuestas
        new_lot_id = data.get("lot_id", lot_crop.lot_id)
        new_start_date = (
            datetime.fromisoformat(data["start_date"])
            if "start_date" in data
            else lot_crop.start_date
        )
        new_end_date = (
            datetime.fromisoformat(data["end_date"])
            if data.get("end_date")
            else lot_crop.end_date
        )

        # Si se cambia el lote o las fechas, validar solapamientos
        if "lot_id" in data or "start_date" in data or "end_date" in data:
            # Verificar si el lote existe
            if "lot_id" in data and data["lot_id"] != lot_crop.lot_id:
                Lot.query.get_or_404(data["lot_id"])

            # Verificar solapamiento con otros cultivos en el lote
            existing_crops = LotCrop.query.filter(
                LotCrop.lot_id == new_lot_id, LotCrop.id != lot_crop_id
            ).all()
            for existing in existing_crops:
                existing_start = existing.start_date
                existing_end = existing.end_date if existing.end_date else datetime.max

                if (new_start_date <= existing_end) and (
                    new_end_date is None or new_end_date >= existing_start
                ):
                    raise BadRequest(
                        "The updated crop dates overlap with an existing crop in this lot."
                    )

        # Actualizar los campos
        if "lot_id" in data and data["lot_id"] != lot_crop.lot_id:
            lot_crop.lot_id = data["lot_id"]

        if "crop_id" in data and data["crop_id"] != lot_crop.crop_id:
            Crop.query.get_or_404(data["crop_id"])  # Verificar que el cultivo existe
            lot_crop.crop_id = data["crop_id"]

        if "start_date" in data:
            lot_crop.start_date = data["start_date"]

        if "end_date" in data:
            lot_crop.end_date = data["end_date"]

        db.session.commit()
        response_data = self._serialize_lot_crop(lot_crop)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _delete_lot_crop(self, lot_crop_id=None, lot_crop_ids=None):
        """Elimina una o varias relaciones lot-crop."""
        claims = get_jwt()
        if lot_crop_id and lot_crop_ids:
            raise BadRequest(
                "Solo se puede especificar lot_crop_id o lot_crop_ids, no ambos."
            )

        if lot_crop_id:
            lot_crop = LotCrop.query.get_or_404(lot_crop_id)
            if not self._has_access(lot_crop, claims):
                raise Forbidden("You do not have access to this lot-crop.")
            db.session.delete(lot_crop)
            db.session.commit()
            return jsonify({"message": "LotCrop deleted successfully"}), 200

        if lot_crop_ids:
            deleted_lot_crops = []
            for lc_id in lot_crop_ids:
                lot_crop = LotCrop.query.get(lc_id)
                if not lot_crop:
                    continue
                if not self._has_access(lot_crop, claims):
                    continue
                db.session.delete(lot_crop)
                deleted_lot_crops.append(f"LotCrop {lot_crop.id}")
            db.session.commit()
            if deleted_lot_crops:
                deleted_str = ", ".join(deleted_lot_crops)
                return (
                    jsonify(
                        {"message": f"LotCrops {deleted_str} deleted successfully"}
                    ),
                    200,
                )
            return (
                jsonify(
                    {
                        "error": "No lot-crops were deleted due to permission restrictions"
                    }
                ),
                403,
            )

    def _has_access(self, lot_crop, claims):
        """Verifica si el usuario actual tiene acceso al recurso."""
        return check_resource_access(lot_crop, claims)

    def _serialize_lot_crop(self, lot_crop):
        """Serializa un objeto LotCrop a un diccionario."""
        return {
            "id": lot_crop.id,
            "lot_id": lot_crop.lot_id,
            "lot_name": lot_crop.lot.name if lot_crop.lot else "",
            "crop_id": lot_crop.crop_id,
            "crop_name": lot_crop.crop.name if lot_crop.crop else "",
            "farm_id": lot_crop.lot.farm_id,
            "farm_name": lot_crop.lot.farm.name if lot_crop.lot.farm else "",
            "start_date": lot_crop.start_date.isoformat(),
            "end_date": lot_crop.end_date.isoformat() if lot_crop.end_date else None,
            "created_at": lot_crop.created_at.isoformat(),
            "updated_at": lot_crop.updated_at.isoformat(),
            "organization_id": (
                lot_crop.lot.farm.org_id if lot_crop.lot and lot_crop.lot.farm else None
            ),
        }


# Vista para análisis de foliar (leaf_analyses)
# 👌
class LeafAnalysisView(MethodView):
    """Clase para gestionar operaciones CRUD sobre análisis de hojas con valores de nutrientes."""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, leaf_analysis_id=None):
        """
        Obtiene una lista de análisis de hojas o un análisis de hoja específico.
        Args:
            leaf_analysis_id (int, optional): ID del análisis de hoja a consultar.
        Returns:
            JSON: Lista de análisis de hojas o detalles de un análisis de hoja específico.
        """
        filter_by = request.args.get("filter_by")
        if filter_by:
            filter_by = int(filter_by)
            return self._get_leaf_analysis_list(filter_by=filter_by)

        if leaf_analysis_id:
            return self._get_leaf_analysis(leaf_analysis_id)
        return self._get_leaf_analysis_list()

    @check_permission(required_roles=["administrator", "reseller"])
    def post(self):
        """
        Crea un nuevo análisis de hoja con valores de nutrientes.
        Expected JSON data:
            {
                "common_analysis_id": int,
                "nutrient_values": {"nutrient_<id>": float, ...} (e.g., "nutrient_1": 10.5)
            }
        Returns:
            JSON: Detalles del análisis de hoja creado.
        """
        data = request.get_json()
        required_fields = ["common_analysis_id"]
        if not data or not all(k in data for k in required_fields):
            raise BadRequest("Missing required fields: common_analysis_id.")
        return self._create_leaf_analysis(data)

    @check_permission(resource_owner_check=True)
    def put(self, id):
        """
        Actualiza un análisis de hoja existente.
        Args:
            leaf_analysis_id (int): ID del análisis de hoja a actualizar.
        Expected JSON data: Same as POST, con campos opcionales.
        Returns:
            JSON: Detalles del análisis de hoja actualizado.
        """
        data = request.get_json()
        leaf_analysis_id = id

        if not data or not leaf_analysis_id:
            raise BadRequest("Missing leaf_analysis_id or data.")
        return self._update_leaf_analysis(leaf_analysis_id, data)

    @check_permission(resource_owner_check=True)
    def delete(self, id=None):
        """
        Elimina un análisis de hoja existente.
        Args:
            leaf_analysis_id (int): ID del análisis de hoja a eliminar.
        Returns:
            JSON: Mensaje de confirmación.
        """
        leaf_analysis_id = id
        if not leaf_analysis_id:
            raise BadRequest("Missing leaf_analysis_id.")
        return self._delete_leaf_analysis(leaf_analysis_id)

    # Métodos auxiliares
    def _get_leaf_analysis_list(self, filter_by=None, page=None, per_page=None):
        """Obtiene una lista de todos los análisis de hojas según el rol del usuario y el filtro por finca.

        Args:
            filter_by (int, optional): ID de la finca para filtrar los resultados.
            page (int, optional): Número de página para la paginación.
            per_page (int, optional): Cantidad de elementos por página.
        """
        claims = get_jwt()
        user_role = claims.get("rol")
        leaf_analyses = []

        if user_role == RoleEnum.ADMINISTRATOR.value:
            query = LeafAnalysis.query.join(
                CommonAnalysis, LeafAnalysis.common_analysis_id == CommonAnalysis.id
            )
            query = query.join(Lot, CommonAnalysis.lot_id == Lot.id)
        elif user_role == RoleEnum.RESELLER.value:
            reseller_package = ResellerPackage.query.filter_by(
                reseller_id=claims.get("org_id")
            ).first()
            if not reseller_package:
                raise NotFound("Reseller package not found.")
            query = LeafAnalysis.query.join(
                CommonAnalysis, LeafAnalysis.common_analysis_id == CommonAnalysis.id
            )
            query = query.join(Lot, CommonAnalysis.lot_id == Lot.id)
            query = query.join(Farm, Lot.farm_id == Farm.id)
            query = query.join(Organization, Farm.org_id == Organization.id)
            query = query.filter(Organization.id.in_(reseller_package.organization_ids))
        else:
            raise Forbidden("Only administrators and resellers can list leaf analyses.")

        if filter_by:
            query = query.filter(Lot.farm_id == filter_by)

        query = query.options(
            joinedload(LeafAnalysis.common_analysis)
            .joinedload(CommonAnalysis.lot)
            .joinedload(Lot.farm),
            selectinload(LeafAnalysis.nutrients),
        )

        pagination = None
        if page is not None or per_page is not None:
            page = page if page is not None else 1
            per_page = per_page if per_page is not None else 10
            if page < 1:
                raise BadRequest("Page number must be 1 or greater.")
            if per_page < 1 or per_page > 100:
                raise BadRequest("Per_page must be between 1 and 100.")
            pagination = query.paginate(page=page, per_page=per_page, error_out=False)
            leaf_analyses = pagination.items
        else:
            leaf_analyses = query.all()

        leaf_analysis_ids = [la.id for la in leaf_analyses]
        values_query = db.session.query(
            leaf_analysis_nutrients.c.leaf_analysis_id,
            leaf_analysis_nutrients.c.nutrient_id,
            leaf_analysis_nutrients.c.value,
        ).filter(leaf_analysis_nutrients.c.leaf_analysis_id.in_(leaf_analysis_ids))
        values_rows = values_query.all()
        nutrient_values_map = {}
        for la_id, nutrient_id, value in values_rows:
            nutrient_values_map.setdefault(la_id, {})[nutrient_id] = value

        items = [
            self._serialize_leaf_analysis(leaf_analysis, nutrient_values_map)
            for leaf_analysis in leaf_analyses
        ]

        if pagination:
            response_data = {
                "items": items,
                "total": pagination.total,
                "pages": pagination.pages,
                "page": pagination.page,
                "per_page": pagination.per_page,
            }
        else:
            response_data = items

        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _get_leaf_analysis(self, leaf_analysis_id):
        """Obtiene los detalles de un análisis de hoja específico."""
        leaf_analysis = LeafAnalysis.query.options(
            joinedload(LeafAnalysis.common_analysis)
            .joinedload(CommonAnalysis.lot)
            .joinedload(Lot.farm),
            selectinload(LeafAnalysis.nutrients),
        ).get_or_404(leaf_analysis_id)
        claims = get_jwt()
        if not self._has_access(leaf_analysis, claims):
            raise Forbidden("You do not have access to this leaf analysis.")
        response_data = self._serialize_leaf_analysis(leaf_analysis)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _create_leaf_analysis(self, data):
        """Crea un nuevo análisis de hoja con valores de nutrientes."""
        common_analysis_id = data["common_analysis_id"]

        # Validar que common_analysis_id existe

        common_analysis = CommonAnalysis.query.get(common_analysis_id)
        if not common_analysis:
            raise BadRequest("Invalid common_analysis_id.")

        # Crear el nuevo análisis foliar
        new_leaf_analysis = LeafAnalysis(common_analysis_id=common_analysis_id)
        db.session.add(new_leaf_analysis)
        db.session.flush()  # Asegura que el ID esté disponible

        # Manejar valores de nutrientes
        nutrient_values = {k: v for k, v in data.items() if k.startswith("nutrient_")}
        for key, value in nutrient_values.items():
            if value is None or str(value).strip() == "":
                continue
            nutrient_id = int(key.split("_")[1])
            nutrient = Nutrient.query.get(nutrient_id)
            if not nutrient:
                raise BadRequest(f"Invalid nutrient ID: {nutrient_id}")
            try:
                nutrient_value = float(value)
                if nutrient_value < 0:
                    raise BadRequest(f"Value for {nutrient.name} must be non-negative.")
                insert_stmt = leaf_analysis_nutrients.insert().values(
                    leaf_analysis_id=new_leaf_analysis.id,
                    nutrient_id=nutrient_id,
                    value=nutrient_value,
                    created_at=datetime.utcnow(),
                )
                db.session.execute(insert_stmt)
            except ValueError:
                raise BadRequest(
                    f"Invalid numeric value for {nutrient.name}: '{value}'"
                )

        db.session.commit()
        response_data = self._serialize_leaf_analysis(new_leaf_analysis)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=201, mimetype="application/json")

    def _update_leaf_analysis(self, leaf_analysis_id, data):
        """Actualiza un análisis de hoja existente."""
        leaf_analysis = LeafAnalysis.query.get_or_404(leaf_analysis_id)

        # Actualizar common_analysis_id si está presente
        if "common_analysis_id" in data:

            common_analysis = CommonAnalysis.query.get(data["common_analysis_id"])
            if not common_analysis:
                raise BadRequest("Invalid common_analysis_id.")
            leaf_analysis.common_analysis_id = data["common_analysis_id"]

        # Manejar valores de nutrientes si están presentes
        nutrient_values = {k: v for k, v in data.items() if k.startswith("nutrient_")}
        if nutrient_values:
            # Eliminar valores de nutrientes existentes
            db.session.query(leaf_analysis_nutrients).filter_by(
                leaf_analysis_id=leaf_analysis.id
            ).delete()
            # Agregar nuevos valores de nutrientes
            for key, value in nutrient_values.items():
                if value is None or str(value).strip() == "":
                    continue
                nutrient_id = int(key.split("_")[1])
                nutrient = Nutrient.query.get(nutrient_id)
                if not nutrient:
                    raise BadRequest(f"Invalid nutrient ID: {nutrient_id}")
                try:
                    nutrient_value = float(value)
                    if nutrient_value < 0:
                        raise BadRequest(
                            f"Value for {nutrient.name} must be non-negative."
                        )
                    insert_stmt = leaf_analysis_nutrients.insert().values(
                        leaf_analysis_id=leaf_analysis.id,
                        nutrient_id=nutrient_id,
                        value=nutrient_value,
                        created_at=datetime.utcnow(),
                    )
                    db.session.execute(insert_stmt)
                except ValueError:
                    raise BadRequest(
                        f"Invalid numeric value for {nutrient.name}: '{value}'"
                    )

        db.session.commit()
        response_data = self._serialize_leaf_analysis(leaf_analysis)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _delete_leaf_analysis(self, leaf_analysis_id):
        """Elimina un análisis de hoja."""
        leaf_analysis = LeafAnalysis.query.get_or_404(leaf_analysis_id)
        db.session.delete(leaf_analysis)
        db.session.commit()
        return jsonify({"message": "Leaf analysis deleted successfully"}), 200

    def _has_access(self, leaf_analysis, claims):
        """Verifica si el usuario actual tiene acceso al análisis de hoja."""
        return check_resource_access(leaf_analysis, claims)

    def _serialize_leaf_analysis(self, leaf_analysis, nutrient_values_map=None):
        """Serializa un objeto LeafAnalysis a un diccionario."""
        if nutrient_values_map is not None:
            values_for_analysis = nutrient_values_map.get(leaf_analysis.id, {})
        else:
            nutrient_values = (
                db.session.query(leaf_analysis_nutrients)
                .filter_by(leaf_analysis_id=leaf_analysis.id)
                .all()
            )
            values_for_analysis = {nv.nutrient_id: nv.value for nv in nutrient_values}
        analysis_dict = {
            "id": leaf_analysis.id,
            "common_analysis_id": leaf_analysis.common_analysis_id,
            "common_analysis_date": leaf_analysis.common_analysis.date.isoformat(),
            "common_analysis_display": f"{leaf_analysis.common_analysis.lot.farm.name}, {leaf_analysis.common_analysis.lot.name}, {leaf_analysis.common_analysis.date.isoformat()}",
            "farm_name": leaf_analysis.common_analysis.farm_name,
            "lot_name": leaf_analysis.common_analysis.lot_name,
            "created_at": leaf_analysis.created_at.isoformat(),
            "updated_at": leaf_analysis.updated_at.isoformat(),
            "nutrients_info": {
                str(n.id): {"name": n.name, "symbol": n.symbol, "unit": n.unit}
                for n in leaf_analysis.nutrients
            },
        }
        for nutrient in leaf_analysis.nutrients:
            analysis_dict[f"nutrient_{nutrient.id}"] = values_for_analysis.get(
                nutrient.id
            )
        return analysis_dict


# 👌
class SoilAnalysisView(MethodView):
    """Class to manage CRUD operations for soil analyses"""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, soil_analysis_id=None):
        """
        Retrieve a list of soil analyses or a specific soil analysis
        Args:
            soil_analysis_id (int, optional): ID of the soil analysis to retrieve
        Returns:
            JSON: List of soil analyses or details of a specific soil analysis
        """

        if soil_analysis_id:
            return self._get_soil_analysis(soil_analysis_id)
        filter_value = request.args.get("filter_value")
        if filter_value:
            filter_value = int(filter_value)
            return self._get_soil_analysis_list(filter_by=filter_value)
        else:
            return self._get_soil_analysis_list()

    @check_permission(required_roles=["administrator", "reseller"])
    def post(self):
        """
        Create a new soil analysis
        Returns:
            JSON: Details of the created soil analysis
        """
        data = request.get_json()
        required_fields = ["common_analysis_id", "energy", "grazing"]
        if not data or not all(k in data for k in required_fields):
            raise BadRequest("Missing required fields")
        return self._create_soil_analysis(data)

    @check_permission(resource_owner_check=True)
    def put(self, id: int):
        """
        Update an existing soil analysis
        Args:
            soil_analysis_id (int): ID of the soil analysis to update
        Returns:
            JSON: Details of the updated soil analysis
        """
        data = request.get_json()
        soil_analysis_id = id
        if not data or not soil_analysis_id:
            raise BadRequest("Missing soil_analysis_id or data")
        return self._update_soil_analysis(soil_analysis_id, data)

    @check_permission(resource_owner_check=True)
    def delete(self, id=None):
        """
        Delete an existing soil analysis
        Args:
            soil_analysis_id (int): ID of the soil analysis to delete
        Returns:
            JSON: Confirmation message
        """
        soil_analysis_id = id
        if not soil_analysis_id:
            raise BadRequest("Missing soil_analysis_id")
        return self._delete_soil_analysis(soil_analysis_id)

    # Helper Methods
    def _get_soil_analysis_list(self, filter_by=None):
        """Retrieve a list of all soil analyses"""
        claims = get_jwt()
        user_role = claims.get("rol")
        soil_analyses = []

        if user_role == RoleEnum.ADMINISTRATOR.value:
            query = SoilAnalysis.query.join(
                CommonAnalysis, SoilAnalysis.common_analysis_id == CommonAnalysis.id
            )
            query = query.join(Lot, CommonAnalysis.lot_id == Lot.id)
        elif user_role == RoleEnum.RESELLER.value:
            reseller_package = ResellerPackage.query.filter_by(
                reseller_id=claims.get("org_id")
            ).first()
            if not reseller_package:
                raise NotFound("Reseller package not found.")
            query = SoilAnalysis.query.join(
                CommonAnalysis, SoilAnalysis.common_analysis_id == CommonAnalysis.id
            )
            query = query.join(Lot, CommonAnalysis.lot_id == Lot.id)
            query = query.join(Farm, Lot.farm_id == Farm.id)
            query = query.join(Organization, Farm.org_id == Organization.id)
            query = query.filter(Organization.id.in_(reseller_package.organization_ids))
        else:
            raise Forbidden("Only administrators and resellers can list soil analyses")

        if filter_by:
            query = query.filter(Lot.farm_id == filter_by)

        soil_analyses = query.all()
        response_data = [self._serialize_soil_analysis(sa) for sa in soil_analyses]
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _get_soil_analysis(self, soil_analysis_id):
        """Retrieve details of a specific soil analysis"""
        soil_analysis = SoilAnalysis.query.get_or_404(soil_analysis_id)
        claims = get_jwt()
        if not self._has_access(soil_analysis, claims):
            raise Forbidden("You do not have access to this soil analysis")
        response_data = self._serialize_soil_analysis(soil_analysis)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _create_soil_analysis(self, data):
        """Create a new soil analysis"""
        common_analysis_id = data["common_analysis_id"]
        energy = data["energy"]
        grazing = data["grazing"]
        soil_analysis = SoilAnalysis(
            common_analysis_id=common_analysis_id, energy=energy, grazing=grazing
        )
        db.session.add(soil_analysis)
        db.session.commit()
        response_data = self._serialize_soil_analysis(soil_analysis)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=201, mimetype="application/json")

    def _update_soil_analysis(self, soil_analysis_id, data):
        """Update an existing soil analysis"""
        soil_analysis = SoilAnalysis.query.get_or_404(soil_analysis_id)
        if "energy" in data:
            soil_analysis.energy = data["energy"]
        if "grazing" in data:
            soil_analysis.grazing = data["grazing"]
        db.session.commit()
        response_data = self._serialize_soil_analysis(soil_analysis)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _delete_soil_analysis(self, soil_analysis_id):
        """Delete an existing soil analysis"""
        soil_analysis = SoilAnalysis.query.get_or_404(soil_analysis_id)
        db.session.delete(soil_analysis)
        db.session.commit()
        return jsonify({"message": "Soil analysis deleted successfully"}), 200

    def _has_access(self, soil_analysis, claims):
        """Check if the current user has access to the soil analysis"""
        return check_resource_access(soil_analysis, claims)

    def _serialize_soil_analysis(self, soil_analysis):
        """Serialize a SoilAnalysis object to a dictionary"""
        return {
            "id": soil_analysis.id,
            "common_analysis_id": soil_analysis.common_analysis_id,
            "energy": soil_analysis.energy,
            "grazing": soil_analysis.grazing,
            "created_at": soil_analysis.created_at.isoformat(),
            "updated_at": soil_analysis.updated_at.isoformat(),
        }


# Vista para aplicaciones de nutrientes (nutrient_applications)
class NutrientApplicationView(MethodView):
    """Class to manage CRUD operations for nutrient applications"""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, nutrient_application_id=None):
        """
        Obtiene una lista de aplicaciones de nutrientes o una aplicación de nutriente específico.
        Args:
            nutrient_application_id (str, optional): ID de la aplicación de nutriente a consultar.
        Returns:
            JSON: Lista de aplicaciones de nutrientes o detalles de una aplicación de nutriente específico.
        """
        if nutrient_application_id:
            return self._get_nutrient_application(nutrient_application_id)
        filter_by = request.args.get("filter_by", None)
        if filter_by:
            filter_by = int(filter_by)
        return self._get_nutrient_application_list(filter_by=filter_by)

    @check_permission(required_roles=["administrator", "reseller"])
    def post(self):
        """
        Create a new nutrient application with nutrient quantities.
        Expected JSON data:
            {
                "lot_id": int,
                "date": str (YYYY-MM-DD),
                "nutrient_quantities": {"nutrient_<id>": float, ...} (e.g., "nutrient_1": 10.5)
            }
        Returns:
            JSON: Details of the created nutrient application.
        """
        data = request.get_json()
        required_fields = ["lot_id", "date"]
        if not data or not all(k in data for k in required_fields):
            raise BadRequest("Missing required fields: lot_id and date.")
        return self._create_nutrient_application(data)

    @check_permission(resource_owner_check=True)
    def put(self, id: int):
        """
        Update an existing nutrient application.
        Args:
            nutrient_application_id (int): ID of the nutrient application to update.
        Expected JSON data: Same as POST, with optional fields.
        Returns:
            JSON: Details of the updated nutrient application.
        """
        data = request.get_json()
        nutrient_application_id = id
        if not data or not nutrient_application_id:
            raise BadRequest("Missing nutrient_application_id or data.")
        return self._update_nutrient_application(nutrient_application_id, data)

    @check_permission(resource_owner_check=True)
    def delete(self, id=None):
        """
        Delete an existing nutrient application.
        Args:
            nutrient_application_id (int): ID of the nutrient application to delete.
        Returns:
            JSON: Confirmation message.
        """
        nutrient_application_id = id
        if not nutrient_application_id:
            raise BadRequest("Missing nutrient_application_id.")
        return self._delete_nutrient_application(nutrient_application_id)

    # Helper Methods
    def _get_nutrient_application_list(self, filter_by=None):
        """
        Retrieve a list of all nutrient applications based on user role
        Args:
            filter_by (int): Filtro por ID de finca.
        Returns:
            Response: Lista de nutrient applications en formato JSON.
        """
        claims = get_jwt()
        user_role = claims.get("rol")
        nutrient_applications = []  # Lista de nutrient applications que se devolverá

        if user_role == RoleEnum.ADMINISTRATOR.value:
            query = NutrientApplication.query.join(
                Lot, NutrientApplication.lot_id == Lot.id
            ).join(Farm, Lot.farm_id == Farm.id)
        elif user_role == RoleEnum.RESELLER.value:
            reseller_package = ResellerPackage.query.filter_by(
                reseller_id=claims.get("org_id")
            ).first()
            if not reseller_package:
                raise NotFound("Reseller package not found.")
            query = (
                NutrientApplication.query.join(
                    Lot, NutrientApplication.lot_id == Lot.id
                )
                .join(Farm, Lot.farm_id == Farm.id)
                .join(Organization, Farm.org_id == Organization.id)
                .filter(Organization.id.in_(reseller_package.organization_ids))
            )
        else:
            raise Forbidden(
                "Only administrators and resellers can list nutrient applications."
            )

        if filter_by:
            query = query.filter(Lot.farm_id == filter_by)

        nutrient_applications = query.all()
        response_data = [
            self._serialize_nutrient_application(nutrient_application)
            for nutrient_application in nutrient_applications
        ]
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _get_nutrient_application(self, nutrient_application_id):
        """Retrieve details of a specific nutrient application"""
        nutrient_application = NutrientApplication.query.get_or_404(
            nutrient_application_id
        )
        claims = get_jwt()
        if not self._has_access(nutrient_application, claims):
            raise Forbidden("You do not have access to this nutrient application.")
        response_data = self._serialize_nutrient_application(nutrient_application)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _create_nutrient_application(self, data):
        """Create a new nutrient application with nutrient quantities"""
        lot_id = data["lot_id"]
        date = datetime.strptime(data["date"], "%Y-%m-%d")
        # Validate lot exists
        lot = Lot.query.get(lot_id)
        if not lot:
            raise BadRequest("Invalid lot ID.")
        new_nutrient_application = NutrientApplication(date=date, lot_id=lot_id)
        db.session.add(new_nutrient_application)
        db.session.flush()  # Ensure new_nutrient_application.id is available
        # Handle nutrient quantities
        nutrient_quantities = {
            k: v for k, v in data.items() if k.startswith("nutrient_")
        }
        for key, value in nutrient_quantities.items():
            nutrient_id = int(key.split("_")[1])
            nutrient = Nutrient.query.get(nutrient_id)
            if not nutrient:
                raise BadRequest(f"Invalid nutrient ID: {nutrient_id}")
            try:
                quantity_float = float(value)  # Convert to float
                if quantity_float <= 0:
                    raise BadRequest(f"Quantity for {nutrient.name} must be positive.")
                insert_stmt = nutrient_application_nutrients.insert().values(
                    nutrient_application_id=new_nutrient_application.id,
                    nutrient_id=nutrient_id,
                    quantity=quantity_float,
                )
                db.session.execute(insert_stmt)
            except ValueError:
                raise BadRequest(
                    f"Quantity for {nutrient.name} must be a valid number."
                )
        db.session.commit()
        response_data = self._serialize_nutrient_application(new_nutrient_application)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=201, mimetype="application/json")

    def _update_nutrient_application(self, nutrient_application_id, data):
        """Update an existing nutrient application"""
        nutrient_application = NutrientApplication.query.get_or_404(
            nutrient_application_id
        )
        # Update main fields if provided
        if "lot_id" in data:
            lot = Lot.query.get(data["lot_id"])
            if not lot:
                raise BadRequest("Invalid lot ID.")
            nutrient_application.lot_id = data["lot_id"]
        if "date" in data:
            nutrient_application.date = datetime.strptime(data["date"], "%Y-%m-%d")
        # Handle nutrient quantities if provided
        nutrient_quantities = {
            k: v for k, v in data.items() if k.startswith("nutrient_")
        }
        if nutrient_quantities:
            # Delete existing nutrient quantities
            db.session.query(nutrient_application_nutrients).filter_by(
                nutrient_application_id=nutrient_application.id
            ).delete()
            # Add new nutrient quantities
            for key, value in nutrient_quantities.items():
                nutrient_id = int(key.split("_")[1])
                nutrient = Nutrient.query.get(nutrient_id)
                if not nutrient:
                    raise BadRequest(f"Invalid nutrient ID: {nutrient_id}")
                # Convert value to float (or int) and validate
                try:
                    quantity_float = float(
                        value
                    )  # Use float to handle decimal values; use int if only integers are expected
                    if quantity_float <= 0:
                        raise BadRequest(
                            f"Quantity for {nutrient.name} must be positive."
                        )
                    insert_stmt = nutrient_application_nutrients.insert().values(
                        nutrient_application_id=nutrient_application.id,
                        nutrient_id=nutrient_id,
                        quantity=quantity_float,
                    )
                    db.session.execute(insert_stmt)
                except ValueError:
                    raise BadRequest(
                        f"Quantity for {nutrient.name} must be a valid number."
                    )
        db.session.commit()
        response_data = self._serialize_nutrient_application(nutrient_application)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _delete_nutrient_application(self, nutrient_application_id):
        """Delete an existing nutrient application"""
        nutrient_application = NutrientApplication.query.get_or_404(
            nutrient_application_id
        )
        db.session.delete(nutrient_application)
        db.session.commit()
        return jsonify({"message": "Nutrient application deleted successfully"}), 200

    def _has_access(self, nutrient_application, claims):
        """Check if the current user has access to the nutrient application"""
        return check_resource_access(nutrient_application, claims)

    def _serialize_nutrient_application(self, nutrient_application):
        """Serialize a NutrientApplication object to a dictionary"""
        nutrient_quantities = (
            db.session.query(nutrient_application_nutrients)
            .filter_by(nutrient_application_id=nutrient_application.id)
            .all()
        )
        nutrient_quantities_dict = [
            {
                "nutrient_id": quantity.nutrient_id,
                "quantity": quantity.quantity,
                "nutrient_name": Nutrient.query.get(quantity.nutrient_id).name,
                "nutrient_symbol": Nutrient.query.get(quantity.nutrient_id).symbol,
                "nutrient_unit": Nutrient.query.get(quantity.nutrient_id).unit,
            }
            for quantity in nutrient_quantities
        ]
        return {
            "id": nutrient_application.id,
            "lot_id": nutrient_application.lot_id,
            "lot_name": nutrient_application.lot.name,
            "farm_name": nutrient_application.lot.farm.name,
            "organization_name": nutrient_application.lot.farm.organization.name,
            "date": nutrient_application.date.isoformat(),
            "created_at": nutrient_application.created_at.isoformat(),
            "updated_at": nutrient_application.updated_at.isoformat(),
            "nutrient_quantities": nutrient_quantities_dict,
        }


class ProductionView(MethodView):
    """Class to manage CRUD operations for productions"""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def get(self, production_id=None):
        """
        Retrieve a list of productions or a specific production
        Args:
            production_id (int, optional): ID of the production to retrieve
        Returns:
            JSON: List of productions or details of a specific production
        """
        if production_id:
            return self._get_production(production_id)
        return self._get_production_list()

    @check_permission(required_roles=["administrator", "reseller"])
    def post(self):
        """
        Create a new production
        Returns:
            JSON: Details of the created production
        """
        data = request.get_json()
        required_fields = [
            "lot_id",
            "date",
            "area",
            "production_kg",
            "bags",
            "harvest",
            "month",
            "variety",
            "price_per_kg",
            "protein_65dde",
            "discount",
        ]
        if not data or not all(k in data for k in required_fields):
            raise BadRequest("Missing required fields")
        return self._create_production(data)

    @check_permission(resource_owner_check=True)
    def put(self, id: int):
        """
        Update an existing production
        Args:
            production_id (int): ID of the production to update
        Returns:
            JSON: Details of the updated production
        """
        data = request.get_json()
        production_id = id
        if not data or not production_id:
            raise BadRequest("Missing production_id or data")
        return self._update_production(production_id, data)

    @check_permission(resource_owner_check=True)
    def delete(self, id=None):
        """
        Delete an existing production
        Args:
            production_id (int): ID of the production to delete
        Returns:
            JSON: Confirmation message
        """
        production_id = id
        if not production_id:
            raise BadRequest("Missing production_id")
        return self._delete_production(production_id)

    # Helper Methods
    def _get_production_list(self):
        """Retrieve a list of all productions"""
        claims = get_jwt()
        user_role = claims.get("rol")
        if user_role == RoleEnum.ADMINISTRATOR.value:
            productions = Production.query.all()
        elif user_role == RoleEnum.RESELLER.value:
            reseller_package = ResellerPackage.query.filter_by(
                reseller_id=claims.get("org_id")
            ).first()
            if not reseller_package:
                raise NotFound("Reseller package not found.")
            productions = []
            for organization in reseller_package.organizations:
                for lot in organization.lots:
                    productions.extend(lot.productions)
        else:
            raise Forbidden("Only administrators and resellers can list productions")
        response_data = [self._serialize_production(p) for p in productions]
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _get_production(self, production_id):
        """Retrieve details of a specific production"""
        production = Production.query.get_or_404(production_id)
        claims = get_jwt()
        if not self._has_access(production, claims):
            raise Forbidden("You do not have access to this production")
        response_data = self._serialize_production(production)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _create_production(self, data):
        """Create a new production"""
        production = Production(
            lot_id=data["lot_id"],
            date=data["date"],
            area=data["area"],
            production_kg=data["production_kg"],
            bags=data["bags"],
            harvest=data["harvest"],
            month=data["month"],
            variety=data["variety"],
            price_per_kg=data["price_per_kg"],
            protein_65dde=data["protein_65dde"],
            discount=data["discount"],
        )
        db.session.add(production)
        db.session.commit()
        response_data = self._serialize_production(production)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=201, mimetype="application/json")

    def _update_production(self, production_id, data):
        """Update an existing production"""
        production = Production.query.get_or_404(production_id)
        if "date" in data:
            production.date = data["date"]
        if "area" in data:
            production.area = data["area"]
        if "production_kg" in data:
            production.production_kg = data["production_kg"]
        if "bags" in data:
            production.bags = data["bags"]
        if "harvest" in data:
            production.harvest = data["harvest"]
        if "month" in data:
            production.month = data["month"]
        if "variety" in data:
            production.variety = data["variety"]
        if "price_per_kg" in data:
            production.price_per_kg = data["price_per_kg"]
        if "protein_65dde" in data:
            production.protein_65dde = data["protein_65dde"]
        if "discount" in data:
            production.discount = data["discount"]
        db.session.commit()
        response_data = self._serialize_production(production)
        json_data = json.dumps(response_data, ensure_ascii=False, indent=4)
        return Response(json_data, status=200, mimetype="application/json")

    def _delete_production(self, production_id):
        """Delete an existing production"""
        production = Production.query.get_or_404(production_id)
        db.session.delete(production)
        db.session.commit()
        return jsonify({"message": "Production deleted successfully"}), 200

    def _has_access(self, production, claims):
        """Check if the current user has access to the production"""
        return check_resource_access(production, claims)

    def _serialize_production(self, production):
        """Serialize a Production object to a dictionary"""
        return {
            "id": production.id,
            "lot_id": production.lot_id,
            "farm_name": production.lot.farm.name,
            "organization_name": production.lot.farm.organization.name,
            "lot_name": production.lot.name,
            "date": production.date.isoformat(),
            "area": production.area,
            "production_kg": production.production_kg,
            "bags": production.bags,
            "harvest": production.harvest,
            "month": production.month,
            "variety": production.variety,
            "price_per_kg": production.price_per_kg,
            "protein_65dde": production.protein_65dde,
            "discount": production.discount,
            "created_at": production.created_at.isoformat(),
            "updated_at": production.updated_at.isoformat(),
        }
