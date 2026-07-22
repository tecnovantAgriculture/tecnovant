from __future__ import annotations

from flask import current_app, jsonify, request

from app.extensions import db
from app.modules.foliage.models import Farm, Lot
from app.modules.media.controller import MediaController

from . import orthophotos_api as api
from .models import OrthophotoMission, OrthophotoPhoto


@api.route("/missions/photos", methods=["POST"])
def upload_photos():
    mission_id = request.form.get("mission_id", type=int)
    mission_name = (request.form.get("mission_name") or "").strip()
    upload_session_id = (request.form.get("upload_session_id") or "").strip()
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
