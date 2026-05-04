"""📃 Rutas web del módulo Media (gestión de assets/imágenes)

CONVENCIÓN DE DECORADORES DE AUTENTICACIÓN:
- @login_required: Para rutas web estándar (redirige a login si no autenticado)
- @jwt_required(): Para rutas que requieren validación JWT explícita
- @api_login_required: Para rutas API que devuelven JSON 401 (no redirección)

Este módulo usa exclusivamente @login_required para todas sus rutas web.
"""

import json
import os
from pathlib import Path

from flask import flash, redirect, render_template, request, send_from_directory, url_for
from sqlalchemy.orm import selectinload

from app.core.controller import login_required
from app.helpers.dashboard_helpers import get_dashboard_menu

from . import media as web
from .controller import MediaController
from .helpers import _media_root
from .models import Asset, AssetType
from .tasks import enqueue_preprocess_asset


def _parse_allowed_types(raw: str | None) -> set[str]:
    """Normaliza la lista de tipos de activo permitidos dentro del selector.

    El parámetro ``raw`` acepta una cadena separada por comas con los valores
    declarados en :class:`~app.modules.media.models.AssetType`. Aquellos tokens
    desconocidos se descartan silenciosamente para permitir enlaces robustos en
    otras vistas (por ejemplo, ``agrovista.hello``) sin necesidad de validar en
    cada consumidor.
    """

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


@web.route("/hello", methods=["GET"])
def hello():
    return render_template("media/hello.j2")


