"""Проверки доступа к админке: доверяем только loopback и токену."""
import unittest
from unittest import mock

import app


def make_handler(client_ip, headers=None):
    h = object.__new__(app.AdvisorHTTPHandler)
    h.client_address = (client_ip, 12345)
    h.headers = headers or {}
    return h


class AdminAccessTest(unittest.TestCase):
    def test_loopback_allowed_without_token(self):
        with mock.patch.object(app, "ADMIN_TOKEN", ""), mock.patch.object(app, "TRUST_PROXY", False):
            self.assertTrue(make_handler("127.0.0.1")._admin_ok())

    def test_private_lan_is_not_trusted(self):
        with mock.patch.object(app, "ADMIN_TOKEN", ""), mock.patch.object(app, "TRUST_PROXY", False):
            self.assertFalse(make_handler("192.168.1.10")._admin_ok())
            self.assertFalse(make_handler("10.0.0.5")._admin_ok())

    def test_token_allows_remote(self):
        h = make_handler("192.168.1.10", {"X-Admin-Token": "secret"})
        with mock.patch.object(app, "ADMIN_TOKEN", "secret"), mock.patch.object(app, "TRUST_PROXY", False):
            self.assertTrue(h._admin_ok())
        h.headers = {"X-Admin-Token": "wrong"}
        with mock.patch.object(app, "ADMIN_TOKEN", "secret"), mock.patch.object(app, "TRUST_PROXY", False):
            self.assertFalse(h._admin_ok())

    def test_direct_client_cannot_spoof_forwarded_for(self):
        # TRUST_PROXY=1, но запрос пришёл не от локального прокси: X-Forwarded-For игнорируется
        h = make_handler("203.0.113.5", {"X-Forwarded-For": "127.0.0.1"})
        with mock.patch.object(app, "ADMIN_TOKEN", ""), mock.patch.object(app, "TRUST_PROXY", True):
            self.assertEqual(h._ip(), "203.0.113.5")
            self.assertFalse(h._admin_ok())

    def test_proxy_passes_real_client_ip(self):
        h = make_handler("127.0.0.1", {"X-Forwarded-For": "203.0.113.5"})
        with mock.patch.object(app, "ADMIN_TOKEN", ""), mock.patch.object(app, "TRUST_PROXY", True):
            self.assertEqual(h._ip(), "203.0.113.5")
            self.assertFalse(h._admin_ok())


if __name__ == "__main__":
    unittest.main()
