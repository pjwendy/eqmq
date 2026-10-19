"""The Bot: one headless character, with MQ2-style TLOs, commands and #events."""
from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .eqstr import EqStr
from .events import EventPattern, render_chat, render_message
from .network import PROTOCOL_VERSION, INetworkClient, ProtobufNetworkClient
from .plugin import MQPlugin, load_plugins
from .proto import headless_pb2 as pb
from .search import SpawnSearch
from .state import StateMirror
from .tlo import CON_COLORS, FACTIONS, BookSpell, Group, Item, Me, Spawn, Zone

SDK_VERSION = "eqmq/0.8"
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


# game text that means a cast failed (as rendered from eqstr_us.txt), and what to report
_CAST_FAILURES = (
    ("Your spell fizzles", "fizzled"),
    ("Your spell is interrupted", "interrupted"),
    ("Your casting has been interrupted", "interrupted"),
    ("Insufficient Mana", "not enough mana"),
    ("You must first select a target", "no target"),
    ("Your target is out of range", "out of range"),
    ("You cannot see your target", "can't see the target"),
    ("You can't cast spells while stunned", "stunned"),
)


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
class ZoneChange:
    """A zone change: "LEAVING" (on the way), "ARRIVED" (in Zone, state is fresh) or "REFUSED"."""
    Status: str
    Zone: str      # short name
    ZoneID: int
    Detail: str = ""


@dataclass(frozen=True)
class Consider:
    """A /consider answer. Color is "green", "lightblue", "blue", "white", "yellow", "red" or "grey"."""
    SpawnID: int
    Color: str
    Faction: str
    PctHPs: int

    @property
    def Safe(self) -> bool:
        """An easy fight: green, light blue or blue."""
        return self.Color in ("green", "lightblue", "blue")


@dataclass(frozen=True)
class LootResult:
    CorpseID: int
    ok: bool
    Error: str = ""
    Items: tuple = ()     # what we tried to loot; game messages say what we got
    Platinum: int = 0
    Gold: int = 0
    Silver: int = 0
    Copper: int = 0

    def __bool__(self) -> bool:
        return self.ok


