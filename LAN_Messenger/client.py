"""Tkinter GUI client for the LAN messenger."""

import argparse
import asyncio
import errno
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from tkinter import messagebox, ttk
from typing import Any

from config import DEFAULT_PORT
from protocol import ProtocolError, read_message, write_message


def _describe_connection_error(host: str, port: int, error: OSError) -> str:
    """Translate common connection failures into actionable GUI guidance."""
    address = f"{host}:{port}"
    winerror = getattr(error, "winerror", None)
    if (
        isinstance(error, ConnectionRefusedError)
        or winerror in (10061, 1225)
        or error.errno in (errno.ECONNREFUSED, 10061, 1225)
    ):
        return (
            f"{address} manzilida server ulanishni rad etdi. Server kompyuterida "
            "server.py ishlayotganini, klientdagi IP/port to‘g‘riligini va "
            f"Windows Firewall’da TCP {port} portiga ruxsat borligini tekshiring. "
            f"Tafsilot: {error}"
        )
    if isinstance(error, asyncio.TimeoutError):
        return (
            f"{address} manzilidan javob kelmadi. IP-manzil, bir xil LAN/Wi-Fi "
            f"tarmog‘i va TCP {port} firewall qoidasini tekshiring."
        )
    return f"{address} serveriga ulanib bo‘lmadi: {error}"


@dataclass
class PrivateChatView:
    window: tk.Toplevel
    chat: tk.Text
    message_var: tk.StringVar
    send_button: ttk.Button


