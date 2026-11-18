"""Asyncio TCP server for the LAN messenger."""

import argparse
import asyncio
import logging
import queue
import re
import threading
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

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
LOGGER.setLevel(logging.INFO)
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
        self.on_clients_changed: Callable[[list[str]], None] | None = None

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
        if self.on_clients_changed is not None:
            self.on_clients_changed(usernames)
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


class _QueueLogHandler(logging.Handler):
    def __init__(self, events: queue.Queue[tuple[str, Any]]) -> None:
        super().__init__()
        self.events = events

    def emit(self, record: logging.LogRecord) -> None:
        self.events.put(("log", self.format(record)))


class ServerGUI:
    """Tkinter controls for starting and monitoring the asyncio server."""

    def __init__(
        self,
        root: tk.Tk,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        database_path: Path = Path(__file__).with_name("messenger.db"),
    ) -> None:
        self.root = root
        self.root.title("LAN Messenger — Server")
        self.root.geometry("820x600")
        self.root.minsize(680, 460)
        self.root.configure(bg="#f3f5f9")

        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.stop_requested = threading.Event()
        self.worker: threading.Thread | None = None
        self.closing = False

        self._build_ui(host, port, database_path)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._process_events)

    def _build_ui(self, host: str, port: int, database_path: Path) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f3f5f9")
        style.configure("TLabel", background="#f3f5f9", foreground="#172033")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("TButton", padding=(10, 6))

        header = ttk.Frame(self.root, padding=(18, 14))
        header.pack(fill="x")
        ttk.Label(header, text="LAN Messenger Server", style="Title.TLabel").pack(
            side="left"
        )
        self.status_label = ttk.Label(header, text="To‘xtatilgan")
        self.status_label.pack(side="right")

        settings = ttk.LabelFrame(self.root, text="Server sozlamalari", padding=10)
        settings.pack(fill="x", padx=18, pady=(0, 12))
        self.host_var = tk.StringVar(value=host)
        self.port_var = tk.StringVar(value=str(port))
        self.database_var = tk.StringVar(value=str(database_path))

        ttk.Label(settings, text="Bind IP").grid(row=0, column=0, sticky="w")
        ttk.Entry(settings, textvariable=self.host_var, width=20).grid(
            row=0, column=1, padx=(6, 14), sticky="ew"
        )
        ttk.Label(settings, text="Port").grid(row=0, column=2, sticky="w")
        ttk.Entry(settings, textvariable=self.port_var, width=8).grid(
            row=0, column=3, padx=(6, 14)
        )
        ttk.Label(settings, text="SQLite baza").grid(row=0, column=4, sticky="w")
        ttk.Entry(settings, textvariable=self.database_var).grid(
            row=0, column=5, padx=6, sticky="ew"
        )
        self.start_button = ttk.Button(
            settings, text="Serverni ishga tushirish", command=self._start_server
        )
        self.start_button.grid(row=0, column=6, padx=(8, 0))
        self.stop_button = ttk.Button(
            settings,
            text="To‘xtatish",
            command=self._stop_server,
            state="disabled",
        )
        self.stop_button.grid(row=0, column=7, padx=(6, 0))
        settings.columnconfigure(5, weight=1)

        body = ttk.Frame(self.root, padding=(18, 0, 18, 16))
        body.pack(fill="both", expand=True)
        users_frame = ttk.LabelFrame(body, text="Onlayn foydalanuvchilar", padding=8)
        users_frame.pack(side="left", fill="y")
        self.user_list = tk.Listbox(
            users_frame,
            width=24,
            relief="flat",
            activestyle="none",
            font=("Segoe UI", 10),
        )
        self.user_list.pack(fill="both", expand=True)

        log_frame = ttk.LabelFrame(body, text="Server logi", padding=8)
        log_frame.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.log_view = tk.Text(
            log_frame,
            state="disabled",
            wrap="word",
            font=("Consolas", 9),
            bg="white",
            fg="#172033",
            relief="flat",
            padx=10,
            pady=8,
        )
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_view.yview)
        self.log_view.configure(yscrollcommand=scrollbar.set)
        self.log_view.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _start_server(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return
        host = self.host_var.get().strip()
        database_path = self.database_var.get().strip()
        try:
            port = int(self.port_var.get())
        except ValueError:
            messagebox.showerror("Noto‘g‘ri port", "Port butun son bo‘lishi kerak.")
            return
        if not host or not database_path or not 1 <= port <= 65535:
            messagebox.showerror(
                "Noto‘g‘ri sozlama", "Bind IP, port va baza yo‘lini tekshiring."
            )
            return

        self.stop_requested.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_label.configure(text="Ishga tushmoqda…")
        self.worker = threading.Thread(
            target=self._server_thread,
            args=(host, port, Path(database_path)),
            name="lan-messenger-server",
            daemon=True,
        )
        self.worker.start()

    def _server_thread(self, host: str, port: int, database_path: Path) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        log_handler = _QueueLogHandler(self.events)
        log_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
        )
        LOGGER.addHandler(log_handler)

        async def run() -> None:
            server = ChatServer(host, port, database_path)
            server.on_clients_changed = lambda users: self.events.put(
                ("users", users)
            )
            try:
                await server.start()
                self.events.put(("started", f"{host}:{server.port}"))
                while not self.stop_requested.is_set():
                    await asyncio.sleep(0.1)
            finally:
                await server.close()

        try:
            loop.run_until_complete(run())
        except Exception as exc:
            self.events.put(("server_error", str(exc)))
            LOGGER.exception("Server could not start or stopped unexpectedly.")
        finally:
            LOGGER.removeHandler(log_handler)
            log_handler.close()
            loop.close()
            self.events.put(("stopped", None))

    def _stop_server(self) -> None:
        if self.worker is None or not self.worker.is_alive():
            return
        self.stop_requested.set()
        self.stop_button.configure(state="disabled")
        self.status_label.configure(text="To‘xtatilmoqda…")

    def _process_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "log":
                    self._append_log(payload)
                elif event == "started":
                    self.status_label.configure(text=f"Ishlayapti: {payload}")
                    self._append_log(f"Server tinglamoqda: {payload}")
                elif event == "users":
                    self.user_list.delete(0, tk.END)
                    for username in payload:
                        self.user_list.insert(tk.END, username)
                elif event == "server_error":
                    self.status_label.configure(text="Server xatosi")
                    self._append_log(f"XATOLIK: {payload}")
                    messagebox.showerror("Server xatosi", str(payload))
                elif event == "stopped":
                    self.status_label.configure(text="To‘xtatilgan")
                    self.start_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.user_list.delete(0, tk.END)
                    if self.closing:
                        self.root.destroy()
        except queue.Empty:
            pass
        if not self.closing:
            self.root.after(100, self._process_events)

    def _append_log(self, text: str) -> None:
        self.log_view.configure(state="normal")
        self.log_view.insert(tk.END, f"{text}\n")
        self.log_view.configure(state="disabled")
        self.log_view.see(tk.END)

    def _on_close(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.closing = True
            self._stop_server()
            self.root.after(100, self._wait_for_shutdown)
        else:
            self.root.destroy()

    def _wait_for_shutdown(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.root.after(100, self._wait_for_shutdown)
        else:
            self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="LAN Messenger async server")
    parser.add_argument(
        "--console",
        action="store_true",
        help="Run the server in console mode instead of opening the GUI",
    )
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
    if args.console:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        try:
            asyncio.run(_run_server(args.host, args.port, args.db))
        except KeyboardInterrupt:
            LOGGER.info("Shutdown requested.")
    else:
        root = tk.Tk()
        ServerGUI(root, args.host, args.port, args.db)
        root.mainloop()


if __name__ == "__main__":
    main()
