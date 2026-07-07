from __future__ import annotations

import os
import secrets
import threading
import time
from datetime import datetime

from flask import (
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
)
from urllib.parse import urljoin

from app.core.controller import login_required
from app.extensions import db
from app.helpers.dashboard_helpers import get_dashboard_menu
from app.modules.media.controller import MediaController
from app.modules.media.helpers import _media_root

from . import orthophotos as web
from .gcp_compute_client import GCPComputeClient, env_flag
from .models import OrthophotoMission, OrthophotoPhoto
from .webodm_client import WebODMClient


STATUS_NAMES = {
    10: "queued",
    20: "running",
    30: "failed",
    40: "completed",
    50: "canceled",
}

DOWNLOADABLE_ASSETS = {
    "orthophoto": ("orthophoto.tif", "ortofoto.tif"),
    "all": ("all.zip", "ortofoto_webodm.zip"),
    "report": ("report.pdf", "reporte_webodm.pdf"),
}

PROCESSING_PROFILES = {
    "fast_2d": "2D rapido nitido",
    "balanced_2d": "2D alta calidad",
    "max_2d": "2D maxima calidad",
}

ACTIVE_STATUSES = {
    "starting_webodm",
    "submitting",
    "uploading_to_webodm",
    "queued",
    "running",
    "downloading_asset",
}
PRE_WEBODM_TASK_STATUSES = {"starting_webodm", "submitting", "uploading_to_webodm"}
TERMINAL_STATUSES = {"completed", "failed", "canceled"}
_AUTOSTOP_LOCK = threading.Lock()


def _processable_photos(mission: OrthophotoMission):
    allowed_ext = {"jpg", "jpeg", "tif", "tiff"}
    return [
        photo
        for photo in mission.photos
        if getattr(getattr(photo, "asset", None), "ext", "").lower() in allowed_ext
    ]


def _autostart_webodm_if_enabled(mission: OrthophotoMission) -> None:
    if not env_flag("WEBODM_AUTOSTART", False):
        return

    mission.status = "starting_webodm"
    mission.processing_error = None
    db.session.add(mission)
    db.session.commit()

    compute = GCPComputeClient()
    current_app.logger.info("orthophotos: starting WebODM VM for mission %s", mission.id)
    compute.start_instance()
    WebODMClient().wait_until_ready()
    mission.status = "uploading_to_webodm"
    db.session.add(mission)
    db.session.commit()
    current_app.logger.info("orthophotos: WebODM is ready for mission %s", mission.id)


def _ensure_webodm_ready_for_download() -> None:
    if not env_flag("WEBODM_AUTOSTART", False):
        return

    current_app.logger.info("orthophotos: ensuring WebODM VM is ready for download")
    GCPComputeClient().start_instance()
    WebODMClient().wait_until_ready()


def _fail_pre_webodm_missions_if_vm_is_down(vm_status: str) -> None:
    if vm_status not in {"TERMINATED", "STOPPED"}:
        return

    stale_seconds = int(os.getenv("WEBODM_READY_TIMEOUT_SECONDS", "60"))
    now = datetime.utcnow()
    missions = (
        OrthophotoMission.query.filter(
            OrthophotoMission.status.in_(PRE_WEBODM_TASK_STATUSES),
            OrthophotoMission.webodm_task_id.is_(None),
        )
        .all()
    )
    if not missions:
        return

    message = (
        "El servicio de procesamiento no estuvo disponible a tiempo. "
        "Intenta procesar nuevamente."
    )
    for mission in missions:
        age_seconds = (now - mission.updated_at).total_seconds()
        if age_seconds < stale_seconds:
            continue
        mission.status = "failed"
        mission.processing_error = message
        mission.updated_at = now
        db.session.add(mission)
    db.session.commit()


def _active_missions_count() -> int:
    return OrthophotoMission.query.filter(
        OrthophotoMission.status.in_(ACTIVE_STATUSES)
    ).count()


