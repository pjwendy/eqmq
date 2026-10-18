"""Transport layer. Scripts never touch this; the Bot owns it.

INetworkClient is the seam that keeps scripts independent of how frames reach the server
(D11). ProtobufNetworkClient speaks the headless gateway protocol: TCP frames of
[uint32 big-endian length][serialized message].
"""
from __future__ import annotations

import abc
import asyncio
import struct
from typing import AsyncIterator

from .proto import headless_pb2 as pb

PROTOCOL_VERSION = pb.PROTOCOL_VERSION_CURRENT
MAX_FRAME_BYTES = 16 * 1024 * 1024


class INetworkClient(abc.ABC):
    """Sends ClientFrames and yields ServerFrames."""

    @abc.abstractmethod
    async def connect(self) -> None: ...

    @abc.abstractmethod
    async def send(self, frame: pb.ClientFrame) -> None: ...

    @abc.abstractmethod
    def frames(self) -> AsyncIterator[pb.ServerFrame]:
        """Incoming frames until the connection closes."""

    @abc.abstractmethod
    async def close(self) -> None: ...


class ProtobufNetworkClient(INetworkClient):
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)

    async def send(self, frame: pb.ClientFrame) -> None:
        if self._writer is None:
            raise ConnectionError("not connected")
        body = frame.SerializeToString()
        self._writer.write(struct.pack(">I", len(body)) + body)
        await self._writer.drain()

    async def frames(self) -> AsyncIterator[pb.ServerFrame]:
        if self._reader is None:
            raise ConnectionError("not connected")
        while True:
            try:
                header = await self._reader.readexactly(4)
                (length,) = struct.unpack(">I", header)
                if length > MAX_FRAME_BYTES:
                    raise ConnectionError(f"frame of {length} bytes is too large")
                body = await self._reader.readexactly(length)
            except asyncio.IncompleteReadError:
                return
            yield pb.ServerFrame.FromString(body)

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            self._writer = None
