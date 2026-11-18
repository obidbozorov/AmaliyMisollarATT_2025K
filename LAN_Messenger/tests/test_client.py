import asyncio
import unittest

from client import _describe_connection_error


class ConnectionErrorMessageTests(unittest.TestCase):
    def test_refused_connection_includes_setup_checks(self):
        error = OSError(1225, "connection refused")
        message = _describe_connection_error("192.168.1.100", 5000, error)

        self.assertIn("192.168.1.100:5000", message)
        self.assertIn("server.py", message)
        self.assertIn("Firewall", message)

    def test_timeout_suggests_network_checks(self):
        message = _describe_connection_error(
            "192.168.1.100", 5000, asyncio.TimeoutError()
        )

        self.assertIn("192.168.1.100:5000", message)
        self.assertIn("LAN/Wi-Fi", message)


if __name__ == "__main__":
    unittest.main()