def _autostop_webodm_if_idle(app) -> None:
    if not env_flag("WEBODM_AUTOSTOP", False):
        return

    with app.app_context():
        if _active_missions_count() > 0:
            return
        try:
            GCPComputeClient().stop_instance()
            app.logger.info("orthophotos: WebODM VM stopped after processing")
        except Exception:
            app.logger.exception("orthophotos: no se pudo apagar la VM WebODM")


def _schedule_autostop_webodm_if_idle(app) -> bool:
    if not env_flag("WEBODM_AUTOSTOP", False):
        return False
    if _active_missions_count() > 0:
        return False
    if not _AUTOSTOP_LOCK.acquire(blocking=False):
        return True

    def stop_worker() -> None:
        try:
            _autostop_webodm_if_idle(app)
        finally:
            _AUTOSTOP_LOCK.release()

    threading.Thread(
        target=stop_worker,
        daemon=True,
        name="orthophoto-webodm-idle-stop",
    ).start()
    return True


def _monitor_mission_until_done(app, mission_id: int) -> None:
    poll_seconds = int(os.getenv("WEBODM_STATUS_POLL_SECONDS", "60"))
    with app.app_context():
        while True:
            mission = OrthophotoMission.query.get(mission_id)
            if not mission:
                return
            if mission.status in TERMINAL_STATUSES:
                break
            if not mission.webodm_project_id or not mission.webodm_task_id:
                return
            _refresh_processing_status(mission)
            db.session.remove()
            time.sleep(poll_seconds)

    _autostop_webodm_if_idle(app)


def _submit_mission_to_webodm(app, mission_id: int, profile: str = "max_2d") -> None:
    with app.app_context():
        mission = OrthophotoMission.query.get(mission_id)
        if not mission:
            return

        try:
            _autostart_webodm_if_enabled(mission)
            webodm = WebODMClient()
            if mission.webodm_project_id and mission.webodm_task_id:
                app.logger.info(
                    "orthophotos: restarting existing WebODM task %s for mission %s",
                    mission.webodm_task_id,
                    mission.id,
                )
                task = webodm.restart_task(
                    mission.webodm_project_id,
                    mission.webodm_task_id,
                    options=webodm.orthophoto_options(profile),
                )
                mission.status = STATUS_NAMES.get(task.get("status"), "queued")
                mission.processing_job_id = str(task.get("id") or mission.webodm_task_id)
                mission.progress = task.get("running_progress")
                mission.available_assets = task.get("available_assets")
                mission.processing_error = None
                db.session.add(mission)
                db.session.commit()

                if env_flag("WEBODM_AUTOSTOP", False):
                    _monitor_mission_until_done(app, mission.id)
                return

            media_root = _media_root()
            opened_files = []

            try:
                for photo in _processable_photos(mission):
                    asset = getattr(photo, "asset", None)
                    if asset is None:
                        continue
                    path = os.path.join(media_root, asset.storage_key)
                    if not os.path.isfile(path):
                        raise FileNotFoundError(
                            f"No existe el archivo {asset.original_name}"
                        )
                    opened_files.append(
                        (
                            "images",
                            (
                                asset.original_name,
                                open(path, "rb"),
                                asset.mime or "image/jpeg",
                            ),
                        )
                    )

                project = webodm.get_or_create_project()
                nodes = webodm.processing_nodes()
                node_id = nodes[0].get("id") if nodes else None
                task = webodm.create_task(
                    project_id=project["id"],
                    name=mission.name,
                    images=[
                        (file_tuple[0], file_tuple[1], file_tuple[2])
                        for _, file_tuple in opened_files
                    ],
                    processing_node_id=node_id,
                    options=webodm.orthophoto_options(profile),
                )

                mission.status = STATUS_NAMES.get(task.get("status"), "queued")
                mission.webodm_project_id = project["id"]
                mission.webodm_task_id = str(task["id"])
                mission.processing_job_id = str(task["id"])
                mission.progress = task.get("running_progress")
                mission.available_assets = task.get("available_assets")
                mission.processing_error = None
                db.session.add(mission)
                db.session.commit()

                if env_flag("WEBODM_AUTOSTOP", False):
                    _monitor_mission_until_done(app, mission.id)
            finally:
                for _, file_tuple in opened_files:
                    try:
                        file_tuple[1].close()
                    except Exception:
                        pass
        except Exception as exc:
            db.session.rollback()
            mission = OrthophotoMission.query.get(mission_id)
            if mission:
                mission.status = "failed"
                mission.processing_error = str(exc)
                db.session.add(mission)
                db.session.commit()
            app.logger.exception("orthophotos: WebODM submission failed")
            _autostop_webodm_if_idle(app)


