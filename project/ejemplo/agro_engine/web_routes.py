"""Consolidated web routes prioritizing agrovista views."""

import os
from pathlib import Path

from flask import flash, redirect, render_template, request, send_from_directory, url_for
from sqlalchemy.orm import selectinload

from app.core.controller import login_required
from app.extensions import db

from . import agro_engine as web
from .controller import MediaController
from .helpers import _media_root
from .models import Asset, AssetType


def get_dashboard_menu():
    """Define el menu superior en los templates"""
    return {
        "menu": [
            {"name": "Home", "url": url_for("core.index")},
            {"name": "Logout", "url": url_for("core.logout")},
            {"name": "Profile", "url": url_for("core.profile")},
        ]
    }


# ==================== Agrovista Web Routes (Priority) ====================

@web.route("/", methods=["GET"])
@login_required
def ndvi_tool():
    """NDVI Tool main view."""
    context = {
        "dashboard": True,
        "title": "NDVI Tool",
        "description": "Herramienta para el analisis NDVI.",
        "author": "Johnny De Castro",
        "site_title": "Análisis de Imagenes",
        "data_menu": get_dashboard_menu(),
        "entity_name": "Reportes",
        "entity_name_lower": "reporte",
    }
    return render_template("agro_engine/ndvi-tool.j2", **context)


@web.route("/secondary-objectives", methods=["GET"])
@login_required
def secondary_objectives():
    """Secondary objectives management view."""
    context = {
        "dashboard": True,
        "title": "Objetivos secundarios",
        "description": "Gestion primaria de objetivos secundarios para NDVI.",
        "author": "Johnny De Castro",
        "site_title": "Agro Engine",
        "data_menu": get_dashboard_menu(),
        "entity_name": "Objetivos secundarios",
        "entity_name_lower": "objetivo secundario",
    }
    return render_template("agro_engine/secondary-objectives.j2", **context)


# ==================== Media Web Routes ====================

def _parse_allowed_types(raw: str | None) -> set[str]:
    """Normaliza la lista de tipos de activo permitidos dentro del selector."""
    if not raw:
        return set()
    valid = {choice.value for choice in AssetType}
    pieces = {chunk.strip().lower() for chunk in raw.split(",")}
    return {piece for piece in pieces if piece in valid}


def _fetch_assets_for_library(q: str | None, type_filter: str | None, page: int, per_page: int):
    """Obtiene la paginación de activos aplicando los filtros indicados."""
    query = Asset.query
    if q:
        like = f"%{q}%"
        query = query.filter(Asset.original_name.ilike(like))
    if type_filter == AssetType.IMAGE.value:
        query = query.filter(Asset.asset_type == AssetType.IMAGE.value)
    elif type_filter == AssetType.GEOTIFF.value:
        query = query.filter(Asset.asset_type == AssetType.GEOTIFF.value)

    query = query.options(selectinload(Asset.variants))
    query = query.order_by(Asset.created_at.desc())
    return query.paginate(page=page, per_page=per_page, error_out=False)


@web.route("/library", methods=["GET"])
@login_required
def library():
    """Media library view."""
    q = request.args.get("q", type=str)
    type_filter = (request.args.get("type", default="all", type=str) or "all").lower()
    page = request.args.get("page", default=1, type=int)
    per_page = request.args.get("per_page", default=24, type=int)

    picker_mode = str(request.args.get("picker", "0")).lower() in {"1", "true", "yes"}
    allowed_types = _parse_allowed_types(request.args.get("allowed"))
    picker_event = request.args.get("event", "media-library:select")
    picker_multi = str(request.args.get("multi", "0")).lower() in {"1", "true", "yes"}

    context = {
        "dashboard": not picker_mode,
        "title": "Biblioteca de Medios",
        "description": "Administra imágenes y archivos de medios.",
        "author": "TecnoAgro",
        "site_title": "Agro Engine",
        "data_menu": get_dashboard_menu(),
    }
    if picker_mode:
        context["data_menu"] = None

    if allowed_types and type_filter not in allowed_types and type_filter != "all":
        type_filter = next(iter(sorted(allowed_types)))

    pagination = _fetch_assets_for_library(
        q=q,
        type_filter=type_filter if type_filter != "all" else None,
        page=page,
        per_page=per_page
    )
    items = pagination.items

    return render_template(
        "agro_engine/library.j2",
        items=items,
        pagination=pagination,
        q=q or "",
        type_filter=type_filter,
        per_page=per_page,
        **context,
        request=request,
        picker_mode=picker_mode,
        picker_allowed_types=sorted(allowed_types),
        picker_event_name=picker_event,
        picker_multi=picker_multi,
    )


