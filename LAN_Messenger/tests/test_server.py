import asyncio
import queue
import sqlite3
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path

from protocol import read_message, write_message
from server import ChatServer, ServerGUI


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "test.db"
        self.server = ChatServer("127.0.0.1", 0, database_path)
        await self.server.start()
        self.database_path = database_path
        self.clients = []

    async def asyncTearDown(self):
        await self.server.close()
        for writer in self.clients:
            writer.close()
        if self.clients:
            await asyncio.gather(
                *(writer.wait_closed() for writer in self.clients),
                return_exceptions=True,
            )
        self.temp_dir.cleanup()

    async def connect(self, username):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.port)
        self.clients.append(writer)
        await write_message(writer, {"type": "login", "username": username})
        messages = []
        while not any(item.get("type") == "user_list" for item in messages):
            messages.append(await asyncio.wait_for(read_message(reader), timeout=2))
        self.assertTrue(any(item.get("type") == "login_success" for item in messages))
        return reader, writer, messages

    async def next_type(self, reader, message_type):
        for _ in range(10):
            item = await asyncio.wait_for(read_message(reader), timeout=2)
            if item.get("type") == message_type:
                return item
        self.fail(f"Did not receive message type {message_type!r}")

    async def test_three_clients_broadcast_private_and_database_persistence(self):
        ali_reader, ali_writer, _ = await self.connect("Ali")
        vali_reader, _, _ = await self.connect("Vali")
        salima_reader, _, _ = await self.connect("Salima")

        await write_message(ali_writer, {"type": "broadcast", "message": "Assalomu alaykum!"})
        self.assertEqual((await self.next_type(ali_reader, "broadcast"))["message"], "Assalomu alaykum!")
        self.assertEqual((await self.next_type(vali_reader, "broadcast"))["sender"], "Ali")
        self.assertEqual((await self.next_type(salima_reader, "broadcast"))["message"], "Assalomu alaykum!")

        await write_message(
            ali_writer,
            {
                "type": "private_message",
                "receiver": "Vali",
                "sender": "SoxtaYuboruvchi",
                "message": "Faqat Vali ko‘radi",
            },
        )
        private_to_ali = await self.next_type(ali_reader, "private_message")
        private_to_vali = await self.next_type(vali_reader, "private_message")
        self.assertEqual(private_to_ali["sender"], "Ali")
        self.assertEqual(private_to_vali["message"], "Faqat Vali ko‘radi")
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(read_message(salima_reader), timeout=0.15)

        connection = sqlite3.connect(self.database_path)
        try:
            rows = connection.execute(
                "SELECT sender, receiver, message, message_type FROM messages ORDER BY id"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(
            rows,
            [
                ("Ali", None, "Assalomu alaykum!", "broadcast"),
                ("Ali", "Vali", "Faqat Vali ko‘radi", "private_message"),
            ],
        )

    async def test_duplicate_username_is_rejected(self):
        await self.connect("Ali")
        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.port)
        self.clients.append(writer)
        await write_message(writer, {"type": "login", "username": "ali"})
        response = await asyncio.wait_for(read_message(reader), timeout=2)
        self.assertEqual(response["type"], "error")
        self.assertIn("already online", response["message"])

    async def test_unexpected_disconnect_does_not_stop_server(self):
        _, writer, _ = await self.connect("Ali")
        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.05)
        reader, _, _ = await self.connect("Vali")
        self.assertEqual(self.server.clients.keys(), {"Vali"})
        self.assertIsNotNone(reader)

    async def test_user_change_callback_tracks_online_clients(self):
        changes = []
        self.server.on_clients_changed = changes.append
        await self.connect("Ali")
        self.assertIn(["Ali"], changes)

    async def test_malformed_json_does_not_stop_server(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.server.port)
        self.clients.append(writer)
        payload = b"{not json"
        writer.write(struct.pack("!I", len(payload)) + payload)
        await writer.drain()
        response = await asyncio.wait_for(read_message(reader), timeout=2)
        self.assertEqual(response["type"], "error")

        next_reader, _, _ = await self.connect("Vali")
        self.assertIsNotNone(next_reader)

    async def test_message_history_survives_server_restart(self):
        reader, writer, _ = await self.connect("Ali")
        await write_message(writer, {"type": "broadcast", "message": "Saqlanadigan xabar"})
        await self.next_type(reader, "broadcast")

        await self.server.close()
        self.server = ChatServer("127.0.0.1", 0, self.database_path)
        await self.server.start()
        _, _, login_messages = await self.connect("Vali")
        history = next(item for item in login_messages if item.get("type") == "history")
        self.assertEqual(history["messages"][0]["message"], "Saqlanadigan xabar")

    async def test_ten_clients_can_be_online_together(self):
        sessions = await asyncio.gather(
            *(self.connect(f"User{index}") for index in range(10))
        )
        self.assertEqual(len(self.server.clients), 10)
        self.assertEqual(len(sessions), 10)


class ServerGUIThreadTests(unittest.TestCase):
    def test_gui_server_worker_starts_and_stops_cleanly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            gui = ServerGUI.__new__(ServerGUI)
            gui.events = queue.Queue()
            gui.stop_requested = threading.Event()
            worker = threading.Thread(
                target=gui._server_thread,
                args=("127.0.0.1", 0, Path(temp_dir) / "gui-test.db"),
                daemon=True,
            )
            worker.start()
            started = False
            deadline = time.monotonic() + 5
            try:
                while time.monotonic() < deadline:
                    try:
                        event, _ = gui.events.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if event == "started":
                        started = True
                        break
                    if event == "server_error":
                        self.fail("GUI server worker failed to start.")
                self.assertTrue(started, "GUI server worker did not report startup.")
            finally:
                gui.stop_requested.set()
                worker.join(timeout=5)

            self.assertFalse(worker.is_alive(), "GUI server worker did not stop.")


if __name__ == "__main__":
    unittest.main()
