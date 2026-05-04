from __future__ import annotations

import numpy as np
import rasterio


def load_rgb_from_bytes(data: bytes):
    with rasterio.MemoryFile(data) as mem:
        with mem.open() as src:
            red = src.read(1)
            green = src.read(2)
            blue = src.read(3)
            nodata = src.nodata
    return red, green, blue, nodata


def mask_and_normalize_uint8(red, green, blue, nodata):
    if nodata is not None:
        red = np.ma.masked_equal(red, nodata)
        green = np.ma.masked_equal(green, nodata)
        blue = np.ma.masked_equal(blue, nodata)
    red = red.astype("float32") / 255.0
    green = green.astype("float32") / 255.0
    blue = blue.astype("float32") / 255.0
    return red, green, blue


def compute_vari(green, red, blue):
    eps = 1e-6
    denom = green + red - blue
    safe_denom = denom + eps
    with np.errstate(divide="ignore", invalid="ignore"):
        vari = (green - red) / safe_denom
    vari = np.ma.masked_where(~np.isfinite(vari) | (denom <= 0), vari)
    return vari.astype("float32")


def vari_to_protein_vector(vari):
    v = np.asarray(vari, dtype="float32")
    out = np.full(v.shape, np.nan, dtype="float32")
    out[v <= 0.0] = 0.0
    out[(v > 0.0) & (v <= 0.10)] = 3.0
    out[(v > 0.10) & (v <= 0.17)] = 6.0
    out[(v > 0.17) & (v <= 0.23)] = 9.0
    out[(v > 0.23) & (v <= 0.35)] = 12.0
    if np.ma.isMaskedArray(vari):
        out = np.ma.array(out, mask=vari.mask)
    return out
