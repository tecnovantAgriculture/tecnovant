"""Funciones auxiliares para resolver fuentes de datos de índices de vegetación."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

from .services.storage import LocalStorage, S3Storage, StorageBackend


def get_storage_and_path(source: str) -> Tuple[StorageBackend, str]:
    """Obtener el backend de almacenamiento y la ruta interna desde una URI.

    Se aceptan dos esquemas principales:

    * ``local:/ruta/archivo``: utiliza el backend ``LocalStorage``. Si la
      variable de entorno ``VEGINDEX_LOCAL_BASE`` está definida, la ruta se
      resuelve de forma relativa a dicho directorio; en caso contrario se usa la
      ruta proporcionada.
    * ``s3://bucket/key`` o ``s3:bucket/key``: resuelve a ``S3Storage`` y, si la
      variable ``VEGINDEX_S3_BUCKET`` está presente, se utiliza como valor
      predeterminado cuando el esquema alternativo ``s3:`` no incluye bucket.

    :param source: Cadena con la localización del archivo de entrada.
    :returns: Tupla con el backend instanciado y la ruta limpia para lectura.
    :raises ValueError: Cuando el esquema de la fuente no es reconocido por el
        módulo.
    """

    if source.startswith("local:"):
        base_dir = os.getenv("VEGINDEX_LOCAL_BASE")
        base = Path(base_dir).resolve() if base_dir else None
        return LocalStorage(base), source.split("local:", 1)[1]
    if source.startswith("s3://") or source.startswith("s3:"):
        bucket = os.getenv("VEGINDEX_S3_BUCKET")
        clean = source.replace("s3:", "", 1) if source.startswith("s3:") else source
        return S3Storage(bucket=bucket), clean
    raise ValueError("Unsupported source. Use local:<path> or s3://bucket/key")
