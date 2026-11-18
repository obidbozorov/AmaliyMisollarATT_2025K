"""JSON message framing helpers for the messenger TCP protocol."""

import asyncio
import json
import struct
from typing import Any

from config import MAX_FRAME_SIZE


class ProtocolError(ValueError):
    """Raised when a peer sends an invalid or oversized frame."""


def encode_message(message: dict[str, Any]) -> bytes:
    """Serialize a message as a four-byte length-prefixed UTF-8 JSON frame."""
    try:
        payload = json.dumps(
            message, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"Message cannot be encoded as JSON: {exc}") from exc

    if not payload or len(payload) > MAX_FRAME_SIZE:
        raise ProtocolError("Message is empty or exceeds the maximum frame size.")
    return struct.pack("!I", len(payload)) + payload


async def read_message(reader: asyncio.StreamReader) -> dict[str, Any]:
    """Read and decode one complete length-prefixed JSON object."""
    header = await reader.readexactly(4)
    (length,) = struct.unpack("!I", header)
    if length == 0 or length > MAX_FRAME_SIZE:
        raise ProtocolError("Invalid frame length.")

    payload = await reader.readexactly(length)
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"Invalid UTF-8 JSON message: {exc}") from exc
    if not isinstance(message, dict):
        raise ProtocolError("Each message must be a JSON object.")
    return message


async def write_message(
    writer: asyncio.StreamWriter, message: dict[str, Any]
) -> None:
    """Write one complete length-prefixed JSON object."""
    writer.write(encode_message(message))
    await writer.drain()
