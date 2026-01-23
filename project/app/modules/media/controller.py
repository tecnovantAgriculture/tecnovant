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
        elimina el archivo del almacenamiento local antes de borrar la fila en
        la base de datos. Los fallos al eliminar el archivo físico se ignoran de
        forma deliberada para priorizar la consistencia del catálogo de activos.

        :param asset_id: Identificador entero primario del activo objetivo.
        :returns: ``True`` si el activo fue eliminado; ``False`` cuando no se
            encontró registro alguno con el identificador indicado.
        """

        asset = Asset.query.get(asset_id)
        if not asset:
            return False
        # Only local storage supported for now
        from .helpers import _media_root
        base = _media_root()
        abs_path = os.path.join(base, asset.storage_key)
        try:
            if os.path.isfile(abs_path):
                os.remove(abs_path)
        except Exception:
            # Continue even if file missing or cannot delete
            pass
        db.session.delete(asset)
        db.session.commit()
        return True
