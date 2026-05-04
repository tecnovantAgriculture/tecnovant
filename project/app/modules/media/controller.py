"""Controlador de lógica de negocio para la gestión de archivos multimedia."""

from __future__ import annotations

import os
from typing import Optional, Tuple

from flask import current_app
from werkzeug.datastructures import FileStorage

from app.extensions import db

from .helpers import (
    allowed_extension,
    allocate_storage_path,
    capture_upload_to_temp,
    extract_geo_info_if_tiff,
    extract_image_info,
    generate_webp_thumbnails,
    guess_mime,
)
from .models import Asset, AssetType, AssetVariant, StorageLocation


class MediaController:
    """Orquesta la ingestión, inspección y eliminación de activos multimeda.

    La clase encapsula las decisiones de negocio relacionadas con cómo se
    almacenan los archivos subidos por los usuarios, qué metadatos se
    derivan de su contenido y cómo se sincronizan esas características con la
    base de datos relacional. De este modo la capa de enrutamiento puede
    delegar la manipulación de archivos y la persistencia sin conocer los
    detalles del sistema de ficheros ni las transformaciones realizadas.
    """

    def save_local_upload(self, file: FileStorage) -> Tuple[Asset, bool]:
        """Guardar un archivo recibido vía formulario dentro del almacenamiento local.

        El proceso valida la presencia de un nombre de archivo, garantiza que el
        tipo esté permitido, calcula el hash SHA-256 y el tamaño exacto sin
        duplicar IO innecesaria, persiste el archivo físico en disco y genera un
        registro `Asset` enriquecido con la información derivada (metadatos MIME,
        dimensiones de imagen, datos geoespaciales, etc.). Finalmente consolida
        los cambios en la base de datos para dejar el activo listo para su
        consumo mediante la API. Cuando el archivo ya existe (mismo hash/tamaño)
        devuelve el activo previo sin crear duplicados.

        :param file: Objeto suministrado por Werkzeug que encapsula el archivo
            enviado desde un formulario HTML, incluyendo el stream subyacente.
        :returns: Tupla ``(asset, created)`` donde ``asset`` es la entidad
            existente o recién creada y ``created`` indica si se trató de una
            inserción nueva.
        :raises ValueError: Si el archivo no existe o su extensión no está
            permitida por la configuración de la aplicación.
        """

        if not file or not getattr(file, "filename", None):
            raise ValueError("No file provided")

        filename = file.filename
        _, ext = os.path.splitext(filename)
        ext = ext.lower()
        if not allowed_extension(filename):
            raise ValueError("Unsupported file type")

        capture = capture_upload_to_temp(file)
        digest = capture.sha256
        size_bytes = capture.size_bytes
        existing_asset = (
            Asset.query.filter_by(sha256=digest, size_bytes=size_bytes)
            .order_by(Asset.id.desc())
            .first()
        )
        if existing_asset:
            capture.discard()
            try:
                existing_variants = {variant.kind for variant in existing_asset.variants}
            except Exception:
                existing_variants = set()

            thumb_specs = current_app.config.get("MEDIA_THUMBNAIL_SPECS") or {
                "gallery": {"max_width": 512, "max_height": 512}
            }
            required_kinds = set(thumb_specs.keys())
            missing_kinds = required_kinds - existing_variants

            if missing_kinds:
                from .helpers import _media_root

                abs_existing_path = os.path.join(_media_root(), existing_asset.storage_key)
                if not os.path.isfile(abs_existing_path):
                    current_app.logger.warning(
                        "Physical file missing for asset %s; cannot build thumbnail.", existing_asset.uuid
                    )
                    return existing_asset, False
                new_variants = False
                try:
                    thumb_results = generate_webp_thumbnails(abs_existing_path, existing_asset.uuid, specs=thumb_specs)
                    for thumb in thumb_results:
                        if thumb.kind not in missing_kinds:
                            continue
                        existing_asset.variants.append(
                            AssetVariant(
                                kind=thumb.kind,
                                storage=StorageLocation.LOCAL.value,
                                storage_key=thumb.storage_key,
                                width=thumb.width,
                                height=thumb.height,
                            )
                        )
                        new_variants = True
                    if new_variants:
                        db.session.add(existing_asset)
                        db.session.commit()
                except Exception:
                    current_app.logger.exception(
                        "Thumbnail regeneration failed for existing asset %s", existing_asset.uuid
                    )
            return existing_asset, False

        storage_key, abs_path = allocate_storage_path(ext)
        capture.move_to(abs_path)

        # Metadata
        mime = guess_mime(abs_path)
        img = extract_image_info(abs_path)
        geo = extract_geo_info_if_tiff(abs_path)

        # Derive meters-per-pixel from GeoTIFF affine transform
        mpp = _derive_mpp_from_transform(geo)

        asset_type = (
            AssetType.GEOTIFF.value if ext in {".tif", ".tiff"} else AssetType.IMAGE.value
        )

        asset = Asset(
            uuid=os.path.splitext(os.path.basename(abs_path))[0],
            original_name=filename,
            ext=ext.lstrip("."),
            mime=mime,
            asset_type=asset_type,
            storage=StorageLocation.LOCAL.value,
            storage_key=storage_key,
            sha256=digest,
            size_bytes=size_bytes,
            width=img.width,
            height=img.height,
            is_geo=geo.is_geo,
            crs=geo.crs,
            bounds=geo.bounds,
            transform=geo.transform,
            mpp=mpp,
            exif=img.exif,
        )

        if asset_type in {AssetType.IMAGE.value, AssetType.GEOTIFF.value}:
            try:
                thumb_results = generate_webp_thumbnails(abs_path, asset.uuid)
                for thumb in thumb_results:
                    asset.variants.append(
                        AssetVariant(
                            kind=thumb.kind,
                            storage=StorageLocation.LOCAL.value,
                            storage_key=thumb.storage_key,
                            width=thumb.width,
                            height=thumb.height,
                        )
                    )
            except Exception:
                current_app.logger.exception("Thumbnail generation failed for %s", asset.uuid)

        db.session.add(asset)
        db.session.commit()
        return asset, True

    def delete_asset(self, asset_id: int) -> bool:
        """Retirar un activo de la base de datos y su archivo físico asociado.

        La operación busca de forma perezosa el activo solicitado, detiene la
        ejecución si no existe un registro coincidente y, en caso de hallarlo,
        elimina:
        1. El archivo fuente del almacenamiento local.
        2. Los archivos de variantes (thumbnails, previews).
        3. El directorio de caché de preprocesamiento (``cache/<uuid>/``).
        4. Registros NDVIImage en Agrovista y sus archivos ``.npy``/``.png``.

        Los fallos al eliminar archivos físicos se ignoran de forma deliberada
        para priorizar la consistencia de la base de datos.

        :param asset_id: Identificador entero primario del activo objetivo.
        :returns: ``True`` si el activo fue eliminado; ``False`` cuando no se
            encontró registro alguno con el identificador indicado.
        """

        asset = Asset.query.get(asset_id)
        if not asset:
            return False

        # 1. Remove source file
        from .helpers import _media_root
        base = _media_root()
        abs_path = os.path.join(base, asset.storage_key)
        try:
            if os.path.isfile(abs_path):
                os.remove(abs_path)
        except Exception:
            pass

        # 2. Remove variant files
        for variant in asset.variants:
            try:
                v_path = os.path.join(base, variant.storage_key)
                if os.path.isfile(v_path):
                    os.remove(v_path)
            except Exception:
                pass

        # 3. Remove preprocessing cache directory
        try:
            cache_root_cfg = current_app.config.get("MEDIA_PREPROCESS_CACHE_DIR")
            if cache_root_cfg:
                cache_root = Path(cache_root_cfg)
            else:
                cache_root = Path(base) / "cache"
            cache_dir = cache_root / asset.uuid
            if cache_dir.exists():
                import shutil
                shutil.rmtree(cache_dir, ignore_errors=True)
        except Exception:
            pass

        # 4. Remove Agrovista NDVIImage records and their data files
        try:
            self._cleanup_agrovista_data(asset.uuid)
        except Exception:
            pass

        db.session.delete(asset)
        db.session.commit()
        return True

    @staticmethod
    def _cleanup_agrovista_data(asset_uuid: str) -> None:
        """Remove NDVIImage records and associated data files for an asset."""
        from app.modules.agrovista.helpers import DATA_DIR as AGROVISTA_DATA_DIR
        from app.modules.agrovista.models import NDVIImage
        from app.extensions import db

        records = NDVIImage.query.filter(NDVIImage.id == asset_uuid).all()
        for record in records:
            # Remove data files referenced by model fields
            for path_attr in ("npy_path", "png_path"):
                file_path = getattr(record, path_attr, None)
                if file_path:
                    try:
                        p = Path(file_path)
                        if p.exists():
                            p.unlink(missing_ok=True)
                    except Exception:
                        pass
            # Remove raw source files matching the id
            try:
                for candidate in AGROVISTA_DATA_DIR.glob(f"{record.id}_raw.*"):
                    candidate.unlink(missing_ok=True)
            except Exception:
                pass
            # Remove metadata JSON (path schema: {id}.json)
            try:
                meta_p = AGROVISTA_DATA_DIR / f"{record.id}.json"
                if meta_p.exists():
                    meta_p.unlink(missing_ok=True)
            except Exception:
                pass
            db.session.delete(record)
        if records:
            db.session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_mpp_from_transform(geo) -> Optional[float]:
    """Derive meters-per-pixel from a GeoTIFF affine transform.

    The rasterio affine transform stores ``a`` (pixel width in CRS units)
    and ``e`` (pixel height, normally negative).  When the CRS uses metres
    (e.g. UTM), these values directly represent the ground resolution.

    For degree-based CRS (e.g. EPSG:4326), we approximate 1° ≈ 111,320 m
    at the equator to convert coefficients to metres.  This is only an
    approximation — it's sufficient for area estimation but will vary
    with latitude.

    Returns ``None`` when the geometry info is missing or the coefficients
    look invalid.
    """
    if not geo or not geo.transform:
        return None

    t = geo.transform
    a = abs(t.get("a", 0))
    e = abs(t.get("e", 0))

    if not a or not e:
        return None

    # Check if CRS is in degrees (EPSG:4326 or similar)
    crs_str = (geo.crs or "").upper()
    is_degrees = "EPSG:4326" in crs_str or "GEOGCRS" in crs_str or "DEGREE" in crs_str

    if is_degrees:
        # Approximate: 1 degree latitude ≈ 111,320 m
        # Longitude degrees shrink with cos(lat); use center of bounds if available
        lat = None
        if geo.bounds:
            lat = (geo.bounds.get("bottom", 0) + geo.bounds.get("top", 0)) / 2
        import math
        lat_rad = math.radians(abs(lat)) if lat is not None else 0
        m_per_deg_lat = 111320.0
        m_per_deg_lon = 111320.0 * math.cos(lat_rad)
        mx = a * m_per_deg_lon
        my = e * m_per_deg_lon  # approximate: assume similar scale
        if mx < 0.01 or my < 0.01:
            return None
        return max(mx, my)
    else:
        # Projected CRS — coefficients are already in metres
        if a < 0.001 or e < 0.001:
            return None
        return max(a, e)