@web.route("/", methods=["GET"])
@login_required
def library():
    """Vista: Biblioteca de medios con filtros reutilizables y modo selector.

    El endpoint concentra la lógica de descubrimiento de archivos multimedia y
    expone un modo opcional ``picker`` pensado para consumidores embebidos como
    ``agrovista.hello``. De esta manera todo el backend relacionado con activos
    (búsqueda, filtros, paginación) permanece dentro del módulo ``media`` y los
    clientes solo necesitan incorporar el frontend generado por esta vista.
    """
    # Parámetros comunes
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
        "site_title": "Medios",
        "data_menu": get_dashboard_menu(),
    }
    if picker_mode:
        context["data_menu"] = None

    # Si hay un subconjunto permitido y el filtro actual no pertenece a él,
    # forzamos a utilizar el primero disponible para evitar resultados vacíos.
    if allowed_types and type_filter not in allowed_types and type_filter != "all":
        type_filter = next(iter(sorted(allowed_types)))

    pagination = _fetch_assets_for_library(q=q, type_filter=type_filter if type_filter != "all" else None, page=page, per_page=per_page)
    items = pagination.items

    return render_template(
        "media/library.j2",
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

@web.route("/element/<int:objective_id>", methods=["GET"])
@login_required
def element(objective_id: int):
    """Vista: Detalle de un activo multimedia."""
    asset = Asset.query.options(selectinload(Asset.variants)).get_or_404(objective_id)
    thumb_variant = next((variant for variant in asset.variants if variant.kind == "gallery"), None)
    asset_url = url_for("media.serve_file", key=asset.storage_key)
    thumb_url = url_for("media.serve_file", key=thumb_variant.storage_key) if thumb_variant else asset_url
    download_url = url_for("media.download_file", key=asset.storage_key)
    cache_rel_dir = os.path.join("cache", asset.uuid)
    cache_abs_dir = os.path.join(_media_root(), cache_rel_dir)
    preview_defs = [
        ("rgb_norm", f"{asset.uuid}__rgb_preproc_preview.png", "RGB normalizado"),
        ("vi_gr", f"{asset.uuid}__vi_gr_ratio.png", "VI (G/R)"),
        ("vi_heat", f"{asset.uuid}__vi_gr_heat.png", "Mapa térmico VI"),
        ("heatmap", f"{asset.uuid}__vi_heatmap.png", "Heatmap vegetación"),
        ("nd_index_rgba", f"{asset.uuid}__nd_index_rgba.png", "Índice espectral (RGBA)"),
    ]
    preproc_previews = []
    for key, filename, label in preview_defs:
        abs_path = os.path.join(cache_abs_dir, filename)
        if os.path.isfile(abs_path):
            url = url_for("media.serve_file", key=os.path.join(cache_rel_dir, filename))
            preproc_previews.append({"id": key, "label": label, "url": url})
    processing_flag = os.path.join(cache_abs_dir, ".processing")
    status_file = os.path.join(cache_abs_dir, ".status.json")
    error_flag = os.path.join(cache_abs_dir, ".error")
    
    is_processing = os.path.isfile(processing_flag)
    error_message: str | None = None
    status_data = None
    
    # Read detailed status if available
    if os.path.isfile(status_file):
        try:
            with open(status_file, "r", encoding="utf-8") as fh:
                status_data = json.load(fh)
        except Exception:
            status_data = None
    
    if os.path.isfile(error_flag):
        try:
            with open(error_flag, "r", encoding="utf-8") as fh:
                error_message = fh.read().strip() or None
        except Exception:
            error_message = "No fue posible leer el estado de error del procesamiento."
    
    # Build status object for template
    preproc_status = {
        "is_processing": is_processing,
        "error": error_message,
        "status": status_data,
    }

    context = {
        "dashboard": True,
        "title": f"Detalle de {asset.original_name}",
        "description": "Vista detallada del elemento multimedia.",
        "author": "TecnoAgro",
        "site_title": "Medios",
        "data_menu": get_dashboard_menu(),
    }
    return render_template(
        "media/element.j2",
        asset=asset,
        thumb_url=thumb_url,
        asset_url=asset_url,
        download_url=download_url,
        preproc_previews=preproc_previews,
        preproc_status=preproc_status,
        **context,
        request=request,
    )


@web.route("/element/<int:objective_id>/reprocess", methods=["POST"])
@login_required
def element_reprocess(objective_id: int):
    """Re-encolar el procesamiento en background para un activo."""
    asset = Asset.query.get_or_404(objective_id)
    cache_rel_dir = os.path.join("cache", asset.uuid)
    cache_abs_dir = os.path.join(_media_root(), cache_rel_dir)
    os.makedirs(cache_abs_dir, exist_ok=True)
    processing_flag = os.path.join(cache_abs_dir, ".processing")
    error_flag = os.path.join(cache_abs_dir, ".error")
    try:
        with open(processing_flag, "w", encoding="utf-8") as fh:
            fh.write("queued")
    except Exception:
        try:
            Path(processing_flag).touch(exist_ok=True)  # type: ignore[arg-type]
        except Exception:
            pass
    try:
        if os.path.exists(error_flag):
            os.remove(error_flag)
    except Exception:
        pass
    enqueue_preprocess_asset(asset.id)
    flash("Se encoló el reprocesamiento del activo. Este proceso puede tardar varios minutos según el tamaño del archivo.", "info")
    return redirect(url_for("media.element", objective_id=objective_id))

@web.route("/upload", methods=["GET", "POST"])
@login_required
def upload_local():
    """Vista: Subida de archivos desde el equipo (solo UI).

    Soporta modo picker para ser embebido en modales. Cuando ``picker=1``,
    se omite el layout completo (header/menú/footer) para integrarse
    correctamente en iframes o modales.
    """
    picker_mode = str(request.args.get("picker", "0")).lower() in {"1", "true", "yes"}
    picker_event = request.args.get("event", "media-library:select")
    picker_multi = str(request.args.get("multi", "0")).lower() in {"1", "true", "yes"}
    allowed_types = _parse_allowed_types(request.args.get("allowed"))

    context = {
        "dashboard": not picker_mode,
        "title": "Subir desde tu equipo",
        "description": "Selecciona imágenes para subir (TIFF, PNG, JPG, JPEG).",
        "author": "TecnoAgro",
        "site_title": "Medios",
        "data_menu": None if picker_mode else get_dashboard_menu(),
    }

    if request.method == "POST":
        file = request.files.get("media_files")
        if not file:
            flash("Debes seleccionar un archivo.", "error")
            return render_template(
                "media/upload_local.j2",
                **context,
                request=request,
                picker_mode=picker_mode,
                picker_event_name=picker_event,
                picker_multi=picker_multi,
                picker_allowed_types=sorted(allowed_types),
            ), 400
        try:
            ctrl = MediaController()
            asset, created = ctrl.save_local_upload(file)
            enqueue_preprocess_asset(asset.id)
            flash(
                "Archivo subido correctamente." if created else "El archivo ya existía y se reutilizó el registro.",
                "success",
            )
            return render_template(
                "media/upload_local.j2",
                **context,
                request=request,
                picker_mode=picker_mode,
                picker_event_name=picker_event,
                picker_multi=picker_multi,
                picker_allowed_types=sorted(allowed_types),
            )
        except ValueError as e:
            flash(str(e), "error")
            return render_template(
                "media/upload_local.j2",
                **context,
                request=request,
                picker_mode=picker_mode,
                picker_event_name=picker_event,
                picker_multi=picker_multi,
                picker_allowed_types=sorted(allowed_types),
            ), 400
        except Exception:
            flash("Error subiendo el archivo.", "error")
            return render_template(
                "media/upload_local.j2",
                **context,
                request=request,
                picker_mode=picker_mode,
                picker_event_name=picker_event,
                picker_multi=picker_multi,
                picker_allowed_types=sorted(allowed_types),
            ), 500

    return render_template(
        "media/upload_local.j2",
        **context,
        request=request,
        picker_mode=picker_mode,
        picker_event_name=picker_event,
        picker_multi=picker_multi,
        picker_allowed_types=sorted(allowed_types),
    )


@web.route("/upload/s3", methods=["GET"])
@login_required
def upload_s3():
    """Vista: Importar desde S3 (solo UI, no implementado).

    Soporta modo picker para ser embebido en modales. Cuando ``picker=1``,
    se omite el layout completo (header/menú/footer) para integrarse
    correctamente en iframes o modales.
    """
    picker_mode = str(request.args.get("picker", "0")).lower() in {"1", "true", "yes"}
    picker_event = request.args.get("event", "media-library:select")
    picker_multi = str(request.args.get("multi", "0")).lower() in {"1", "true", "yes"}
    allowed_types = _parse_allowed_types(request.args.get("allowed"))

    context = {
        "dashboard": not picker_mode,
        "title": "Importar desde S3",
        "description": "Configura el origen en S3 para importar medios.",
        "author": "TecnoAgro",
        "site_title": "Medios",
        "data_menu": None if picker_mode else get_dashboard_menu(),
    }

    return render_template(
        "media/upload_s3.j2",
        **context,
        request=request,
        picker_mode=picker_mode,
        picker_event_name=picker_event,
        picker_multi=picker_multi,
        picker_allowed_types=sorted(allowed_types),
    )


@web.route("/file/<path:key>", methods=["GET"])
@login_required
def serve_file(key: str):
    # Only allow to serve under the media root
    base = _media_root()
    directory = os.path.join(base, os.path.dirname(key))
    filename = os.path.basename(key)
    return send_from_directory(directory, filename)


@web.route("/download/<path:key>", methods=["GET"])
@login_required
def download_file(key: str):
    base = _media_root()
    directory = os.path.join(base, os.path.dirname(key))
    filename = os.path.basename(key)
    return send_from_directory(directory, filename, as_attachment=True)


@web.route("/admin/cleanup", methods=["GET"])
@login_required
def admin_cleanup():
    """Admin interface for cache cleanup and monitoring."""
    from pathlib import Path
    import json
    import time
    
    # Get cache root directory
    root_cfg = current_app.config.get("MEDIA_PREPROCESS_CACHE_DIR")
    if root_cfg:
        cache_root = Path(root_cfg)
    else:
        from .helpers import _media_root
        cache_root = Path(_media_root()) / "cache"
    
    cache_info = {
        "exists": cache_root.exists(),
        "path": str(cache_root),
        "total_dirs": 0,
        "orphaned_processing": 0,
        "recent_errors": 0,
        "total_size_mb": 0,
    }
    
    if cache_root.exists():
        # Scan cache directory
        cache_dirs = []
        for cache_dir in cache_root.iterdir():
            if not cache_dir.is_dir():
                continue
            
            dir_info = {
                "name": cache_dir.name,
                "exists": True,
                "has_processing": False,
                "has_error": False,
                "has_status": False,
                "age_hours": 0,
                "size_mb": 0,
                "files": [],
            }
            
            # Check for flags
            processing_flag = cache_dir / ".processing"
            error_flag = cache_dir / ".error"
            status_file = cache_dir / ".status.json"
            
            if processing_flag.exists():
                dir_info["has_processing"] = True
                cache_info["orphaned_processing"] += 1
                
                # Check age
                file_age = time.time() - processing_flag.stat().st_mtime
                dir_info["age_hours"] = file_age / 3600
                
                # Check if orphaned (> 30 minutes)
                dir_info["is_orphaned"] = file_age > 1800
            
            if error_flag.exists():
                dir_info["has_error"] = True
                cache_info["recent_errors"] += 1
                
                try:
                    dir_info["error_message"] = error_flag.read_text()[:100]
                except:
                    dir_info["error_message"] = "Error reading error file"
            
            if status_file.exists():
                dir_info["has_status"] = True
                try:
                    status_data = json.loads(status_file.read_text())
                    dir_info["status"] = status_data.get("state", "unknown")
                    dir_info["progress"] = status_data.get("progress", 0)
                except:
                    dir_info["status"] = "corrupted"
            
            # Calculate size
            try:
                total_size = 0
                for file in cache_dir.glob("**/*"):
                    if file.is_file():
                        total_size += file.stat().st_size
                        dir_info["files"].append({
                            "name": file.name,
                            "size_mb": file.stat().st_size / (1024 * 1024),
                            "ext": file.suffix.lower()
                        })
                
                dir_info["size_mb"] = total_size / (1024 * 1024)
                cache_info["total_size_mb"] += dir_info["size_mb"]
            except:
                pass
            
            cache_dirs.append(dir_info)
            cache_info["total_dirs"] += 1
        
        # Sort by age (oldest first)
        cache_dirs.sort(key=lambda x: x.get("age_hours", 0), reverse=True)
        
        return render_template(
            "media/admin_cleanup.j2",
            menu=get_dashboard_menu(),
            cache_info=cache_info,
            cache_dirs=cache_dirs,
            title="Media Cache Admin"
        )
    else:
        return render_template(
            "media/admin_cleanup.j2",
            menu=get_dashboard_menu(),
            cache_info=cache_info,
            cache_dirs=[],
            title="Media Cache Admin"
        )
