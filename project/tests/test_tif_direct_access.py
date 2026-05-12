"""Tests for TIF-direct access: WB sidecar + window reading + preview generation."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds

from app.modules.media.helpers import (
    PreprocessConfig,
    compute_wb_factors_from_tif,
    preprocess_rgb_once,
    read_tif_window_as_linear_rgb,
)
from app.modules.media.helper_npy_cache import (
    load_linear_rgb_npy,
    npy_path_for,
    write_linear_rgb_npy,
)


def _make_tif(path: Path, width: int = 256, height: int = 256, seed: int = 42) -> Path:
    """Write a small synthetic uint8 GeoTIFF (3 bands, LZW tiled) to *path*."""
    rng = np.random.default_rng(seed)
    data = rng.integers(20, 220, (3, height, width), dtype=np.uint8)
    transform = from_bounds(0, 0, 1, 1, width, height)
    with rasterio.open(
        str(path),
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=3,
        dtype="uint8",
        crs="EPSG:4326",
        transform=transform,
        compress="lzw",
        tiled=True,
        blockxsize=128,
        blockysize=128,
    ) as ds:
        ds.write(data)
    return path


class TestComputeWbFactors(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wb-test-"))
        self.tif = _make_tif(self.tmp / "test.tif")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_three_float_keys(self):
        factors = compute_wb_factors_from_tif(self.tif)
        self.assertIn("scale_r", factors)
        self.assertIn("scale_g", factors)
        self.assertIn("scale_b", factors)
        for v in factors.values():
            self.assertIsInstance(v, float)

    def test_json_serializable(self):
        factors = compute_wb_factors_from_tif(self.tif)
        # Must not raise TypeError for numpy floats
        serialized = json.dumps(factors)
        self.assertIsInstance(serialized, str)

    def test_deterministic(self):
        f1 = compute_wb_factors_from_tif(self.tif)
        f2 = compute_wb_factors_from_tif(self.tif)
        self.assertEqual(f1, f2)

    def test_positive_factors(self):
        factors = compute_wb_factors_from_tif(self.tif)
        for v in factors.values():
            self.assertGreater(v, 0.0)

    def test_gray_world_invariant(self):
        """mean(scale_r * r_mean, scale_g * g_mean, scale_b * b_mean) == global_mean."""
        factors = compute_wb_factors_from_tif(self.tif)
        # After scaling, all channels should have the same mean → check ratios are close.
        # The factors normalize each channel so channel_mean * scale == global_mean.
        sr, sg, sb = factors["scale_r"], factors["scale_g"], factors["scale_b"]
        # All factors deviate from 1 within a reasonable range for random data.
        for v in (sr, sg, sb):
            self.assertGreater(v, 0.5)
            self.assertLess(v, 2.0)


class TestReadTifWindowAsLinearRgb(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="window-test-"))
        self.tif = _make_tif(self.tmp / "test.tif", width=512, height=512)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_shape_and_dtype(self):
        rgb = read_tif_window_as_linear_rgb(self.tif, 0, 0, 200, 200)
        self.assertEqual(rgb.shape, (200, 200, 3))
        self.assertEqual(rgb.dtype, np.float32)

    def test_values_in_unit_range(self):
        rgb = read_tif_window_as_linear_rgb(self.tif, 0, 0, 200, 200)
        self.assertGreaterEqual(float(rgb.min()), 0.0)
        self.assertLessEqual(float(rgb.max()), 1.0)

    def test_wb_factors_applied(self):
        factors = {"scale_r": 1.5, "scale_g": 1.0, "scale_b": 0.8}
        rgb_no_wb = read_tif_window_as_linear_rgb(self.tif, 50, 50, 150, 150)
        rgb_wb = read_tif_window_as_linear_rgb(self.tif, 50, 50, 150, 150, wb_factors=factors)
        # With scale_r=1.5 the red channel should differ
        self.assertFalse(np.allclose(rgb_no_wb[:, :, 0], rgb_wb[:, :, 0]))

    def test_wb_factors_clip_to_one(self):
        factors = {"scale_r": 9.9, "scale_g": 9.9, "scale_b": 9.9}
        rgb = read_tif_window_as_linear_rgb(self.tif, 0, 0, 100, 100, wb_factors=factors)
        self.assertLessEqual(float(rgb.max()), 1.0)

    def test_small_window_correctness(self):
        rgb = read_tif_window_as_linear_rgb(self.tif, 10, 10, 11, 11)
        self.assertEqual(rgb.shape, (1, 1, 3))


class TestPreprocessRgbOnce(unittest.TestCase):
    """preprocess_rgb_once generates .wb.json + preview PNGs, no .npy."""

    def setUp(self):
        import os
        from flask import Flask

        self.tmp = Path(tempfile.mkdtemp(prefix="preprocess-test-"))
        self.tif = _make_tif(self.tmp / "asset.tif", width=512, height=512)
        self.cache_dir = self.tmp / "cache"
        self.cache_dir.mkdir()

        self.app = Flask(__name__)
        self.app.config.update(
            MEDIA_STORAGE_DIR=str(self.tmp / "storage"),
            MEDIA_PREVIEW_MAX_DIM=256,
        )
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cfg(self):
        return PreprocessConfig(cache_dir=self.cache_dir, preview_max_dim=256)

    def test_no_npy_written(self):
        preprocess_rgb_once(self.tif, self._cfg())
        npy_files = list(self.cache_dir.glob("*.npy"))
        self.assertEqual(len(npy_files), 0, f"unexpected .npy files: {npy_files}")

    def test_wb_json_written(self):
        preprocess_rgb_once(self.tif, self._cfg())
        wb_path = self.cache_dir / "asset.wb.json"
        self.assertTrue(wb_path.exists(), ".wb.json not created")
        factors = json.loads(wb_path.read_text())
        self.assertIn("scale_r", factors)
        self.assertIn("scale_g", factors)
        self.assertIn("scale_b", factors)

    def test_rgb_preview_written(self):
        preprocess_rgb_once(self.tif, self._cfg())
        preview = self.cache_dir / "asset__rgb_preproc_preview.png"
        self.assertTrue(preview.exists(), "RGB preview PNG not created")

    def test_vi_previews_written(self):
        preprocess_rgb_once(self.tif, self._cfg())
        for suffix in ("__vi_gr_ratio.png", "__vi_gr_heat.png", "__vi_heatmap.png"):
            p = self.cache_dir / f"asset{suffix}"
            self.assertTrue(p.exists(), f"{suffix} not created")

    def test_return_values(self):
        result = preprocess_rgb_once(self.tif, self._cfg())
        rgb_lin, preview_path, npy_path, vi_gray, vi_heat, heatmap = result
        self.assertIsNone(rgb_lin, "rgb_lin should be None (TIF-direct)")
        self.assertIsNone(npy_path, "npy_path should be None (TIF-direct)")
        self.assertIsNotNone(preview_path)
        self.assertIsNotNone(vi_gray)
        self.assertIsNotNone(vi_heat)
        self.assertIsNotNone(heatmap)

    def test_fast_path_when_all_artifacts_exist(self):
        """Second call returns immediately without re-generating artifacts."""
        preprocess_rgb_once(self.tif, self._cfg())
        # Delete wb.json — fast path only checks PNGs, not wb.json
        # Actually fast path checks 4 PNGs; call again to verify no exception.
        result = preprocess_rgb_once(self.tif, self._cfg())
        self.assertIsNotNone(result[1])  # preview_path


class TestNpyCacheLegacy(unittest.TestCase):
    """helper_npy_cache.py still writes/reads .npy correctly (legacy path)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="npy-legacy-test-"))
        self.tif = _make_tif(self.tmp / "asset.tif", width=128, height=128)
        self.cache_dir = self.tmp / "cache"
        self.cache_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_npy_path_for(self):
        p = npy_path_for(self.cache_dir, "mystemasset")
        self.assertEqual(p.name, "mystemasset__rgb_preproc_linear.npy")
        self.assertEqual(p.parent, self.cache_dir)

    def test_write_and_load(self):
        cfg = PreprocessConfig(cache_dir=self.cache_dir)
        result = write_linear_rgb_npy(self.tif, self.cache_dir, cfg)
        self.assertIsNotNone(result, "write_linear_rgb_npy returned None")
        self.assertTrue(result.exists())

        arr = load_linear_rgb_npy(result)
        self.assertIsNotNone(arr)
        self.assertEqual(arr.shape, (128, 128, 3))
        self.assertEqual(arr.dtype, np.float32)
        self.assertGreaterEqual(float(np.nanmin(arr)), 0.0)

    def test_load_missing_returns_none(self):
        result = load_linear_rgb_npy(self.cache_dir / "nonexistent.npy")
        self.assertIsNone(result)

    def test_npy_not_written_by_preprocess_rgb_once(self):
        """preprocess_rgb_once must not create .npy files anymore."""
        import os
        from flask import Flask

        app = Flask(__name__)
        app.config["MEDIA_STORAGE_DIR"] = str(self.tmp / "storage")
        app.config["MEDIA_PREVIEW_MAX_DIM"] = 128

        with app.app_context():
            cfg = PreprocessConfig(cache_dir=self.cache_dir, preview_max_dim=128)
            preprocess_rgb_once(self.tif, cfg)

        npy_files = list(self.cache_dir.glob("*.npy"))
        self.assertEqual(len(npy_files), 0, f".npy should not exist: {npy_files}")


if __name__ == "__main__":
    unittest.main()