def _context(**extra):
    context = {
        "title": "Ortofotos",
        "description": "Gestiona misiones y cargas de imagenes para ortofotos.",
        "author": "TecnoAgro",
        "site_title": "Ortofotos",
        "page_title": "Ortofotos",
        "page_logo": "/img/iamgentec.png",
    }
    context.update(extra)
    return context


def _public_url_for(endpoint: str, **values) -> str:
    path = url_for(endpoint, **values)
    public_base = os.getenv("TECNOAGRO_PUBLIC_URL", "").strip()
    if not public_base:
        return url_for(endpoint, _external=True, **values)
    return urljoin(public_base.rstrip("/") + "/", path.lstrip("/"))


def _webodm_vm_status_payload() -> dict[str, str]:
    if not env_flag("WEBODM_AUTOSTART", False):
        return {
            "status": "manual",
            "label": "Control manual",
            "color": "gray",
            "message": "El procesamiento automatico no esta activo.",
        }

    try:
        status = GCPComputeClient().status()
    except Exception as exc:
        current_app.logger.exception("orthophotos: no se pudo consultar la VM WebODM")
        return {
            "status": "unknown",
            "label": "Sin conexion",
            "color": "gray",
            "message": str(exc),
        }

    if status == "RUNNING":
        if _schedule_autostop_webodm_if_idle(current_app._get_current_object()):
            return {
                "status": "STOPPING_IDLE",
                "label": "Finalizando procesos",
                "color": "yellow",
                "message": "No hay ortofotos en proceso.",
            }
        return {
            "status": status,
            "label": "Procesamiento disponible",
            "color": "green",
            "message": "Hay procesos activos en este momento.",
        }
    if status in {"TERMINATED", "STOPPED"}:
        _fail_pre_webodm_missions_if_vm_is_down(status)
        return {
            "status": status,
            "label": "Procesamiento en espera",
            "color": "red",
            "message": "El procesamiento esta en espera.",
        }
    return {
        "status": status,
        "label": "Procesamiento en preparacion",
        "color": "yellow",
        "message": "El servicio de procesamiento se esta preparando.",
    }


def _refresh_processing_status(mission: OrthophotoMission) -> None:
    if not mission.webodm_project_id or not mission.webodm_task_id:
        return
    if mission.status in TERMINAL_STATUSES:
        return
    try:
        previous_status = mission.status
        task = WebODMClient().task(
            mission.webodm_project_id,
            mission.webodm_task_id,
        )
        mission.status = STATUS_NAMES.get(task.get("status"), mission.status)
        mission.progress = task.get("running_progress")
        mission.available_assets = task.get("available_assets")
        mission.processing_error = task.get("last_error")
        db.session.add(mission)
        db.session.commit()
        if (
            mission.status in TERMINAL_STATUSES
            and previous_status not in TERMINAL_STATUSES
        ):
            _autostop_webodm_if_idle(current_app._get_current_object())
    except Exception:
        db.session.rollback()


