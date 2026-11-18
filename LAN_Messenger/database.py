"""Small SQLite persistence layer used by the chat server."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import HISTORY_LIMIT


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MessengerDatabase:
    """Owns the server's SQLite connection and chat history operations."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self.connection = sqlite3.connect(self.path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=10000")
        self._create_tables()

    def _create_tables(self) -> None:
        with self.connection:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    connected_at TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT NOT NULL,
                    receiver TEXT,
                    message TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_timestamp "
                "ON messages(timestamp)"
            )

    def user_connected(self, username: str) -> None:
        now = utc_timestamp()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO users (username, connected_at, last_seen)
                VALUES (?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    connected_at = excluded.connected_at,
                    last_seen = excluded.last_seen
                """,
                (username, now, now),
            )

    def user_disconnected(self, username: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE users SET last_seen = ? WHERE username = ?",
                (utc_timestamp(), username),
            )

    def save_message(
        self,
        sender: str,
        receiver: str | None,
        message: str,
        message_type: str,
    ) -> dict[str, Any]:
        timestamp = utc_timestamp()
        with self.connection:
            cursor = self.connection.execute(
                """
                INSERT INTO messages
                    (sender, receiver, message, message_type, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (sender, receiver, message, message_type, timestamp),
            )
        return {
            "type": message_type,
            "sender": sender,
            "receiver": receiver,
            "message": message,
            "timestamp": timestamp,
            "id": cursor.lastrowid,
        }

    def history_for(self, username: str, limit: int = HISTORY_LIMIT) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT id, sender, receiver, message, message_type, timestamp
            FROM messages
            WHERE message_type = 'broadcast'
               OR sender = ?
               OR receiver = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (username, username, limit),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def close(self) -> None:
        self.connection.close()
