"""The Bot: one headless character, with MQ2-style TLOs, commands and #events."""
from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Callable

from .eqstr import EqStr
from .events import EventPattern, render_chat, render_message
from .network import PROTOCOL_VERSION, INetworkClient, ProtobufNetworkClient
from .plugin import MQPlugin, load_plugins
from .proto import headless_pb2 as pb
from .search import SpawnSearch
from .state import StateMirror
from .tlo import Group, Me, Spawn, Zone

SDK_VERSION = "eqmq/0.5"
COMMAND_TIMEOUT = 10.0
log = logging.getLogger("eqmq")

_CHANNEL_COMMANDS = {
    "/say": pb.CHAT_SAY, "/s": pb.CHAT_SAY,
    "/g": pb.CHAT_GROUP, "/gsay": pb.CHAT_GROUP,
    "/gu": pb.CHAT_GUILD, "/guildsay": pb.CHAT_GUILD,
    "/ooc": pb.CHAT_OOC,
    "/shout": pb.CHAT_SHOUT,
    "/auction": pb.CHAT_AUCTION, "/auc": pb.CHAT_AUCTION,
    "/rsay": pb.CHAT_RAID,
}


class Refused(Exception):
    """The server refused the session (reason is the RefusedReason name)."""

    def __init__(self, reason: str, detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class MoveResult:
    """How a /moveto ended: "ARRIVED", "STOPPED", "STUCK", "NO_PATH" or "ZONE_LINE"."""
    Status: str
    X: float
    Y: float
    Z: float

    @property
    def Loc(self) -> str:
        return f"{self.Y:.2f}, {self.X:.2f}, {self.Z:.2f}"


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    error: str = ""

    def __bool__(self) -> bool:
        return self.ok


class Bot:
    def __init__(self, network: INetworkClient, token: str, character: str, eqstr: str | None = None):
        self._net = network
        self._token = token
        self._character = character
        self._eqstr = EqStr.load(eqstr)
        self._state = StateMirror()
        self._ready = asyncio.Event()
        self._closed = asyncio.Event()
        self._receiver: asyncio.Task | None = None
        self._refused: Refused | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._handlers: dict[str, list[Callable]] = {"chat": [], "message": [], "line": [], "move": []}
        self._move_waiters: list[asyncio.Future] = []
        self._commands: dict[str, Callable] = {}
        self._tlos: dict[str, Callable[[], Any]] = {}
        self._patterns: list[tuple[EventPattern, Callable]] = []
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
        waits = {asyncio.create_task(self._ready.wait()), asyncio.create_task(self._closed.wait())}
        _, pending = await asyncio.wait(waits, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
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
                elif kind == "result":
                    fut = self._pending.pop(frame.result.id, None)
                    if fut and not fut.done():
                        fut.set_result(CommandResult(frame.result.ok, frame.result.error))
                elif kind == "event":
                    await self._dispatch_event(frame.event)
                else:
                    self._state.apply(frame)
                    if self._state.ready:
                        self._ready.set()
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_result(CommandResult(False, "disconnected"))
            self._pending.clear()
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

    @property
    def Group(self) -> Group | None:
        """Your group, or None when not grouped."""
        return Group.from_pb(self._state.me) if self._state.me else None

    def Bots(self) -> list[Spawn]:
        """Your spawned EQEmu bots in this zone, nearest first."""
        me = self._state.me
        return [s for s in self.Spawns("bot") if me and s.OwnerID == me.spawn_id]

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

    # ---- commands ----

    async def command(self, cmd: pb.Command) -> CommandResult:
        """Send a raw Command and wait for the server's CommandResult."""
        if not self.connected:
            return CommandResult(False, "not connected")
        cmd.id = self._next_id
        self._next_id += 1
        fut = asyncio.get_running_loop().create_future()
        self._pending[cmd.id] = fut
        frame = pb.ClientFrame()
        frame.command.CopyFrom(cmd)
        await self._net.send(frame)
        try:
            return await asyncio.wait_for(fut, COMMAND_TIMEOUT)
        except asyncio.TimeoutError:
            self._pending.pop(cmd.id, None)
            return CommandResult(False, "no response from the server")

    async def target(self, spawn: Spawn | int | None) -> CommandResult:
        """Target a spawn (or None to clear). The result means 'asked'; check bot.Target after."""
        cmd = pb.Command()
        cmd.target.spawn_id = 0 if spawn is None else (spawn if isinstance(spawn, int) else spawn.ID)
        return await self.command(cmd)

    async def attack(self, on: bool = True) -> CommandResult:
        cmd = pb.Command()
        cmd.attack.on = on
        return await self.command(cmd)

    async def chat(self, channel: int, text: str, to: str = "") -> CommandResult:
        cmd = pb.Command()
        cmd.chat.channel = channel
        cmd.chat.text = text
        cmd.chat.to = to
        return await self.command(cmd)

    async def say(self, text: str) -> CommandResult:
        return await self.chat(pb.CHAT_SAY, text)

    async def tell(self, to: str, text: str) -> CommandResult:
        return await self.chat(pb.CHAT_TELL, text, to)

    async def group(self, text: str) -> CommandResult:
        return await self.chat(pb.CHAT_GROUP, text)

    async def sit(self, sit: bool = True) -> CommandResult:
        cmd = pb.Command()
        cmd.sit.sit = sit
        return await self.command(cmd)

    async def stand(self) -> CommandResult:
        return await self.sit(False)

    async def moveto(self, x: float, y: float, z: float | None = None, wait: bool = False,
                     timeout: float = 300) -> CommandResult | MoveResult:
        """Walk to a point (in-game x, y, z; /loc prints y first) along the navmesh at run speed.

        With wait=True, returns the MoveResult when the walk ends instead of the CommandResult.
        z defaults to your current height; the server keeps you on the floor either way.
        """
        me = self._state.me
        cmd = pb.Command()
        cmd.move_to.x, cmd.move_to.y = x, y
        cmd.move_to.z = z if z is not None else (me.z if me else 0.0)
        if not wait:
            return await self.command(cmd)
        fut = asyncio.get_running_loop().create_future()
        self._move_waiters.append(fut)
        result = await self.command(cmd)
        if not result:
            self._move_waiters.remove(fut)
            return result
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            await self.stop()
            return MoveResult("STOPPED", *(self._pos()))

    async def stop(self) -> CommandResult:
        """Stop walking."""
        cmd = pb.Command()
        cmd.stop.SetInParent()
        return await self.command(cmd)

    async def invite(self, who: Spawn | str | None = None) -> CommandResult:
        """Invite a player or one of your bots to your group (None: your target), as /invite."""
        cmd = pb.Command()
        cmd.invite.name = "" if who is None else (who if isinstance(who, str) else who.Name)
        return await self.command(cmd)

    async def face(self, spawn: Spawn | int | None = None) -> CommandResult:
        """Turn to face a spawn (None: your target), as /face. Melee needs you facing your target."""
        cmd = pb.Command()
        cmd.face.spawn_id = 0 if spawn is None else (spawn if isinstance(spawn, int) else spawn.ID)
        return await self.command(cmd)

    async def disband(self) -> CommandResult:
        """As /disband: removes your target from the group if you lead it, else leaves."""
        cmd = pb.Command()
        cmd.disband.SetInParent()
        return await self.command(cmd)

    def _pos(self) -> tuple[float, float, float]:
        me = self._state.me
        return (me.x, me.y, me.z) if me else (0.0, 0.0, 0.0)

    async def DoCommand(self, line: str) -> CommandResult:
        """Run an MQ2/EQ-style slash command, e.g. "/target id 123" or "/tell Eboola hi"."""
        word, _, rest = line.strip().partition(" ")
        word, rest = word.lower(), rest.strip()

        if word in self._commands:
            result = self._commands[word](rest)
            if inspect.isawaitable(result):
                result = await result
            return result if isinstance(result, CommandResult) else CommandResult(True)

        if word in _CHANNEL_COMMANDS:
            return await self.chat(_CHANNEL_COMMANDS[word], rest)
        if word in ("/tell", "/t", "/msg"):
            to, _, text = rest.partition(" ")
            return await self.tell(to, text.strip())
        if word == "/target":
            if rest.lower() in ("", "clear"):
                return await self.target(None)
            spawn = self.Spawn(rest)  # "id 123", "npc", a name, ... (MQ2 search syntax)
            return await self.target(spawn) if spawn else CommandResult(False, f"no spawn matches '{rest}'")
        if word == "/attack":
            if rest.lower() not in ("on", "off"):
                return CommandResult(False, "usage: /attack on|off")
            return await self.attack(rest.lower() == "on")
        if word == "/sit":
            return await self.sit(rest.lower() != "off")
        if word == "/stand":
            return await self.stand()
        if word == "/moveto":
            # MQ2 MoveUtils syntax: /moveto loc <y> <x> [z] | /moveto id <spawn id> | /moveto off
            parts = rest.split()
            if parts and parts[0].lower() == "off":
                return await self.stop()
            if len(parts) >= 3 and parts[0].lower() == "loc":
                try:
                    y, x = float(parts[1]), float(parts[2])
                    z = float(parts[3]) if len(parts) > 3 else None
                except ValueError:
                    return CommandResult(False, "usage: /moveto loc <y> <x> [z]")
                return await self.moveto(x, y, z)
            if len(parts) == 2 and parts[0].lower() == "id":
                spawn = self.Spawn(f"id {parts[1]}")
                if not spawn:
                    return CommandResult(False, f"no spawn with id {parts[1]}")
                return await self.moveto(spawn.X, spawn.Y, spawn.Z)
            return CommandResult(False, "usage: /moveto loc <y> <x> [z] | /moveto id <n> | /moveto off")
        if word == "/invite":
            return await self.invite(rest or None)
        if word == "/face":
            # /face (your target) | /face id <n> | /face <spawn search>
            if not rest:
                return await self.face()
            spawn = self.Spawn(rest)
            return await self.face(spawn) if spawn else CommandResult(False, f"no spawn matches '{rest}'")
        if word == "/disband":
            return await self.disband()
        if word == "/bot":
            # EQEmu bot commands are typed as ^command in say
            return await self.say(rest if rest.startswith("^") else f"^{rest}")
        return CommandResult(False, f"unsupported command {word}")

    # ---- plugins ----

    def register_command(self, name: str, handler: Callable) -> None:
        """Add a slash command for DoCommand: handler(rest_of_line), sync or async."""
        if not name.startswith("/"):
            raise ValueError("command names start with /")
        self._commands[name.lower()] = handler

    def register_tlo(self, name: str, getter: Callable[[], Any]) -> None:
        """Add a Top-Level Object, read with bot.TLO(name)."""
        self._tlos[name] = getter

    def TLO(self, name: str) -> Any:
        getter = self._tlos.get(name)
        return getter() if getter else None

    async def run(self, plugins: list[MQPlugin] | str | None = None, frame_ms: int = 100) -> None:
        """Run plugins until the bot disconnects: on_load, then on_frame every frame, then on_clean.

        plugins may be a list of MQPlugin instances or a directory to load them from.
        """
        if isinstance(plugins, str):
            plugins = load_plugins(plugins, self)
        plugins = plugins or []

        for p in plugins:
            await self._call(p.on_load)
        try:
            loop = asyncio.get_running_loop()
            while self.connected:
                started = loop.time()
                for p in plugins:
                    await self._call(p.on_frame)
                await asyncio.sleep(max(0.0, frame_ms / 1000 - (loop.time() - started)))
        finally:
            for p in plugins:
                await self._call(p.on_clean)

    # ---- events ----

    def on(self, kind: str) -> Callable:
        """Register a handler: "chat" gets a Chat, "message" a Message, "line" every line, "move" a MoveResult."""
        if kind not in self._handlers:
            raise ValueError(f"unknown event kind {kind!r}; use one of {sorted(self._handlers)}")

        def register(fn: Callable) -> Callable:
            self._handlers[kind].append(fn)
            return fn

        return register

    def event(self, pattern: str) -> Callable:
        """MQ2 #event: @bot.event("#1# tells you, '#2#'") is called with the captures."""
        compiled = EventPattern(pattern)

        def register(fn: Callable) -> Callable:
            self._patterns.append((compiled, fn))
            return fn

        return register

    async def _call(self, fn: Callable, *args: Any) -> None:
        try:
            result = fn(*args)
            if inspect.isawaitable(result):
                await result
        except Exception:
            log.exception("event handler %r failed", fn)

    async def _dispatch_event(self, event: pb.GameEvent) -> None:
        kind = event.WhichOneof("event")
        if kind == "move":
            m = event.move
            done = MoveResult(pb.MoveStatus.Name(m.status).removeprefix("MOVE_"), m.x, m.y, m.z)
            waiters, self._move_waiters = self._move_waiters, []
            for fut in waiters:
                if not fut.done():
                    fut.set_result(done)
            for fn in self._handlers["move"]:
                await self._call(fn, done)
            return
        if kind == "chat":
            item = render_chat(event.chat)
            handlers = self._handlers["chat"]
        elif kind == "message":
            item = render_message(event.message, self._eqstr)
            handlers = self._handlers["message"]
        else:
            return

        for fn in handlers:
            await self._call(fn, item)
        for fn in self._handlers["line"]:
            await self._call(fn, item.Line)
        for pattern, fn in self._patterns:
            captures = pattern.match(item.Line)
            if captures is not None:
                await self._call(fn, *captures)


async def connect(host: str, port: int, token: str, character: str, eqstr: str | None = None, timeout: float = 60) -> Bot:
    """Log a headless character in and return it once its first snapshot has arrived.

    eqstr: path to your client's eqstr_us.txt, to render messages sent as string ids
    (or set EQMQ_EQSTR).
    """
    bot = Bot(ProtobufNetworkClient(host, port), token, character, eqstr)
    await bot.start(timeout)
    return bot
