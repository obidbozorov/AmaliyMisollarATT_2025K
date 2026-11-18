import asyncio
import json
import struct
import unittest

from protocol import ProtocolError, encode_message, read_message


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_round_trip_preserves_uzbek_text_and_frame_length(self):
        message = {"type": "broadcast", "message": "O‘zbekcha: salom, dunyo! "}
        frame = encode_message(message)
        length = struct.unpack("!I", frame[:4])[0]
        self.assertEqual(length, len(frame) - 4)

        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        self.assertEqual(await read_message(reader), message)

    async def test_rejects_malformed_json_and_non_object_json(self):
        for payload in (b"{bad json", json.dumps(["not", "an", "object"]).encode()):
            reader = asyncio.StreamReader()
            reader.feed_data(struct.pack("!I", len(payload)) + payload)
            with self.subTest(payload=payload), self.assertRaises(ProtocolError):
                await read_message(reader)

    async def test_rejects_invalid_frame_length(self):
        reader = asyncio.StreamReader()
        reader.feed_data(struct.pack("!I", 0))
        with self.assertRaises(ProtocolError):
            await read_message(reader)


if __name__ == "__main__":
    unittest.main()
