"""The Bot: one headless character, with MQ2-style TLOs over a live state mirror."""
from __future__ import annotations

import asyncio
import logging

from .network import PROTOCOL_VERSION, INetworkClient, ProtobufNetworkClient
from .proto import headless_pb2 as pb
from .search import SpawnSearch
from .state import StateMirror
from .tlo import Me, Spawn, Zone

SDK_VERSION = "eqmq/0.1"
log = logging.getLogger("eqmq")


class Refused(Exception):
    """The server refused the session (reason is the RefusedReason name)."""

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class Bot:
    def __init__(self, network: INetworkClient, token: str, character: str):
        self._net = network
        self._token = token
        self._character = character
        self._state = StateMirror()
        self._ready = asyncio.Event()
        self._closed = asyncio.Event()
        self._receiver: asyncio.Task | None = None
        self.session_id = ""
        self.spawn_id = 0

    # ---- lifecycle ----

    async def start(self, timeout: float = 60) -> None:
        """Connect, authenticate and wait for the first snapshot."""
        await self._net.connect()
        hello = pb.ClientFrame()
        hello.hello.token = self._token
        hello.hello.character = self._character
        hello.hello.sdk_version = SDK_VERSION
        hello.hello.protocol_version = PROTOCOL_VERSION
        await self._net.send(hello)

        self._receiver = asyncio.create_task(self._receive())
        ready = asyncio.create_task(self._ready.wait())
        closed = asyncio.create_task(self._closed.wait())
        done, pending = await asyncio.wait({ready, closed}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        if self._refused:
            raise self._refused
        if not self._ready.is_set():
            await self.close()
            raise TimeoutError("no snapshot from the server")

    async def close(self) -> None:
        await self._net.close()
        if self._receiver:
            self._receiver.cancel()
        self._closed.set()

    async def wait_closed(self) -> None:
        await self._closed.wait()

    @property
    def connected(self) -> bool:
        return self._ready.is_set() and not self._closed.is_set()

    _refused: Refused | None = None

    async def _receive(self) -> None:
        try:
            async for frame in self._net.frames():
                kind = frame.WhichOneof("payload")
                if kind == "refused":
                    self._refused = Refused(pb.RefusedReason.Name(frame.refused.reason), frame.refused.detail)
                    log.warning("refused: %s", self._refused)
                    break
                if kind == "welcome":
                    self.session_id = frame.welcome.session_id
                    self.spawn_id = frame.welcome.spawn_id
                    log.info("welcome: session %s spawn %d", self.session_id, self.spawn_id)
                    continue
                self._state.apply(frame)
                if self._state.ready:
                    self._ready.set()
        finally:
            self._closed.set()

    # ---- TLOs ----

    @property
    def Me(self) -> Me | None:
        return self._state.me_tlo()

    @property
    def Zone(self) -> Zone | None:
        return self._state.zone_tlo()

    @property
    def Target(self) -> Spawn | None:
        me = self._state.me
        return self._state.spawn_tlo(me.target_id) if me and me.target_id else None

    def Spawns(self, search: str = "") -> list[Spawn]:
        """All spawns matching an MQ2 search string, nearest first."""
        q = SpawnSearch.parse(search)
        me = self._state.me
        mz = me.z if me else 0.0
        return sorted((s for s in self._state.all_spawns() if q.matches(s, mz)), key=lambda s: s.Distance)

    def Spawn(self, search: str = "") -> Spawn | None:
        """The nearest spawn matching the search, as ${Spawn[...]}."""
        found = self.Spawns(search)
        return found[0] if found else None

    def NearestSpawn(self, n: int, search: str = "") -> Spawn | None:
        """The n-th nearest match (1-based), as ${NearestSpawn[n,...]}."""
        found = self.Spawns(search)
        return found[n - 1] if 0 < n <= len(found) else None

    def SpawnCount(self, search: str = "") -> int:
        return len(self.Spawns(search))


async def connect(host: str, port: int, token: str, character: str, timeout: float = 60) -> Bot:
    """Log a headless character in and return it once its first snapshot has arrived."""
    bot = Bot(ProtobufNetworkClient(host, port), token, character)
    await bot.start(timeout)
    return bot
