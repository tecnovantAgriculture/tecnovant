"""Rutinas de negocio para transformar fuentes en índices de vegetación."""

from __future__ import annotations

from typing import Dict, Optional, Sequence

import numpy as np

from .helpers import get_storage_and_path
from .services.indices import (
    compute_vari,
    load_rgb_from_bytes,
    mask_and_normalize_uint8,
    vari_to_protein_vector,
)


def compute_from_source(
    source: str,
    bbox: Optional[Sequence[int]] = None,
) -> Dict:
    """Derivar estadísticas VARI y proteína estimada desde un recurso raster.

    La función identifica el backend de almacenamiento adecuado en función de la
    URI ``source``, descarga el archivo en memoria y extrae los canales RGB
    combinando herramientas de la capa ``services``. Una vez normalizados los
    canales y aplicado el enmascaramiento respecto al valor ``nodata``, se
    calcula el índice VARI. Si se especifica ``bbox`` el resultado se recorta a
    la ventana solicitada garantizando límites válidos.

    Con la matriz resultante se filtran los valores inválidos, se proyecta la
    distribución hacia el vector de proteína mediante ``vari_to_protein_vector``
    y se construye un diccionario con las estadísticas relevantes para su
    exposición vía API o plantillas.

    :param source: Localizador de la imagen en formato ``backend:/ruta`` (por
        ejemplo ``local:/data/archivo.tif`` o ``s3://bucket/clave``).
    :param bbox: Secuencia opcional con cuatro enteros ``[xmin, ymin, xmax, ymax]``
        que delimita la porción de la escena a analizar.
    :returns: Diccionario con el conteo de píxeles válidos, estadísticas de VARI,
        forma del arreglo y media de proteína estimada.
    :raises ValueError: Propagada desde la capa de almacenamiento si la fuente
        no es accesible o tiene un formato no soportado.
    """

    storage, path = get_storage_and_path(source)
    data = storage.read_bytes(path)
    red, green, blue, nodata = load_rgb_from_bytes(data)
    red_n, green_n, blue_n = mask_and_normalize_uint8(red, green, blue, nodata)
    vari = compute_vari(green_n, red_n, blue_n)

    if bbox:
        xmin, ymin, xmax, ymax = [int(x) for x in bbox]
        xmin = max(0, xmin)
        ymin = max(0, ymin)
        xmax = min(vari.shape[1], max(xmin + 1, xmax))
        ymax = min(vari.shape[0], max(ymin + 1, ymax))
        vari = vari[ymin:ymax, xmin:xmax]

    subset = np.ma.masked_invalid(vari).compressed()
    if subset.size == 0:
        return {"count": 0, "mean_protein": None, "vari_stats": None}

    protein = vari_to_protein_vector(subset)
    protein = protein[~np.isnan(protein)]
    mean_protein = float(np.mean(protein)) if protein.size else None

    return {
        "count": int(subset.size),
        "mean_protein": mean_protein,
        "vari_stats": {
            "min": float(np.min(subset)),
            "max": float(np.max(subset)),
            "mean": float(np.mean(subset)),
        },
        "shape": (
            [int(vari.shape[0]), int(vari.shape[1])] if hasattr(vari, "shape") else None
        ),
    }
