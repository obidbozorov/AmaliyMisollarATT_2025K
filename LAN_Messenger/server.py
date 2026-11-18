"""Asyncio TCP server for the LAN messenger."""

import argparse
import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    MAX_CLIENTS,
    MAX_MESSAGE_LENGTH,
    MAX_USERNAME_LENGTH,
)
from database import MessengerDatabase, utc_timestamp
from protocol import ProtocolError, read_message, write_message

LOGGER = logging.getLogger("lan_messenger.server")
USERNAME_PATTERN = re.compile(r"^[^\s\x00-\x1f\x7f]+$")


@dataclass
class ClientConnection:
    username: str
    writer: asyncio.StreamWriter


class ChatServer:
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        database_path: str | Path = Path(__file__).with_name("messenger.db"),
    ) -> None:
        self.host = host
        self.port = port
        self.database = MessengerDatabase(database_path)
        self.clients: dict[str, ClientConnection] = {}
        self._clients_lock = asyncio.Lock()
        self._handler_tasks: set[asyncio.Task[Any]] = set()
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port, backlog=MAX_CLIENTS
        )
        sockets = self._server.sockets or []
        if sockets:
            self.port = int(sockets[0].getsockname()[1])
        LOGGER.info("Server listening on %s:%s", self.host, self.port)

    async def serve_forever(self) -> None:
        if self._server is None:
            raise RuntimeError("Call start() before serve_forever().")
        async with self._server:
            await self._server.serve_forever()

    async def close(self) -> None:
        server = self._server
        if server is not None:
            server.close()
            self._server = None

        async with self._clients_lock:
            connections = list(self.clients.values())
            self.clients.clear()
        for connection in connections:
            connection.writer.close()
        if connections:
            await asyncio.gather(
                *(connection.writer.wait_closed() for connection in connections),
                return_exceptions=True,
            )
        current_task = asyncio.current_task()
        handlers = [
            task for task in self._handler_tasks if task is not current_task
        ]
        if handlers:
            _, pending = await asyncio.wait(handlers, timeout=2)
            if pending:
                LOGGER.warning("Cancelling %d client handler(s) during shutdown.", len(pending))
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        if server is not None:
            await server.wait_closed()
        self.database.close()
        LOGGER.info("Server stopped.")

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._handler_tasks.add(task)
        peer = writer.get_extra_info("peername")
        username: str | None = None
        try:
            login = await read_message(reader)
            if login.get("type") != "login":
                await self._send_error(writer, "The first message must be login.")
                return
            requested_username = login.get("username")
            if not self._valid_username(requested_username):
                await self._send_error(
                    writer,
                    f"Username must be 1-{MAX_USERNAME_LENGTH} characters "
                    "without spaces or control characters.",
                )
                return
            username = requested_username

            async with self._clients_lock:
                if len(self.clients) >= MAX_CLIENTS:
                    await self._send_error(writer, "The server is full.")
                    return
                if any(name.casefold() == username.casefold() for name in self.clients):
                    await self._send_error(writer, "That username is already online.")
                    return
                self.clients[username] = ClientConnection(username, writer)
                self.database.user_connected(username)

            LOGGER.info("Client %s connected from %s", username, peer)
            await write_message(
                writer,
                {"type": "login_success", "username": username, "timestamp": utc_timestamp()},
            )
            await write_message(
                writer,
                {"type": "history", "messages": self.database.history_for(username)},
            )
            await self._broadcast_user_list()
            await self._broadcast_system(f"{username} chatga qo‘shildi.", exclude=username)

            while True:
                try:
                    request = await read_message(reader)
                except ProtocolError as exc:
                    await self._send_error(writer, str(exc))
                    break

                message_type = request.get("type")
                if message_type == "logout":
                    break
                if message_type == "broadcast":
                    await self._handle_broadcast(username, request)
                elif message_type == "private_message":
                    await self._handle_private_message(username, request)
                else:
                    await self._send_error(writer, "Unsupported message type.")

        except asyncio.IncompleteReadError:
            LOGGER.info("Client connection closed: %s", peer)
        except (ConnectionError, OSError) as exc:
            LOGGER.warning("Network error for %s: %s", peer, exc)
        except ProtocolError as exc:
            LOGGER.warning("Invalid protocol data from %s: %s", peer, exc)
            await self._send_error(writer, str(exc))
        except Exception:
            LOGGER.exception("Unexpected client handler error for %s", peer)
        finally:
            if username is not None:
                removed = False
                async with self._clients_lock:
                    current = self.clients.get(username)
                    if current is not None and current.writer is writer:
                        del self.clients[username]
                        self.database.user_disconnected(username)
                        removed = True
                if removed:
                    LOGGER.info("Client %s disconnected.", username)
                    await self._broadcast_user_list()
                    await self._broadcast_system(
                        f"{username} chatdan chiqdi.", exclude=username
                    )
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            if task is not None:
                self._handler_tasks.discard(task)

    @staticmethod
    def _valid_username(username: Any) -> bool:
        return (
            isinstance(username, str)
            and 1 <= len(username) <= MAX_USERNAME_LENGTH
            and USERNAME_PATTERN.fullmatch(username) is not None
        )

    async def _handle_broadcast(
        self, sender: str, request: dict[str, Any]
    ) -> None:
        text = request.get("message")
        if not self._valid_text(text):
            await self._send_error_to_user(sender, "Message is empty or too long.")
            return
        message = self.database.save_message(sender, None, text, "broadcast")
        await self._send_to_all(message)

    async def _handle_private_message(
        self, sender: str, request: dict[str, Any]
    ) -> None:
        receiver = request.get("receiver")
        text = request.get("message")
        if not self._valid_text(text):
            await self._send_error_to_user(sender, "Message is empty or too long.")
            return
        if not isinstance(receiver, str) or receiver == sender:
            await self._send_error_to_user(sender, "Choose another online user.")
            return

        async with self._clients_lock:
            target = next(
                (
                    client
                    for name, client in self.clients.items()
                    if name.casefold() == receiver.casefold()
                ),
                None,
            )
        if target is None:
            await self._send_error_to_user(sender, "That user is not online.")
            return

        message = self.database.save_message(
            sender, target.username, text, "private_message"
        )
        await self._send_to_user(sender, message)
        if target.username != sender:
            await self._send_to_user(target.username, message)

    @staticmethod
    def _valid_text(text: Any) -> bool:
        return (
            isinstance(text, str)
            and bool(text.strip())
            and len(text) <= MAX_MESSAGE_LENGTH
        )

    async def _send_error_to_user(self, username: str, text: str) -> None:
        await self._send_to_user(
            username, {"type": "error", "message": text, "timestamp": utc_timestamp()}
        )

    async def _send_error(self, writer: asyncio.StreamWriter, text: str) -> None:
        try:
            await write_message(
                writer, {"type": "error", "message": text, "timestamp": utc_timestamp()}
            )
        except (ConnectionError, OSError):
            LOGGER.debug("Could not send an error response to a disconnected peer.")

    async def _send_to_user(self, username: str, message: dict[str, Any]) -> None:
        async with self._clients_lock:
            client = self.clients.get(username)
        if client is None:
            return
        try:
            await write_message(client.writer, message)
        except (ConnectionError, OSError) as exc:
            LOGGER.warning("Could not deliver a message to %s: %s", username, exc)

    async def _send_to_all(
        self, message: dict[str, Any], exclude: str | None = None
    ) -> None:
        async with self._clients_lock:
            clients = [
                client
                for name, client in self.clients.items()
                if name != exclude
            ]
        if clients:
            results = await asyncio.gather(
                *(write_message(client.writer, message) for client in clients),
                return_exceptions=True,
            )
            for client, result in zip(clients, results):
                if isinstance(result, BaseException):
                    LOGGER.warning(
                        "Could not deliver a message to %s: %s",
                        client.username,
                        result,
                    )

    async def _broadcast_user_list(self) -> None:
        async with self._clients_lock:
            usernames = sorted(self.clients, key=str.casefold)
        await self._send_to_all(
            {"type": "user_list", "users": usernames, "timestamp": utc_timestamp()}
        )

    async def _broadcast_system(
        self, text: str, exclude: str | None = None
    ) -> None:
        await self._send_to_all(
            {"type": "system_message", "message": text, "timestamp": utc_timestamp()},
            exclude=exclude,
        )


async def _run_server(host: str, port: int, database_path: Path) -> None:
    server = ChatServer(host, port, database_path)
    try:
        await server.start()
        await server.serve_forever()
    finally:
        await server.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="LAN Messenger async server")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind address (default: all interfaces)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(__file__).with_name("messenger.db"),
        help="SQLite database path",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(_run_server(args.host, args.port, args.db))
    except KeyboardInterrupt:
        LOGGER.info("Shutdown requested.")


if __name__ == "__main__":
    main()
