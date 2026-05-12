"""NPY RGB linear cache — LEGACY (kept for reference and compatibility).

Before TIF-direct access was introduced (see ``helpers.py``), the preprocessing
pipeline stored the full linear RGB array in a memory-mapped ``.npy`` file:

    {cache_dir}/{asset_uuid}__rgb_preproc_linear.npy   (dtype=float32, shape=(H,W,3))

This file can reach 6–7 GB for large GeoTIFFs (e.g. 16 370 × 34 030 pixels).

## Por qué fue reemplazado

``_protein_from_media`` en ``agrovista/api_routes.py`` cargaba via mmap el
archivo completo para extraer un recorte BBox de ~200 × 200 px.  El SO provocaba
page-faults proporcionales al recorte solicitado, no al tamaño del archivo, pero
los 6 GB en disco permanecían hasta ser eliminados manualmente.

El nuevo enfoque almacena solo un sidecar de 57 bytes (``.wb.json``) con los
factores globales de balance de blancos (gray-world) y lee los recortes BBox
directamente del GeoTIFF comprimido (rasterio solo descomprime los tiles LZW
de 256 × 256 que intersectan la ventana, ~4 ms para un recorte de 200 × 200
sobre una imagen de 16 k × 34 k píxeles).

## Cuándo usar estas funciones

- **Migración**: convertir despliegues viejos con caches ``.npy`` al formato
  ``.wb.json`` sin re-subir imágenes.
- **Depuración**: comparar valores de píxel entre el pipeline viejo y el nuevo.
- **Lectores de respaldo**: leer archivos ``.npy`` escritos antes del refactor
  (p.ej. servidores de producción más antiguos).

No llames a ``write_linear_rgb_npy`` en pipelines de preprocesamiento nuevos.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import rasterio
from numpy.typing import NDArray

from .helpers import (
    PreprocessConfig,
    _dtype_max,
    gray_world,
    iter_windows,
    srgb_to_linear,
)


def npy_path_for(cache_dir: Path, stem: str) -> Path:
    """Devuelve la ruta canónica del archivo ``.npy`` para un asset cacheado.

    Parameters
    ----------
    cache_dir:
        Directorio devuelto por ``_resolve_cache_dir(app, asset.uuid)``.
    stem:
        ``source_path.stem`` — el UUID del archivo almacenado (igual a
        ``asset.uuid`` cuando fue escrito por ``allocate_storage_path``).
    """
    return cache_dir / f"{stem}__rgb_preproc_linear.npy"


def load_linear_rgb_npy(npy_path: Path) -> Optional[NDArray[np.float32]]:
    """Carga un cache NPY de RGB lineal mediante memoria compartida (mmap).

    Devuelve el array (forma ``(H, W, 3)``, dtype ``float32``) o ``None`` si el
    archivo no existe o está corrompido.

    El array devuelto es **de solo lectura** (``mmap_mode="r"``).  Recortarlo
    provoca page-faults proporcionales a la región solicitada — los consumidores
    deben recortar primero para minimizar la I/O.

    Parameters
    ----------
    npy_path:
        Ruta devuelta por :func:`npy_path_for`.
    """
    if not npy_path.exists():
        return None
    try:
        return np.load(npy_path, mmap_mode="r")
    except Exception:
        return None


def write_linear_rgb_npy(
    source_path: Path,
    cache_dir: Path,
    cfg: PreprocessConfig,
    progress_cb: Optional[Callable[[str, float, str], None]] = None,
) -> Optional[Path]:
    """Escribe el array RGB lineal a resolución completa en un archivo ``.npy``.

    .. warning::
        Esta función genera archivos de hasta 6–7 GB para GeoTIFFs grandes.
        Existe únicamente para migración y depuración.  Los pipelines nuevos
        deben usar ``compute_wb_factors_from_tif`` + ``read_tif_window_as_linear_rgb``.

    Algoritmo
    ---------
    Paso 1 (opcional)
        Escaneo por bloques para calcular los factores globales de balance de
        blancos (gray-world).
    Paso 2
        Re-lectura por bloques: aplica ``sRGB → lineal``, aplica WB, escribe
        directamente en un archivo ``.npy`` temporal mapeado en memoria.  Rename
        atómico al final garantiza que un write parcial nunca quede en disco.

    Parameters
    ----------
    source_path:
        Ruta absoluta al GeoTIFF fuente.
    cache_dir:
        Directorio donde se escribirá el ``.npy``.
    cfg:
        Controla ``apply_gray_world``, ``apply_shadow_mask`` y ``shadow_thr``.
    progress_cb:
        Callback opcional ``(state, progress_0_to_1, message) → None``.

    Returns
    -------
    Path
        Ruta al archivo ``.npy`` escrito, o ``None`` si la escritura falló.
    """

    def _emit(state: str, progress: float, message: str) -> None:
        if progress_cb:
            try:
                progress_cb(state, progress, message)
            except Exception:
                pass

    in_key = source_path.stem
    npy_path = npy_path_for(cache_dir, in_key)
    _npy_tmp = npy_path.with_name(npy_path.stem + "__tmp.npy")

    try:
        with rasterio.open(str(source_path)) as src:
            if src.count < 3:
                return None

            h, w = src.height, src.width
            block_size = 1024

            _emit("npy_prepare", 0.08, "Preparando escritura incremental")

            # Paso 1: estadísticas globales para gray-world.
            scale = np.ones(3, dtype=np.float32)
            if cfg.apply_gray_world:
                sums = np.zeros(3, dtype=np.float64)
                valid_count = 0
                for win in iter_windows(w, h, block_size):
                    data = src.read([1, 2, 3], window=win, masked=True).astype(
                        np.float32
                    )
                    maxv = _dtype_max(src.dtypes[0])
                    if maxv > 1.0:
                        data /= maxv
                    arr = np.moveaxis(np.ma.filled(data, np.nan), 0, -1).astype(
                        np.float32
                    )
                    mask = np.isnan(arr).any(axis=-1)
                    arr[mask] = 0.0
                    arr = srgb_to_linear(arr)
                    valid = ~mask
                    if np.any(valid):
                        sums += arr[valid].sum(axis=0)
                        valid_count += int(valid.sum())
                if valid_count > 0:
                    means = (sums / valid_count).astype(np.float32)
                    denom = np.where(means <= 1e-8, 1e-8, means)
                    scale = np.float32(means.mean()) / denom
                _emit("npy_prepare", 0.12, "Balance de blancos calculado")

            # Paso 2: escribe bloques directos al NPY temporal.
            mm = np.lib.format.open_memmap(
                _npy_tmp, mode="w+", dtype=np.float32, shape=(h, w, 3)
            )
            windows = list(iter_windows(w, h, block_size))
            total_windows = max(1, len(windows))
            for idx, win in enumerate(windows, start=1):
                data = src.read([1, 2, 3], window=win, masked=True).astype(np.float32)
                maxv = _dtype_max(src.dtypes[0])
                if maxv > 1.0:
                    data /= maxv
                arr = np.moveaxis(np.ma.filled(data, np.nan), 0, -1).astype(np.float32)
                mask = np.isnan(arr).any(axis=-1)
                arr[mask] = 0.0
                arr = srgb_to_linear(arr)
                if cfg.apply_gray_world:
                    arr = np.clip(arr * scale, 0.0, 1.0).astype(np.float32)
                if cfg.apply_shadow_mask:
                    dark = (arr[..., 0] + arr[..., 1] + arr[..., 2]) < cfg.shadow_thr
                    arr[dark] = np.nan
                arr[mask] = np.nan
                y0_b = int(win.row_off)
                y1_b = int(win.row_off + win.height)
                x0_b = int(win.col_off)
                x1_b = int(win.col_off + win.width)
                mm[y0_b:y1_b, x0_b:x1_b, :] = arr
                if idx % max(1, total_windows // 20) == 0 or idx == total_windows:
                    prog = 0.12 + (0.70 * (idx / total_windows))
                    _emit(
                        "npy_writing", min(prog, 0.82), f"Bloque {idx}/{total_windows}"
                    )

            mm.flush()
            del mm
            os.replace(_npy_tmp, npy_path)
            _emit("npy_done", 0.84, "Cache NPY completado")
            return npy_path

    except Exception:
        try:
            _npy_tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return None
