import asyncio
import unittest

from client import MessengerClient, _describe_connection_error


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

    def test_incoming_private_message_routes_to_its_separate_chat(self):
        client = MessengerClient.__new__(MessengerClient)
        client.username = "Vali"
        client.private_histories = {}
        client.private_windows = {}
        opened_chats = []
        client._open_private_chat = opened_chats.append
        client._append = lambda *_args, **_kwargs: self.fail(
            "Private messages must not appear in the public chat."
        )
        message = {
            "id": 42,
            "type": "private_message",
            "sender": "Ali",
            "receiver": "Vali",
            "message": "Salom",
        }

        client._display_chat_message(message)
        client._display_chat_message(message)

        self.assertEqual(opened_chats, ["Ali"])
        self.assertEqual(client.private_histories["Ali"], [message])


if __name__ == "__main__":
    unittest.main()
