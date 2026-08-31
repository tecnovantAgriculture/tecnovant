from __future__ import annotations

from datetime import date

from flask import current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.extensions import db
from app.core.controller import login_required
from app.core.models import Organization, ResellerPackage, User, get_clients_for_user
from app.modules.foliage.models import Farm, Lot
from app.modules.media.controller import MediaController

from . import orthophotos_api as api
from .models import OrthophotoMission, OrthophotoPhoto


@api.route("/locations", methods=["POST"])
@login_required
def create_location_path():
    data = request.get_json(silent=True) or {}
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify({"success": False, "message": "Usuario no válido."}), 403

    organization_id = data.get("organization_id")
    organization_name = str(data.get("organization_name") or "").strip()
    farm_id = data.get("farm_id")
    farm_name = str(data.get("farm_name") or "").strip()
    lot_id = data.get("lot_id")
    lot_name = str(data.get("lot_name") or "").strip()
    lot_area = data.get("lot_area")
    accessible_ids = {organization.id for organization in get_clients_for_user(user_id)}

    try:
        organization = Organization.query.get(int(organization_id)) if organization_id else None
        if organization is None and organization_name:
            if not (user.is_admin() or user.is_reseller()):
                return jsonify({"success": False, "message": "Tu rol no permite crear clientes."}), 403
            organization = Organization.query.filter(
                db.func.lower(Organization.name) == organization_name.lower(),
                Organization.active.is_(True),
            ).first()
            if organization and organization.id not in accessible_ids and not user.is_admin():
                return jsonify({"success": False, "message": "Ya existe un cliente con ese nombre fuera de tu acceso."}), 409
            if organization is None:
                organization = Organization(name=organization_name, description="Creado desde Fotogrametría")
                if user.is_reseller():
                    package = ResellerPackage.query.filter_by(reseller_id=user_id).first()
                    if not package or not package.add_client():
                        return jsonify({"success": False, "message": "No hay cupo disponible para crear otro cliente."}), 409
                    organization.reseller_id = package.id
                    package.current_clients += 1
                db.session.add(organization)
                db.session.flush()
            accessible_ids.add(organization.id)
        if not organization or (organization.id not in accessible_ids and not user.is_admin()):
            return jsonify({"success": False, "message": "Selecciona un cliente autorizado."}), 403

        farm = Farm.query.get(int(farm_id)) if farm_id else None
        if farm is None and farm_name:
            farm = Farm.query.filter(
                Farm.org_id == organization.id,
                db.func.lower(Farm.name) == farm_name.lower(),
            ).first()
            if farm is None:
                farm = Farm(name=farm_name, org_id=organization.id)
                db.session.add(farm)
                db.session.flush()
        if not farm or farm.org_id != organization.id:
            return jsonify({"success": False, "message": "Selecciona o escribe una finca válida."}), 400

        lot = Lot.query.get(int(lot_id)) if lot_id else None
        if lot is None and lot_name:
            try:
                area = float(lot_area)
            except (TypeError, ValueError):
                return jsonify({"success": False, "message": "Escribe el área del lote en hectáreas."}), 400
            if area <= 0:
                return jsonify({"success": False, "message": "El área del lote debe ser mayor que cero."}), 400
            lot = Lot.query.filter(
                Lot.farm_id == farm.id,
                db.func.lower(Lot.name) == lot_name.lower(),
                Lot.active.is_(True),
            ).first()
            if lot is None:
                lot = Lot(name=lot_name, area=area, farm_id=farm.id)
                db.session.add(lot)
                db.session.flush()
        if not lot or lot.farm_id != farm.id:
            return jsonify({"success": False, "message": "Selecciona o escribe un lote válido."}), 400

        db.session.commit()
        return jsonify({"success": True, "organization": {"id": organization.id, "name": organization.name}, "farm": {"id": farm.id, "name": farm.name}, "lot": {"id": lot.id, "name": lot.name, "area": lot.area}})
    except Exception:
        db.session.rollback()
        current_app.logger.exception("orthophotos: no se pudo crear la ruta de ubicación")
        return jsonify({"success": False, "message": "No se pudo crear la estructura de cliente, finca y lote."}), 500


