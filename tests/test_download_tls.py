"""Регрессия: прайс-листы скачиваются только с проверкой TLS-сертификата."""
import os
import ssl
import tempfile
import unittest
from unittest import mock

import build_catalog


class DownloadTlsTest(unittest.TestCase):
    def test_download_uses_verified_context(self):
        seen = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b"x" * 2000

        def fake_urlopen(req, context=None, timeout=None):
            seen["ctx"] = context
            return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp, mock.patch("urllib.request.urlopen", fake_urlopen):
            ok, msg = build_catalog.download_price_file(os.path.join(tmp, "price.xlsx"), "https://example.com/price.xlsx")
            self.assertTrue(ok, msg)
        ctx = seen.get("ctx")
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)


if __name__ == "__main__":
    unittest.main()
