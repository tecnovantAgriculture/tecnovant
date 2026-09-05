"""Generated previews must use their own storage, not their parent's storage."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from app.modules.media import web_routes


class MediaStorageRedirectTest(unittest.TestCase):
    def setUp(self):
        self.context = Flask(__name__).test_request_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        self.asset = SimpleNamespace(
            storage_key="originals/ortho.tif", storage="gcs", variants=[]
        )
        for name, value in (
            ("accessible_asset_for_storage_key", self.asset),
            ("gcs_enabled", True),
        ):
            patcher = patch.object(web_routes, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(
            web_routes, "public_or_signed_url",
            side_effect=lambda key: "https://storage.example/" + key,
        )
        self.sign_url = patcher.start()
        self.addCleanup(patcher.stop)

    def test_cloud_original_redirects(self):
        response = web_routes._cloud_storage_redirect_for_key(self.asset.storage_key)
        self.assertEqual(response.status_code, 302)

    def test_analysis_preview_of_cloud_asset_stays_local(self):
        response = web_routes._cloud_storage_redirect_for_key("cache/uuid/nd_index.png")
        self.assertIsNone(response)
        self.sign_url.assert_not_called()

    def test_display_preview_still_redirects(self):
        response = web_routes._cloud_storage_redirect_for_key("display/uuid/display.png")
        self.assertEqual(response.status_code, 302)

    def test_local_variant_of_cloud_asset_stays_local(self):
        self.asset.variants = [SimpleNamespace(storage_key="thumb.webp", storage="local")]
        self.assertIsNone(web_routes._cloud_storage_redirect_for_key("thumb.webp"))
        self.sign_url.assert_not_called()

    def test_cloud_variant_of_local_asset_redirects(self):
        self.asset.storage = "local"
        self.asset.variants = [SimpleNamespace(storage_key="thumb.webp", storage="gcs")]
        self.assertEqual(web_routes._cloud_storage_redirect_for_key("thumb.webp").status_code, 302)

    def test_inaccessible_asset_does_not_redirect(self):
        with patch.object(web_routes, "accessible_asset_for_storage_key", return_value=None):
            self.assertIsNone(web_routes._cloud_storage_redirect_for_key("display/uuid/display.png"))
        self.sign_url.assert_not_called()