@web.route("/dashboard/orthophotos", methods=["GET", "POST"])
@login_required
def dashboard():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip() or None
        if not name:
            flash("Escribe un nombre para la mision.", "error")
        else:
            mission = OrthophotoMission(name=name, description=description)
            db.session.add(mission)
            db.session.commit()
            redirect_url = url_for("orthophotos.dashboard", created=mission.id)
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": True, "redirect_url": redirect_url})
            flash("Mision creada correctamente.", "success")
            return redirect(redirect_url)

    missions = OrthophotoMission.query.order_by(
        OrthophotoMission.created_at.desc()
    ).all()
    for mission in missions:
        _refresh_processing_status(mission)
    if any(
        mission.status in PRE_WEBODM_TASK_STATUSES and not mission.webodm_task_id
        for mission in missions
    ):
        try:
            _fail_pre_webodm_missions_if_vm_is_down(GCPComputeClient().status())
        except Exception:
            current_app.logger.exception("orthophotos: no se pudo reconciliar estado WebODM")
    created_id = request.args.get("created", type=int)
    created_mission = OrthophotoMission.query.get(created_id) if created_id else None
    webodm_vm_status = {
        "status": "loading",
        "label": "Consultando procesamiento",
        "color": "gray",
        "message": "Consultando estado del procesamiento en segundo plano.",
    }
    return render_template(
        "orthophotos/dashboard.j2",
        missions=missions,
        created_mission=created_mission,
        webodm_vm_status=webodm_vm_status,
        pilot_upload_url=lambda mission_id: _public_url_for(
            "orthophotos.pilot_upload",
            mission_id=mission_id,
        ),
        dashboard=True,
        data_menu=get_dashboard_menu(),
        **_context(),
        request=request,
    )


@web.route("/dashboard/orthophotos/webodm-status", methods=["GET"])
@login_required
def webodm_status():
    return jsonify(_webodm_vm_status_payload())


@web.route("/dashboard/orthophotos/<int:mission_id>/process", methods=["POST"])
@login_required
def process_mission(mission_id: int):
    mission = OrthophotoMission.query.get_or_404(mission_id)
    profile = request.form.get("profile", "max_2d")
    if profile not in PROCESSING_PROFILES:
        profile = "max_2d"
    photos = _processable_photos(mission)
    if len(photos) < 2:
        message = "La mision necesita minimo 2 fotos JPG/TIFF para generar una ortofoto."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "message": message}), 400
        flash(message, "error")
        return redirect(url_for("orthophotos.dashboard"))

    if mission.status in ACTIVE_STATUSES:
        message = "Esta mision ya esta en proceso."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "redirect_url": url_for("orthophotos.dashboard")})
        flash(message, "info")
        return redirect(url_for("orthophotos.dashboard"))

    mission.status = "submitting"
    mission.processing_error = None
    if not mission.webodm_project_id or not mission.webodm_task_id:
        mission.processing_job_id = None
    mission.progress = None
    mission.available_assets = None
    db.session.add(mission)
    db.session.commit()

    app = current_app._get_current_object()
    thread = threading.Thread(
        target=_submit_mission_to_webodm,
        args=(app, mission.id, profile),
        daemon=True,
        name=f"orthophoto-submit-{mission.id}",
    )
    thread.start()

    message = "Procesamiento iniciado. Puedes refrescar esta pantalla para ver el estado."
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "redirect_url": url_for("orthophotos.dashboard")})
    flash(message, "success")

    return redirect(url_for("orthophotos.dashboard"))


@web.route("/dashboard/orthophotos/<int:mission_id>/webodm", methods=["GET"])
@login_required
def open_webodm_task(mission_id: int):
    mission = OrthophotoMission.query.get_or_404(mission_id)
    if not mission.webodm_project_id or not mission.webodm_task_id:
        abort(404)
    return redirect(
        WebODMClient().task_browser_url(
            mission.webodm_project_id,
            mission.webodm_task_id,
        )
    )