@api.route("/missions/photos", methods=["POST"])
def upload_photos():
    mission_id = request.form.get("mission_id", type=int)
    mission_name = (request.form.get("mission_name") or "").strip()
    upload_session_id = (request.form.get("upload_session_id") or "").strip()
    foliar_date_raw = (request.form.get("foliar_date") or "").strip()
    orthophoto_date_raw = (request.form.get("orthophoto_date") or "").strip()
    try:
        foliar_date = date.fromisoformat(foliar_date_raw) if foliar_date_raw else None
        orthophoto_date = date.fromisoformat(orthophoto_date_raw) if orthophoto_date_raw else None
    except ValueError:
        return jsonify({"success": False, "message": "Las fechas foliar y de ortofoto no son válidas."}), 400
    organization_id = request.form.get("organization_id", type=int)
    farm_id = request.form.get("farm_id", type=int)
    lot_id = request.form.get("lot_id", type=int)
    has_location = any((organization_id, farm_id, lot_id))
    farm = Farm.query.get(farm_id) if farm_id else None
    lot = Lot.query.get(lot_id) if lot_id else None
    if has_location and (
        not organization_id
        or not farm
        or farm.org_id != organization_id
        or not lot
        or lot.farm_id != farm.id
    ):
        return jsonify({"success": False, "message": "La ruta cliente, finca y lote no es valida."}), 400
    mission = OrthophotoMission.query.get(mission_id) if mission_id else None
    if mission is None:
        if upload_session_id:
            mission = OrthophotoMission.query.filter_by(
                upload_token=upload_session_id
            ).first()

    if mission is None and not mission_name:
        mission = (
            OrthophotoMission.query.filter_by(
                name="Carga de piloto",
                description="Mision creada desde el portal publico de pilotos.",
                status="receiving",
            )
            .order_by(OrthophotoMission.created_at.desc())
            .first()
        )

    if mission is None:
        mission = OrthophotoMission(
            name=mission_name or "Carga de piloto",
            description="Mision creada desde el portal publico de pilotos.",
            organization_id=organization_id if has_location else None,
            farm_id=farm.id if has_location else None,
            lot_id=lot.id if has_location else None,
            foliar_date=foliar_date,
            orthophoto_date=orthophoto_date,
        )
        if upload_session_id:
            mission.upload_token = upload_session_id
        db.session.add(mission)
        db.session.commit()

    files = request.files.getlist("files")
    if not files:
        return jsonify({"success": False, "message": "No se recibieron fotos."}), 400

    ctrl = MediaController()
    uploaded = []
    errors = []

    for file in files:
        if not file or not getattr(file, "filename", None):
            continue
        try:
            asset, _created = ctrl.save_local_upload(file)
            photo = OrthophotoPhoto(
                mission_id=mission.id,
                asset_id=asset.id,
                original_name=file.filename or asset.original_name,
            )
            db.session.add(photo)
            db.session.commit()
            uploaded.append(
                {
                    "asset_id": asset.id,
                    "name": asset.original_name,
                    "size_bytes": asset.size_bytes,
                }
            )
        except ValueError as exc:
            db.session.rollback()
            errors.append({"name": file.filename, "message": str(exc)})
        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception("orthophotos: failed to upload %s", file.filename)
            errors.append({"name": file.filename, "message": str(exc) or "No se pudo subir."})

    mission.status = "receiving"
    db.session.add(mission)
    db.session.commit()

    return jsonify(
        {
            "success": len(errors) == 0,
            "uploaded": uploaded,
            "errors": errors,
            "photo_count": len(mission.photos),
            "mission": {
                "id": mission.id,
                "name": mission.name,
                "organization_id": mission.organization_id,
                "farm_id": mission.farm_id,
                "lot_id": mission.lot_id,
                "folder_path": mission.folder_path,
            },
        }
    ), 200 if uploaded else 400