class MessengerClient:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("LAN Messenger")
        self.root.geometry("900x620")
        self.root.minsize(700, 480)
        self.root.configure(bg="#f3f5f9")

        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.outgoing: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.connected = False
        self.username = ""
        self.private_histories: dict[str, list[dict[str, Any]]] = {}
        self.private_windows: dict[str, PrivateChatView] = {}
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self._process_events)

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f3f5f9")
        style.configure("TLabel", background="#f3f5f9", foreground="#172033")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("TButton", padding=(10, 6))

        header = ttk.Frame(self.root, padding=(18, 14))
        header.pack(fill="x")
        ttk.Label(header, text="LAN Messenger", style="Title.TLabel").pack(side="left")
        self.status_label = ttk.Label(header, text="Ulanmagan")
        self.status_label.pack(side="right")

        connection = ttk.LabelFrame(self.root, text="Serverga ulanish", padding=10)
        connection.pack(fill="x", padx=18, pady=(0, 12))
        self.host_var = tk.StringVar(value="127.0.0.1")
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        self.username_var = tk.StringVar()
        ttk.Label(connection, text="Server IP").grid(row=0, column=0, sticky="w")
        ttk.Entry(connection, textvariable=self.host_var, width=20).grid(
            row=0, column=1, padx=(6, 14), sticky="ew"
        )
        ttk.Label(connection, text="Port").grid(row=0, column=2, sticky="w")
        ttk.Entry(connection, textvariable=self.port_var, width=8).grid(
            row=0, column=3, padx=(6, 14)
        )
        ttk.Label(connection, text="Foydalanuvchi").grid(row=0, column=4, sticky="w")
        self.username_entry = ttk.Entry(connection, textvariable=self.username_var, width=18)
        self.username_entry.grid(row=0, column=5, padx=6, sticky="ew")
        self.connect_button = ttk.Button(
            connection, text="Ulanish", command=self._connect
        )
        self.connect_button.grid(row=0, column=6, padx=(8, 0))
        self.disconnect_button = ttk.Button(
            connection, text="Uzish", command=self._disconnect, state="disabled"
        )
        self.disconnect_button.grid(row=0, column=7, padx=(6, 0))
        connection.columnconfigure(5, weight=1)

        content = ttk.Frame(self.root, padding=(18, 0, 18, 16))
        content.pack(fill="both", expand=True)
        chat_frame = ttk.Frame(content)
        chat_frame.pack(side="left", fill="both", expand=True)
        ttk.Label(chat_frame, text="Umumiy chat", font=("Segoe UI", 11, "bold")).pack(
            anchor="w", pady=(0, 6)
        )
        self.chat = tk.Text(
            chat_frame,
            state="disabled",
            wrap="word",
            font=("Segoe UI", 10),
            bg="white",
            fg="#172033",
            relief="flat",
            padx=14,
            pady=12,
        )
        scrollbar = ttk.Scrollbar(chat_frame, command=self.chat.yview)
        self.chat.configure(yscrollcommand=scrollbar.set)
        self.chat.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.chat.tag_configure("mine", justify="right", foreground="#175cd3")
        self.chat.tag_configure("other", justify="left", foreground="#172033")
        self.chat.tag_configure("system", justify="center", foreground="#667085")
        self.chat.tag_configure("error", justify="center", foreground="#b42318")

        sidebar = ttk.LabelFrame(content, text="Onlayn foydalanuvchilar", padding=8)
        sidebar.pack(side="right", fill="y", padx=(12, 0))
        self.user_list = tk.Listbox(
            sidebar,
            width=22,
            height=20,
            relief="flat",
            activestyle="none",
            exportselection=False,
            font=("Segoe UI", 10),
        )
        self.user_list.pack(fill="both", expand=True)
        self.user_list.insert(tk.END, "Hamma (umumiy chat)")
        self.user_list.selection_set(0)
        ttk.Label(
            sidebar,
            text="Foydalanuvchini ikki marta\nbosing yoki tugmani bosing.",
            justify="center",
        ).pack(pady=(8, 0))
        ttk.Button(
            sidebar,
            text="Shaxsiy chatni ochish",
            command=self._open_selected_private_chat,
        ).pack(fill="x", pady=(8, 0))
        self.user_list.bind("<Double-Button-1>", self._open_selected_private_chat)

        compose = ttk.Frame(self.root, padding=(18, 0, 18, 18))
        compose.pack(fill="x")
        ttk.Label(compose, text="Umumiy xabar").pack(side="left", padx=(0, 8))
        self.message_var = tk.StringVar()
        self.message_entry = ttk.Entry(compose, textvariable=self.message_var)
        self.message_entry.pack(side="left", fill="x", expand=True)
        self.message_entry.bind("<Return>", self._send_message)
        self.send_button = ttk.Button(
            compose, text="Yuborish", command=self._send_message, state="disabled"
        )
        self.send_button.pack(side="left", padx=(8, 0))

    def _connect(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return
        host = self.host_var.get().strip()
        username = self.username_var.get().strip()
        try:
            port = int(self.port_var.get())
        except ValueError:
            messagebox.showerror("Xatolik", "Port butun son bo‘lishi kerak.")
            return
        if not host or not 1 <= port <= 65535 or not username:
            messagebox.showerror("Xatolik", "Server IP, port va ismni to‘g‘ri kiriting.")
            return

        self.username = username
        self.outgoing = queue.Queue()
        self.stop_event = threading.Event()
        self.connected = False
        self.status_label.configure(text="Ulanmoqda…")
        self.connect_button.configure(state="disabled")
        self.worker = threading.Thread(
            target=self._run_network,
            args=(host, port, username, self.outgoing, self.stop_event, self.events),
            daemon=True,
        )
        self.worker.start()

    def _run_network(
        self,
        host: str,
        port: int,
        username: str,
        outgoing: queue.Queue[dict[str, Any]],
        stop_event: threading.Event,
        events: queue.Queue[tuple[str, Any]],
    ) -> None:
        try:
            asyncio.run(self._network_session(host, port, username, outgoing, stop_event, events))
        except (OSError, ConnectionError, asyncio.TimeoutError) as exc:
            events.put(("disconnected", _describe_connection_error(host, port, exc)))
        except ProtocolError as exc:
            events.put(("disconnected", f"Server protokoli xatosi: {exc}"))
        finally:
            events.put(("network_closed", None))

    async def _network_session(
        self,
        host: str,
        port: int,
        username: str,
        outgoing: queue.Queue[dict[str, Any]],
        stop_event: threading.Event,
        events: queue.Queue[tuple[str, Any]],
    ) -> None:
        reader, writer = await asyncio.open_connection(host, port)
        await write_message(writer, {"type": "login", "username": username})
        events.put(("connecting", None))

        async def send_pending() -> None:
            while not stop_event.is_set():
                try:
                    message = outgoing.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.05)
                    continue
                await write_message(writer, message)
            await write_message(writer, {"type": "logout"})

        async def receive_messages() -> None:
            while True:
                message = await read_message(reader)
                events.put(("message", message))

        sender = asyncio.create_task(send_pending())
        receiver = asyncio.create_task(receive_messages())
        try:
            done, pending = await asyncio.wait(
                (sender, receiver), return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                exception = task.exception()
                if exception is not None:
                    raise exception
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        except (asyncio.IncompleteReadError, ConnectionError, OSError) as exc:
            if not stop_event.is_set():
                events.put(("disconnected", _describe_connection_error(host, port, exc)))
        finally:
            stop_event.set()
            for task in (sender, receiver):
                if not task.done():
                    task.cancel()
            await asyncio.gather(sender, receiver, return_exceptions=True)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    def _disconnect(self) -> None:
        self.stop_event.set()
        self.status_label.configure(text="Uzilmoqda…")
        self.disconnect_button.configure(state="disabled")

    def _send_message(self, _event: tk.Event | None = None) -> str:
        text = self.message_var.get().strip()
        if not text or not self.connected:
            return "break"
        self.outgoing.put({"type": "broadcast", "message": text})
        self.message_var.set("")
        return "break"

    def _process_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "message":
                    self._handle_server_message(payload)
                elif event == "disconnected":
                    self.status_label.configure(text="Aloqa uzildi")
                    self._append(f"Server bilan aloqa uzildi: {payload}", "error")
                    messagebox.showwarning("Aloqa uzildi", str(payload))
                elif event == "network_closed":
                    self.connected = False
                    self.connect_button.configure(state="normal")
                    self.disconnect_button.configure(state="disabled")
                    self.send_button.configure(state="disabled")
                    self._set_private_send_state("disabled")
                    if self.status_label.cget("text") != "Aloqa uzildi":
                        self.status_label.configure(text="Ulanmagan")
                elif event == "connecting":
                    pass
        except queue.Empty:
            pass
        self.root.after(100, self._process_events)

    def _handle_server_message(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        if kind == "login_success":
            self.connected = True
            self.status_label.configure(text=f"Ulandi: {self.username}")
            self.connect_button.configure(state="disabled")
            self.disconnect_button.configure(state="normal")
            self.send_button.configure(state="normal")
            self._set_private_send_state("normal")
            self.message_entry.focus_set()
        elif kind == "history":
            for item in message.get("messages", []):
                if item.get("message_type", item.get("type")) == "private_message":
                    self._store_private_message(item, open_if_missing=False)
                else:
                    self._display_chat_message(item)
        elif kind == "user_list":
            selected = self.user_list.curselection()
            previous = self.user_list.get(selected[0]) if selected else None
            self.user_list.delete(0, tk.END)
            self.user_list.insert(tk.END, "Hamma (umumiy chat)")
            for username in message.get("users", []):
                if username != self.username:
                    self.user_list.insert(tk.END, username)
            if previous:
                for index in range(self.user_list.size()):
                    if self.user_list.get(index) == previous:
                        self.user_list.selection_set(index)
                        break
                else:
                    self.user_list.selection_set(0)
            else:
                self.user_list.selection_set(0)
        elif kind in ("broadcast", "private_message"):
            self._display_chat_message(message)
        elif kind == "system_message":
            self._append(message.get("message", ""), "system", message.get("timestamp"))
        elif kind == "error":
            self._append(message.get("message", "Server xatoligi"), "error")
            if not self.connected:
                messagebox.showerror("Ulanish xatoligi", message.get("message", ""))

    def _display_chat_message(self, message: dict[str, Any]) -> None:
        sender = message.get("sender", "?")
        kind = message.get("message_type", message.get("type"))
        if kind == "private_message":
            self._store_private_message(message, open_if_missing=True)
            return
        label = "Men" if sender == self.username else sender
        self._append(
            f"{label}: {message.get('message', '')}",
            "mine" if sender == self.username else "other",
            message.get("timestamp"),
        )

    def _store_private_message(
        self, message: dict[str, Any], open_if_missing: bool
    ) -> None:
        peer = self._private_peer(message)
        if peer is None:
            return
        history = self.private_histories.setdefault(peer, [])
        message_id = message.get("id")
        if message_id is not None and any(
            existing.get("id") == message_id for existing in history
        ):
            return
        history.append(message)

        view = self.private_windows.get(peer)
        if view is not None:
            self._append_private_message(view.chat, message)
        elif open_if_missing:
            self._open_private_chat(peer)

    def _private_peer(self, message: dict[str, Any]) -> str | None:
        sender = message.get("sender")
        receiver = message.get("receiver")
        if sender == self.username and isinstance(receiver, str):
            return receiver
        if receiver == self.username and isinstance(sender, str):
            return sender
        return None

    def _open_selected_private_chat(
        self, _event: tk.Event | None = None
    ) -> str | None:
        selection = self.user_list.curselection()
        if not selection:
            return "break" if _event is not None else None
        peer = self.user_list.get(selection[0])
        if peer != "Hamma (umumiy chat)" and peer != self.username:
            self._open_private_chat(peer)
        return "break" if _event is not None else None

    def _open_private_chat(self, peer: str) -> PrivateChatView:
        existing = self.private_windows.get(peer)
        if existing is not None and existing.window.winfo_exists():
            existing.window.lift()
            existing.window.focus_force()
            return existing

        window = tk.Toplevel(self.root)
        window.title(f"Shaxsiy chat — {peer}")
        window.geometry("520x440")
        window.minsize(380, 320)
        window.configure(bg="#f3f5f9")

        chat_frame = ttk.Frame(window, padding=(12, 12, 12, 0))
        chat_frame.pack(fill="both", expand=True)
        chat = tk.Text(
            chat_frame,
            state="disabled",
            wrap="word",
            font=("Segoe UI", 10),
            bg="white",
            fg="#172033",
            relief="flat",
            padx=12,
            pady=10,
        )
        scrollbar = ttk.Scrollbar(chat_frame, command=chat.yview)
        chat.configure(yscrollcommand=scrollbar.set)
        chat.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        chat.tag_configure("mine", justify="right", foreground="#175cd3")
        chat.tag_configure("other", justify="left", foreground="#172033")

        compose = ttk.Frame(window, padding=12)
        compose.pack(fill="x")
        message_var = tk.StringVar(master=window)
        entry = ttk.Entry(compose, textvariable=message_var)
        entry.pack(side="left", fill="x", expand=True)
        send_button = ttk.Button(
            compose,
            text="Yuborish",
            command=lambda: self._send_private_message(peer),
            state="normal" if self.connected else "disabled",
        )
        send_button.pack(side="left", padx=(8, 0))
        view = PrivateChatView(window, chat, message_var, send_button)
        self.private_windows[peer] = view
        entry.bind("<Return>", lambda _event: self._send_private_message(peer))
        window.protocol(
            "WM_DELETE_WINDOW", lambda peer=peer: self._close_private_chat(peer)
        )
        for message in self.private_histories.get(peer, []):
            self._append_private_message(chat, message)
        entry.focus_set()
        return view

    def _close_private_chat(self, peer: str) -> None:
        view = self.private_windows.pop(peer, None)
        if view is not None:
            view.window.destroy()

    def _send_private_message(self, peer: str) -> str:
        view = self.private_windows.get(peer)
        if view is None or not self.connected:
            return "break"
        text = view.message_var.get().strip()
        if not text:
            return "break"
        self.outgoing.put(
            {"type": "private_message", "receiver": peer, "message": text}
        )
        view.message_var.set("")
        return "break"

    def _set_private_send_state(self, state: str) -> None:
        for view in self.private_windows.values():
            view.send_button.configure(state=state)

    def _append_private_message(
        self, chat: tk.Text, message: dict[str, Any]
    ) -> None:
        sender = message.get("sender", "?")
        label = "Men" if sender == self.username else sender
        self._append_to_chat(
            chat,
            f"{label}: {message.get('message', '')}",
            "mine" if sender == self.username else "other",
            message.get("timestamp"),
        )

    def _append(self, text: str, tag: str, timestamp: str | None = None) -> None:
        self._append_to_chat(self.chat, text, tag, timestamp)

    def _append_to_chat(
        self,
        chat: tk.Text,
        text: str,
        tag: str,
        timestamp: str | None = None,
    ) -> None:
        display_time = ""
        if timestamp:
            try:
                display_time = datetime.fromisoformat(timestamp).astimezone().strftime("%H:%M")
            except ValueError:
                display_time = timestamp
        line = f"{display_time}  {text}" if display_time else text
        chat.configure(state="normal")
        chat.insert(tk.END, line + "\n\n", tag)
        chat.configure(state="disabled")
        chat.see(tk.END)

    def _on_close(self) -> None:
        if self.connected:
            self.stop_event.set()
            self.root.after(150, self.root.destroy)
        else:
            self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="LAN Messenger graphical client")
    parser.add_argument("--host", help="Pre-fill the server IP address")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    root = tk.Tk()
    app = MessengerClient(root)
    if args.host:
        app.host_var.set(args.host)
    app.port_var.set(str(args.port))
    root.mainloop()


if __name__ == "__main__":
    main()