@dataclass(frozen=True)
class Death:
    Killer: str
    CorpseID: int
    SpellID: int
    Damage: int


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
        self._handlers: dict[str, list[Callable]] = {"chat": [], "message": [], "line": [], "move": [], "zone": [],
                                                     "death": []}
        self._consider_waiters: dict[int, list[asyncio.Future]] = {}
        self._loot_waiters: dict[int, list[asyncio.Future]] = {}
        self._move_waiters: list[asyncio.Future] = []
        self._zone_waiters: list[asyncio.Future] = []
        self._zoning = False
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
                    if kind == "snapshot" and self._zoning:
                        # the session survived the zone change: this is the new zone's first state
                        self._zoning = False
                        z = frame.snapshot.zone
                        await self._zone_done(ZoneChange("ARRIVED", z.short_name, z.id))
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

    def Haters(self) -> list[Spawn]:
        """NPCs that have you on their hate list, nearest first."""
        me = self._state.me
        found = [self._state.spawn_tlo(i) for i in (me.haters if me else [])]
        return sorted((s for s in found if s), key=lambda s: s.Distance)

    def Book(self) -> list[BookSpell]:
        """Your spellbook, lowest level first."""
        return sorted(self._state.book, key=lambda s: (s.Level, s.Name))

    def BookSpell(self, name: str) -> BookSpell | None:
        return next((s for s in self._state.book if s.Name.lower() == name.lower()), None)

    def Inventory(self) -> list[Item]:
        """Everything you carry: worn, general slots, bags and cursor."""
        return list(self._state.inventory)

    def FindItem(self, name: str) -> Item | None:
        """The first carried item whose name contains `name`, as ${FindItem[...]}."""
        return next((i for i in self._state.inventory if name.lower() in i.Name.lower()), None)

    def FindItemCount(self, name: str) -> int:
        return sum(max(1, i.Charges) for i in self._state.inventory if name.lower() in i.Name.lower())

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

    async def cast(self, spell: int | str, target: Spawn | int | None = None, wait: bool = False,
                   timeout: float = 30) -> CommandResult:
        """Cast the spell in a gem: a gem number (1-based) or a memorised spell's name, as /cast.

        target: who to target first (None keeps your target; with no target you cast on yourself).
        wait=True returns once the cast has finished (or never started).
        """
        me = self.Me
        gem = me.Gem(spell) if me else None
        if gem is None:
            return CommandResult(False, f"{spell!r} is not memorised")
        if target is not None:
            await self.target(target)
            await asyncio.sleep(0.3)  # the target round trip
        cmd = pb.Command()
        cmd.cast.gem = gem.Slot - 1
        cmd.cast.spell_id = gem.ID
        failure: list[str] = []

        def watch(line: str) -> None:
            for text, reason in _CAST_FAILURES:
                if text in line:
                    failure.append(reason)

        if wait:
            self._handlers["line"].append(watch)
        try:
            result = await self.command(cmd)
            if not result or not wait:
                return result
            loop = asyncio.get_running_loop()
            start = loop.time()
            started = False
            while loop.time() < start + timeout and self.connected and not failure:
                if self.Me.Casting:
                    started = True
                elif started or loop.time() > start + 1.5:
                    break
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.2)  # a fizzle or interrupt message may trail the cast
            if failure:
                return CommandResult(False, failure[0])
            return CommandResult(True) if started else CommandResult(False, "the cast didn't start")
        finally:
            if watch in self._handlers["line"]:
                self._handlers["line"].remove(watch)

    async def stopcast(self) -> CommandResult:
        cmd = pb.Command()
        cmd.stop_cast.SetInParent()
        return await self.command(cmd)

    async def memorize(self, gem: int, spell: int | str | None, wait: bool = True, timeout: float = 15) -> CommandResult:
        """Memorise a spell from your book into gem (1-based); None forgets it. As /memspell."""
        spell_id = 0
        if spell is not None:
            found = self.BookSpell(spell) if isinstance(spell, str) else next(
                (s for s in self._state.book if s.ID == spell), None)
            if found is None:
                return CommandResult(False, f"{spell!r} is not in your spellbook")
            spell_id = found.ID
        cmd = pb.Command()
        cmd.memorize.gem = gem - 1
        cmd.memorize.spell_id = spell_id
        result = await self.command(cmd)
        if not result or not wait:
            return result
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline and self.connected:
            g = self.Me.Gem(gem)
            if (g.ID if g else 0) == spell_id and (g is None or g.Ready):
                return CommandResult(True)
            await asyncio.sleep(0.2)
        return CommandResult(False, "memorising didn't finish")

    async def consider(self, spawn: Spawn | int | None = None, timeout: float = 5) -> Consider | None:
        """/consider a spawn (default: your target). None if no answer came."""
        spawn_id = (self.Me.TargetID if spawn is None else spawn if isinstance(spawn, int) else spawn.ID)
        if not spawn_id:
            return None
        fut = asyncio.get_running_loop().create_future()
        self._consider_waiters.setdefault(spawn_id, []).append(fut)
        cmd = pb.Command()
        cmd.consider.spawn_id = spawn_id
        if not await self.command(cmd):
            self._consider_waiters[spawn_id].remove(fut)
            return None
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return None

    async def loot(self, corpse: Spawn | int, timeout: float = 10) -> LootResult:
        """Loot everything from a corpse (walk within ~10 units first)."""
        corpse_id = corpse if isinstance(corpse, int) else corpse.ID
        fut = asyncio.get_running_loop().create_future()
        self._loot_waiters.setdefault(corpse_id, []).append(fut)
        cmd = pb.Command()
        cmd.loot.corpse_id = corpse_id
        result = await self.command(cmd)
        if not result:
            self._loot_waiters[corpse_id].remove(fut)
            return LootResult(corpse_id, False, result.error)
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return LootResult(corpse_id, False, "no answer from the corpse")

    async def spawn_bots(self, names: list[str], group: bool = True, pause: float = 1.5) -> list[Spawn]:
        """Spawn your EQEmu bots (^botspawn) and, by default, invite them so they follow you.

        The server won't spawn bots while you're engaged, so this does nothing then.
        """
        if self.Me and self.Me.Engaged:
            return self.Bots()
        for name in names:
            if not any(b.Name.lower() == name.lower() for b in self.Bots()):
                await self.DoCommand(f"/bot ^botspawn {name}")
                await asyncio.sleep(pause)
        await asyncio.sleep(1.0)
        if group:
            for attempt in range(2):
                for b in self.Bots():
                    g = self.Group
                    if not (g and g.Member(b.Name)):
                        if attempt:
                            # it came back in an old group (e.g. after a death): camp it and try again
                            await self.DoCommand(f"/bot ^botcamp byname {b.Name}")
                            await asyncio.sleep(pause)
                            await self.DoCommand(f"/bot ^botspawn {b.Name}")
                            await asyncio.sleep(pause)
                        await self.invite(b.Name)
                        await asyncio.sleep(0.8)
                g = self.Group
                if all(g and g.Member(b.Name) for b in self.Bots()):
                    break
        return self.Bots()

    async def disband(self) -> CommandResult:
        """As /disband: removes your target from the group if you lead it, else leaves."""
        cmd = pb.Command()
        cmd.disband.SetInParent()
        return await self.command(cmd)

    def wait_zoned(self, timeout: float = 90) -> Awaitable[ZoneChange]:
        """Wait for the next zone change to finish: ARRIVED or REFUSED ("TIMEOUT" if neither).

        It starts listening when called, so call it before the zoning can happen (e.g. in a death
        handler) and await it later.
        """
        fut = asyncio.get_running_loop().create_future()
        self._zone_waiters.append(fut)

        async def wait() -> ZoneChange:
            try:
                return await asyncio.wait_for(fut, timeout)
            except asyncio.TimeoutError:
                return ZoneChange("TIMEOUT", "", 0, f"no zone change within {timeout:.0f}s")

        return wait()

    async def zone_to(self, short_name: str, timeout: float = 300) -> ZoneChange:
        """Walk to this zone's zone line for a neighbouring zone (see Zone.Exits) and through it.

        Returns once you're in the new zone (ARRIVED), or why not (REFUSED, TIMEOUT).
        """
        done = self.wait_zoned(timeout)  # listening before we start walking
        cmd = pb.Command()
        cmd.zone_to.zone = short_name
        result = await self.command(cmd)
        if not result:
            done.close()
            return ZoneChange("REFUSED", short_name, 0, result.error)
        return await done

    async def gm_zone(self, short_name: str, timeout: float = 90) -> ZoneChange:
        """Zone with the GM command #zone (needs GM status) and wait until in the new zone."""
        fut = asyncio.get_running_loop().create_future()
        self._zone_waiters.append(fut)
        result = await self.say(f"#zone {short_name}")
        if not result:
            self._zone_waiters.remove(fut)
            return ZoneChange("REFUSED", short_name, 0, result.error)
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return ZoneChange("TIMEOUT", short_name, 0, f"no zone change within {timeout:.0f}s")

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
        if word == "/cast":
            # /cast <gem number> | /cast "Spell Name"
            what = rest.strip().strip('"')
            if not what:
                return CommandResult(False, "usage: /cast <gem> | /cast \"Spell Name\"")
            return await self.cast(int(what) if what.isdigit() else what)
        if word == "/stopcast":
            return await self.stopcast()
        if word == "/memspell":
            # /memspell <gem> "Spell Name"
            gem, _, name = rest.partition(" ")
            if not gem.isdigit() or not name.strip():
                return CommandResult(False, "usage: /memspell <gem> \"Spell Name\"")
            return await self.memorize(int(gem), name.strip().strip('"'))
        if word in ("/consider", "/con"):
            spawn = self.Spawn(rest) if rest else self.Target
            if not spawn:
                return CommandResult(False, "nothing to consider")
            con = await self.consider(spawn)
            return CommandResult(True) if con else CommandResult(False, "no answer")
        if word == "/loot":
            corpse = self.Spawn(f"corpse {rest}".strip()) if rest or not self.Target else self.Target
            if not corpse:
                return CommandResult(False, "no corpse to loot")
            res = await self.loot(corpse)
            return CommandResult(res.ok, res.Error)
        if word in ("/travelto", "/zoneto"):
            # MQ2's /travelto, one zone hop: walk through the zone line to a neighbouring zone
            if not rest:
                return CommandResult(False, "usage: /travelto <zone short name>")
            change = await self.zone_to(rest.split()[0])
            return CommandResult(change.Status == "ARRIVED", change.Detail if change.Status != "ARRIVED" else "")
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
        """Register a handler: "chat" gets a Chat, "message" a Message, "line" every line, "move" a MoveResult,
        "zone" a ZoneChange, "death" a Death (yours)."""
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

    async def _zone_done(self, change: ZoneChange) -> None:
        if change.Status != "LEAVING":
            waiters, self._zone_waiters = self._zone_waiters, []
            for fut in waiters:
                if not fut.done():
                    fut.set_result(change)
        for fn in self._handlers["zone"]:
            await self._call(fn, change)

    async def _dispatch_event(self, event: pb.GameEvent) -> None:
        kind = event.WhichOneof("event")
        if kind == "consider":
            c = event.consider
            spawn = self._state.spawns.get(c.spawn_id)  # the reply's HP fields aren't filled in for NPCs
            con = Consider(c.spawn_id, CON_COLORS.get(c.color, str(c.color)), FACTIONS.get(c.faction, str(c.faction)),
                           spawn.hp_pct if spawn else 0)
            for fut in self._consider_waiters.pop(c.spawn_id, []):
                if not fut.done():
                    fut.set_result(con)
            return
        if kind == "loot":
            lt = event.loot
            res = LootResult(lt.corpse_id, lt.ok, lt.error, tuple(lt.items), lt.platinum, lt.gold, lt.silver, lt.copper)
            for fut in self._loot_waiters.pop(lt.corpse_id, []):
                if not fut.done():
                    fut.set_result(res)
            return
        if kind == "death":
            d = event.death
            death = Death(d.killer, d.corpse_id, d.spell_id, d.damage)
            for fn in self._handlers["death"]:
                await self._call(fn, death)
            return
        if kind == "zone":
            z = event.zone
            status = pb.ZoneStatus.Name(z.status).removeprefix("ZONE_")
            if status == "LEAVING":
                self._zoning = True
            await self._zone_done(ZoneChange(status, z.zone, z.zone_id, z.detail))
            return
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