@web.route("/dashboard/orthophotos/<int:mission_id>/download/<asset_key>", methods=["GET"])
@login_required
def download_mission_asset(mission_id: int, asset_key: str):
    mission = OrthophotoMission.query.get_or_404(mission_id)
    if not mission.webodm_project_id or not mission.webodm_task_id:
        abort(404)
    if asset_key not in DOWNLOADABLE_ASSETS:
        abort(404)

    asset_name, download_name = DOWNLOADABLE_ASSETS[asset_key]
    available_assets = mission.available_assets or []
    if available_assets and asset_name not in available_assets:
        abort(404)

    previous_status = mission.status
    mission.status = "downloading_asset"
    db.session.add(mission)
    db.session.commit()

    try:
        _ensure_webodm_ready_for_download()
        upstream = WebODMClient().download_asset(
            mission.webodm_project_id,
            mission.webodm_task_id,
            asset_name,
        )
    except Exception:
        db.session.rollback()
        mission = OrthophotoMission.query.get(mission_id)
        if mission:
            mission.status = previous_status
            db.session.add(mission)
            db.session.commit()
        raise

    def generate():
        try:
            for chunk in upstream.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()
            with current_app.app_context():
                finished_mission = OrthophotoMission.query.get(mission_id)
                if finished_mission and finished_mission.status == "downloading_asset":
                    finished_mission.status = previous_status
                    db.session.add(finished_mission)
                    db.session.commit()
                _autostop_webodm_if_idle(current_app._get_current_object())

    headers = {
        "Content-Disposition": f'attachment; filename="{download_name}"',
    }
    content_length = upstream.headers.get("Content-Length")
    if content_length:
        headers["Content-Length"] = content_length

    return Response(
        stream_with_context(generate()),
        headers=headers,
        content_type=upstream.headers.get("Content-Type", "application/octet-stream"),
    )


@web.route("/dashboard/orthophotos/<int:mission_id>/delete", methods=["POST"])
@login_required
def delete_mission(mission_id: int):
    mission = OrthophotoMission.query.get_or_404(mission_id)
    if mission.status in ACTIVE_STATUSES:
        message = "No se puede eliminar una mision mientras esta procesando."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "message": message}), 409
        flash(message, "error")
        return redirect(url_for("orthophotos.dashboard"))

    asset_ids = [photo.asset_id for photo in mission.photos if photo.asset_id]
    webodm_project_id = mission.webodm_project_id
    webodm_task_id = mission.webodm_task_id

    if webodm_project_id and webodm_task_id:
        try:
            WebODMClient().delete_task(webodm_project_id, webodm_task_id)
        except Exception:
            current_app.logger.exception("orthophotos: no se pudo eliminar task WebODM")

    try:
        db.session.delete(mission)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        message = f"No se pudo eliminar la mision: {exc}"
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "message": message}), 500
        flash(message, "error")
        return redirect(url_for("orthophotos.dashboard"))

    media = MediaController()
    deleted_assets = 0
    for asset_id in set(asset_ids):
        still_used = OrthophotoPhoto.query.filter_by(asset_id=asset_id).first()
        if still_used:
            continue
        try:
            if media.delete_asset(asset_id):
                deleted_assets += 1
        except Exception:
            db.session.rollback()
            current_app.logger.exception(
                "orthophotos: no se pudo eliminar asset %s", asset_id
            )

    message = f"Mision eliminada. Archivos eliminados: {deleted_assets}."
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "redirect_url": url_for("orthophotos.dashboard")})
    flash(message, "success")
    return redirect(url_for("orthophotos.dashboard"))


@web.route("/ortofotos/subir", methods=["GET"])
def pilot_upload():
    mission_id = request.args.get("mission_id", type=int)
    mission = OrthophotoMission.query.get(mission_id) if mission_id else None
    if mission is None:
        mission = (
            OrthophotoMission.query.order_by(OrthophotoMission.created_at.desc()).first()
        )
    missions = OrthophotoMission.query.order_by(
        OrthophotoMission.created_at.desc()
    ).all()
    return render_template(
        "orthophotos/pilot_upload.j2",
        mission=mission,
        missions=missions,
        upload_session_id=secrets.token_urlsafe(24),
        dashboard=False,
        app_home=False,
        basic_form_view=False,
        data_menu=None,
        **_context(
            title="Subir fotos de dron",
            page_title="Carga de fotos",
            description="Portal de carga para pilotos.",
        ),
        request=request,
    )
