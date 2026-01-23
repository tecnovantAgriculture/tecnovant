import io
import os
import shutil
import tempfile
import unittest

from flask import Flask
from werkzeug.datastructures import FileStorage

from app.modules.media.helpers import capture_upload_to_temp


class CaptureUploadToTempTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="media-test-")
        self.app = Flask(__name__)
        self.app.config.update(
            MEDIA_STORAGE_DIR=os.path.join(self.temp_dir, "storage"),
            MEDIA_UPLOAD_TMP_DIR=os.path.join(self.temp_dir, "tmp"),
            MEDIA_UPLOAD_CHUNK_SIZE=1024 * 1024,  # 1 MiB chunks force multiple iterations
        )
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_capture_streams_large_payload_without_truncation(self):
        payload = os.urandom(3 * 1024 * 1024 + 123)  # >3 MiB
        file = FileStorage(stream=io.BytesIO(payload), filename="sample.bin")

        capture = capture_upload_to_temp(file)

        self.assertEqual(capture.size_bytes, len(payload))
        with open(capture.temp_path, "rb") as fh:
            self.assertEqual(fh.read(), payload)

        capture.discard()


if __name__ == "__main__":
    unittest.main()