@web.route("/element/<int:asset_id>", methods=["GET"])
@login_required
def element(asset_id: int):
    """Media asset detail view."""
    asset = Asset.query.options(selectinload(Asset.variants)).get_or_404(asset_id)
    thumb_variant = next((variant for variant in asset.variants if variant.kind == "gallery"), None)
    asset_url = url_for("agro_engine.serve_file", key=asset.storage_key)
    thumb_url = url_for("agro_engine.serve_file", key=thumb_variant.storage_key) if thumb_variant else asset_url
    download_url = url_for("agro_engine.download_file", key=asset.storage_key)

    context = {
        "dashboard": True,
        "title": f"Detalle de {asset.original_name}",
        "description": "Vista detallada del elemento multimedia.",
        "author": "TecnoAgro",
        "site_title": "Agro Engine",
        "data_menu": get_dashboard_menu(),
    }
    return render_template(
        "agro_engine/element.j2",
        asset=asset,
        thumb_url=thumb_url,
        asset_url=asset_url,
        download_url=download_url,
        **context,
        request=request,
    )


@web.route("/upload", methods=["GET", "POST"])
@login_required
def upload_local():
    """Upload local files view."""
    context = {
        "dashboard": True,
        "title": "Subir desde tu equipo",
        "description": "Selecciona imágenes para subir (TIFF, PNG, JPG, JPEG).",
        "author": "TecnoAgro",
        "site_title": "Agro Engine",
        "data_menu": get_dashboard_menu(),
    }
    if request.method == "POST":
        file = request.files.get("media_files")
        if not file:
            flash("Debes seleccionar un archivo.", "error")
            return render_template("agro_engine/upload_local.j2", **context, request=request), 400
        try:
            ctrl = MediaController()
            asset, created = ctrl.save_local_upload(file)
            flash(
                "Archivo subido correctamente." if created else "El archivo ya existía y se reutilizó el registro.",
                "success",
            )
            return render_template("agro_engine/upload_local.j2", **context, request=request)
        except ValueError as e:
            flash(str(e), "error")
            return render_template("agro_engine/upload_local.j2", **context, request=request), 400
        except Exception:
            flash("Error subiendo el archivo.", "error")
            return render_template("agro_engine/upload_local.j2", **context, request=request), 500
    return render_template("agro_engine/upload_local.j2", **context, request=request)


@web.route("/upload/s3", methods=["GET"])
@login_required
def upload_s3():
    """Upload from S3 view (placeholder)."""
    context = {
        "dashboard": True,
        "title": "Importar desde S3",
        "description": "Configura el origen en S3 para importar medios.",
        "author": "TecnoAgro",
        "site_title": "Agro Engine",
        "data_menu": get_dashboard_menu(),
    }
    return render_template("agro_engine/upload_s3.j2", **context, request=request)


@web.route("/file/<path:key>", methods=["GET"])
@login_required
def serve_file(key: str):
    """Serve media files."""
    base = _media_root()
    directory = os.path.join(base, os.path.dirname(key))
    filename = os.path.basename(key)
    return send_from_directory(directory, filename)


@web.route("/download/<path:key>", methods=["GET"])
@login_required
def download_file(key: str):
    """Download media files."""
    base = _media_root()
    directory = os.path.join(base, os.path.dirname(key))
    filename = os.path.basename(key)
    return send_from_directory(directory, filename, as_attachment=True)
