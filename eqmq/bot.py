"""The Bot: one headless character, with MQ2-style TLOs, commands and #events."""
from __future__ import annotations

import asyncio
import inspect
import logging
import math
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .eqstr import EqStr
from .events import EventPattern, render_chat, render_message
from .network import PROTOCOL_VERSION, INetworkClient, ProtobufNetworkClient
from .plugin import MQPlugin, load_plugins
from .proto import headless_pb2 as pb
from .search import SpawnSearch
from .state import StateMirror
from .tlo import CON_COLORS, CURSOR_SLOT, FACTIONS, BookSpell, BotGear, Group, Item, Me, Spawn, Zone, WORLD_CONTAINER, WORLD_SLOT

SDK_VERSION = "eqmq/0.16"
COMMAND_TIMEOUT = 10.0
log = logging.getLogger("eqmq")

# combat abilities (EQ skill numbers), for ability() and /doability
ABILITIES = {"backstab": 8, "bash": 10, "slam": 10, "dragon punch": 21, "tail rake": 21, "eagle strike": 23,
             "feign death": 25, "flying kick": 26, "hide": 29, "kick": 30, "round kick": 38, "sneak": 42,
             "tiger claw": 52, "intimidation": 71, "taunt": 73, "frenzy": 74}

# pet commands (EQEmu's PetCommand numbers), for pet() and /pet
PET_COMMANDS = {"health": 0, "leader": 1, "attack": 2, "qattack": 3, "follow": 4, "guard": 5, "sit": 6,
                "sit on": 7, "sit off": 8, "taunt": 12, "taunt on": 13, "taunt off": 14, "hold": 15,
                "hold on": 16, "hold off": 17, "ghold": 18, "spellhold": 21, "focus": 24, "feign": 27,
                "back off": 28, "get lost": 29, "guard me": 30, "regroup": 31}

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
class NavNote:
    """Where a walk found the zone's navmesh wanting (MoveResult.Nav). Kind: "no_mesh_here" (none
    where we stood), "no_mesh_there" (none at the destination), "not_connected" (no way between:
    Closest is where it gets nearest), "stuck" (walked into something it says isn't there), or a gap
    the walk went round: "off_mesh", "straight_walk" (To: where it stepped or walked to); and doors it
    couldn't open: "locked", "door_wont_open".
    Points are (x, y, z)."""
    Kind: str
    At: tuple[float, float, float]
    To: tuple[float, float, float]
    Closest: tuple[float, float, float]


@dataclass(frozen=True)
class MoveResult:
    """How a /moveto ended: "ARRIVED", "STOPPED", "STUCK", "NO_PATH", "ZONE_LINE", "LOCKED" (a door
    on the way that it has no key for) or "REFUSED" (the server didn't take the command: Error says
    why, e.g. the rate limit, casting, or not being in a zone yet)."""
    Status: str
    X: float
    Y: float
    Z: float
    Error: str = ""
    Nav: tuple[NavNote, ...] = ()  # what the walk found wrong with the navmesh, if anything

    @property
    def Loc(self) -> str:
        return f"{self.Y:.2f}, {self.X:.2f}, {self.Z:.2f}"


@dataclass(frozen=True)
class PackItem:
    """Something one of your bots carries in its pack (Bot.pack_list): its slot there, the item, how many,
    and whether it's a bag (the bags hold the rest)."""
    Slot: int
    ID: int
    Count: int
    Name: str
    Bag: bool = False


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
    Items: tuple = ()     # what came off the corpse
    Platinum: int = 0
    Gold: int = 0
    Silver: int = 0
    Copper: int = 0
    Left: tuple = ()      # what's still on it (no room for it, or it wouldn't come)

    def __bool__(self) -> bool:
        return self.ok


@dataclass(frozen=True)
class Merchant:
    """An open merchant window: what it sells (Item.Slot is the merchant slot, Item.Price the cost).
    A parcel merchant also lists the parcels waiting for you."""
    NpcID: int
    Items: tuple = ()
    ParcelMerchant: bool = False
    Parcels: tuple = ()  # Parcel

    def Find(self, name: str) -> "Item | None":
        return next((i for i in self.Items if name.lower() in i.Name.lower()), None)


@dataclass(frozen=True)
class Parcel:
    """A parcel waiting for you at the parcel merchants (any of them). ItemID 99990 is coin
    (Quantity: copper)."""
    Slot: int
    ItemID: int
    Name: str
    Quantity: int
    From: str
    Note: str = ""
    Sent: int = 0  # unix time


@dataclass(frozen=True)
class Death:
    Killer: str
    CorpseID: int
    SpellID: int
    Damage: int


@dataclass(frozen=True)
class SkillUp:
    """A skill (or language: SkillID 100 and up) went up to Value."""
    SkillID: int
    Name: str
    Value: int

    @property
    def Line(self) -> str:
        """What the client prints for it."""
        return f"You have become better at {self.Name}! ({self.Value})"


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
                                                     "death": [], "skill": []}
        self._consider_waiters: dict[int, list[asyncio.Future]] = {}
        self._loot_waiters: dict[int, list[asyncio.Future]] = {}
        self._merchant_waiters: dict[int, list[asyncio.Future]] = {}
        self._move_waiters: list[asyncio.Future] = []
        self._plan_waiters: list[asyncio.Future] = []
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

    def BotGear(self) -> list[BotGear]:
        """Your spawned EQEmu bots and what each one wears."""
        return list(self._state.bot_gear)

    def Book(self) -> list[BookSpell]:
        """Your spellbook, lowest level first."""
        return sorted(self._state.book, key=lambda s: (s.Level, s.Name))

    def BookSpell(self, name: str) -> BookSpell | None:
        return next((s for s in self._state.book if s.Name.lower() == name.lower()), None)

    def Inventory(self) -> list[Item]:
        """Everything you carry: worn, general slots, bags and cursor (not the bank)."""
        return [i for i in self._state.inventory if not i.Banked]

    def Bank(self) -> list[Item]:
        """What's in your bank (slots 2000-2023 and the bags in them)."""
        return [i for i in self._state.inventory if i.Banked]

    def free_book_slot(self) -> int | None:
        used = {s.Slot for s in self._state.book}
        return next((i for i in range(720) if i not in used), None)

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
                     timeout: float = 300, avoid: bool = False) -> CommandResult | MoveResult:
        """Walk to a point (in-game x, y, z; /loc prints y first) along the navmesh at run speed.

        With wait=True, returns the MoveResult when the walk ends instead of the CommandResult (a
        refused command is a MoveResult too, with Status "REFUSED"), so callers can always read Status.
        z defaults to your current height; the server keeps you on the floor either way. avoid=True keeps
        round the mobs that would aggro you where there's a way (zone_to always does).
        """
        me = self._state.me
        if me and me.sitting:  # (the mover stops a sitting character at once: "STOPPED", every time)
            await self.stand()
        cmd = pb.Command()
        cmd.move_to.x, cmd.move_to.y = x, y
        cmd.move_to.z = z if z is not None else (me.z if me else 0.0)
        cmd.move_to.avoid = avoid
        if not wait:
            return await self.command(cmd)
        fut = asyncio.get_running_loop().create_future()
        self._move_waiters.append(fut)
        result = await self.command(cmd)
        if not result:
            if fut in self._move_waiters:  # (a move event may have taken the waiters already)
                self._move_waiters.remove(fut)
            return MoveResult("REFUSED", *(self._pos()), Error=result.error)
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            await self.stop()
            return MoveResult("STOPPED", *(self._pos()))

    async def drag_corpse(self, corpse: Spawn | int) -> CommandResult:
        """/corpse drag: a corpse (yours, or one you're consented to) follows you as you move, within the
        server's drag distance (Character:DragCorpseDistance)."""
        cmd = pb.Command()
        cmd.corpse_drag.corpse_id = corpse if isinstance(corpse, int) else corpse.ID
        return await self.command(cmd)

    async def drop_corpse(self, corpse: Spawn | int | None = None) -> CommandResult:
        """/corpse drop: stop dragging a corpse (None: every corpse you drag)."""
        cmd = pb.Command()
        cmd.corpse_drag.corpse_id = 0 if corpse is None else (corpse if isinstance(corpse, int) else corpse.ID)
        cmd.corpse_drag.drop = True
        return await self.command(cmd)

    async def click_door(self, door_id: int, timeout: float = 30.0) -> ZoneChange:
        """Click a door in this zone by its door id (0-255), as the client does: stand within its reach
        first. A door with a destination (a teleporter, a Plane of Knowledge book) zones you where it
        goes: returns once you're there (ARRIVED), or why not (REFUSED: the server's reason; TIMEOUT:
        clicked, but nothing took you anywhere: too far, or a door that only opens)."""
        start = self.Zone.ShortName if self.Zone else ""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        done = self.wait_zoned(timeout)  # (listening before we click)
        cmd = pb.Command()
        cmd.click_door.door_id = door_id
        result = await self.command(cmd)
        if not result:
            done.close()
            return ZoneChange("REFUSED", "", 0, result.error)
        change = await done
        # an arrival in the zone we clicked from isn't the door's (a zoning still settling: Eboola's first
        # two books "arrived" in the Plane of Knowledge she'd just come to): wait on for the real one
        while change.Status == "ARRIVED" and change.Zone == start and loop.time() < deadline:
            change = await self.wait_zoned(max(1.0, deadline - loop.time()))
        return change

    async def click_object(self, object_id: int) -> CommandResult:
        """Open a world container (a forge, oven, kiln, brew barrel, loom...) by its id in the zone's object table, as a click on
        it does: stand beside it first (the server checks). Put what you combine into its slots (WORLD_SLOT + 0...: move_item),
        then combine(); close_object() when done."""
        cmd = pb.Command()
        cmd.click_object.object_id = object_id
        return await self.command(cmd)

    async def close_object(self) -> CommandResult:
        """Close the world container opened (anything left in it comes back to the inventory)."""
        cmd = pb.Command()
        cmd.close_object.SetInParent()
        return await self.command(cmd)

    async def combine(self, container_slot: int = WORLD_CONTAINER) -> CommandResult:
        """The Combine button: make what the recipe says from what's in a container (WORLD_CONTAINER: the world object opened with
        click_object; or an inventory bag's slot, for a portable one). The server rolls the skill: the product, or the loss of
        some components, land in the inventory and the messages in chat (recent_messages)."""
        cmd = pb.Command()
        cmd.combine.container_slot = container_slot
        return await self.command(cmd)

    async def aa_exp(self, percent: int) -> CommandResult:
        """The share of experience going to AA, as the client's AA window slider (0 off, 100: no more
        levels; Me.AASplit says what it is)."""
        cmd = pb.Command()
        cmd.aa_exp.percent = max(0, min(100, int(percent)))
        return await self.command(cmd)

    async def surface(self, timeout: float = 30) -> MoveResult:
        """Under water: swim straight up to the surface for air (Me.Air: seconds left). The MoveResult
        when there, or REFUSED with why not (not under water, something solid above)."""
        cmd = pb.Command()
        cmd.surface.SetInParent()
        fut = asyncio.get_running_loop().create_future()
        self._move_waiters.append(fut)
        result = await self.command(cmd)
        if not result:
            if fut in self._move_waiters:  # (a move event may have taken the waiters already)
                self._move_waiters.remove(fut)
            return MoveResult("REFUSED", *(self._pos()), Error=result.error)
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            await self.stop()
            return MoveResult("STOPPED", *(self._pos()))

    async def route_length(self, x: float, y: float, z: float | None = None, timeout: float = 5) -> float | None:
        """How far a walk to (in-game x, y, z) would be along the navmesh, without walking; None if
        there's no way there. A walk under way carries on."""
        me = self._state.me
        cmd = pb.Command()
        cmd.move_to.x, cmd.move_to.y = x, y
        cmd.move_to.z = z if z is not None else (me.z if me else 0.0)
        cmd.move_to.plan_only = True
        fut = asyncio.get_running_loop().create_future()
        self._plan_waiters.append(fut)
        if not await self.command(cmd):
            self._plan_waiters.remove(fut)
            return None
        try:
            plan = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return None
        return plan[0] if plan else None

    async def zone_plan(self, short_name: str, number: int = 0, timeout: float = 5) -> tuple[float, float] | None:
        """The walk zone_to would take to this zone's zone line for a neighbouring zone, without walking:
        (its length, how much of it is a swim), or None if there's no way there. A walk under way carries on."""
        cmd = pb.Command()
        cmd.zone_to.zone = short_name
        cmd.zone_to.number = number
        cmd.zone_to.plan_only = True
        fut = asyncio.get_running_loop().create_future()
        self._plan_waiters.append(fut)
        if not await self.command(cmd):
            self._plan_waiters.remove(fut)
            return None
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return None

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

    async def ability(self, which: str | int) -> CommandResult:
        """Use a combat ability as the client's ability buttons do, by name or EQ skill number: kick,
        bash (slam), backstab, taunt, frenzy, intimidation and the monk strikes act on your target;
        sneak, hide and feign death on you. The server checks the skill and its reuse timer (it says
        "Ability recovery time not yet met." if you're early). As /doability."""
        skill = which if isinstance(which, int) else ABILITIES.get(which.lower().strip())
        if skill is None:
            return CommandResult(False, f"unknown ability {which!r}; one of {', '.join(sorted(ABILITIES))}")
        cmd = pb.Command()
        cmd.ability.skill_id = skill
        return await self.command(cmd)

    async def pet(self, command: str | int) -> CommandResult:
        """Command your pet, as /pet: "attack" (your target), "back off", "follow", "guard", "taunt on",
        "hold", "sit", ... (PET_COMMANDS), or EQEmu's pet command number."""
        number = command if isinstance(command, int) else PET_COMMANDS.get(command.lower().strip())
        if number is None:
            return CommandResult(False, f"unknown pet command {command!r}; one of {', '.join(PET_COMMANDS)}")
        cmd = pb.Command()
        cmd.pet.command = number
        return await self.command(cmd)

    def Pet(self) -> Spawn | None:
        """Your pet, if you have one here."""
        me = self.Me
        return next((s for s in self.Spawns("pet") if me and s.OwnerID == me.ID), None)

    async def discipline(self, spell_id: int) -> CommandResult:
        """Use a discipline you know (Me.Disciplines), as the combat abilities window: on your target,
        or yourself. The server applies its reuse timer."""
        cmd = pb.Command()
        cmd.discipline.spell_id = spell_id
        return await self.command(cmd)

    async def use_item(self, item: Item | int) -> CommandResult:
        """Right-click an item (or a slot): its click effect, a potion or food, or a tome, which teaches
        you its discipline."""
        cmd = pb.Command()
        cmd.use_item.slot = item if isinstance(item, int) else item.Slot
        return await self.command(cmd)

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

    async def open_merchant(self, npc: Spawn | int, timeout: float = 5) -> Merchant | None:
        """Open a merchant's window (stand within ~20 units, as the client must). None if it didn't open."""
        npc_id = npc if isinstance(npc, int) else npc.ID
        fut = asyncio.get_running_loop().create_future()
        self._merchant_waiters.setdefault(npc_id, []).append(fut)
        cmd = pb.Command()
        cmd.merchant.npc_id = npc_id
        cmd.merchant.open = True
        if not await self.command(cmd):
            self._merchant_waiters[npc_id].remove(fut)
            return None
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return None

    async def close_merchant(self, npc: Spawn | int) -> CommandResult:
        cmd = pb.Command()
        cmd.merchant.npc_id = npc if isinstance(npc, int) else npc.ID
        cmd.merchant.open = False
        return await self.command(cmd)

    async def buy(self, npc: Spawn | int, merchant_slot: int, quantity: int = 1) -> CommandResult:
        """Buy from an open merchant (its Item.Slot). The server checks coin, lore and room."""
        cmd = pb.Command()
        cmd.buy.npc_id = npc if isinstance(npc, int) else npc.ID
        cmd.buy.merchant_slot = merchant_slot
        cmd.buy.quantity = quantity
        return await self.command(cmd)

    async def give(self, npc: Spawn | int, item: Item | int, quantity: int = 0) -> CommandResult:
        """Hand an item from your inventory (all of a stack by default) to an NPC beside you, as the trade
        window does: its script takes it (a quest's hand-in). Not while it's fighting."""
        slot = item if isinstance(item, int) else item.Slot
        if slot != CURSOR_SLOT:
            # the trade window takes only what's on the cursor (the server kicks a client that moves anything else
            # into it: "Trade with non-cursor item", which put a soulstone's giver in a login loop): pick it up first
            if any(i.Slot == CURSOR_SLOT for i in self.Inventory()):
                return CommandResult(ok=False, error="something is already on the cursor")
            moved = await self.move_item(slot, CURSOR_SLOT, quantity)
            if not moved:
                return moved
            await asyncio.sleep(0.5)
            slot = CURSOR_SLOT
        cmd = pb.Command()
        cmd.give.npc_id = npc if isinstance(npc, int) else npc.ID
        cmd.give.slot = slot
        cmd.give.quantity = quantity
        return await self.command(cmd)

    async def sell(self, npc: Spawn | int, item: Item | int, quantity: int = 0) -> CommandResult:
        """Sell an item from your inventory (all of a stack by default) to an open merchant."""
        cmd = pb.Command()
        cmd.sell.npc_id = npc if isinstance(npc, int) else npc.ID
        cmd.sell.slot = item if isinstance(item, int) else item.Slot
        cmd.sell.quantity = quantity
        return await self.command(cmd)

    async def send_parcel(self, npc: Spawn | int, item: Item | int, to: str, note: str = "",
                          quantity: int = 0) -> CommandResult:
        """Send an item from your inventory (all of a stack by default) as a parcel to a character,
        at a parcel merchant whose window is open. Not no-drop items. The server allows one parcel
        every 30 seconds (Parcel:ParcelDeliveryDelay); a refusal comes as the merchant's tell."""
        cmd = pb.Command()
        cmd.parcel_send.npc_id = npc if isinstance(npc, int) else npc.ID
        cmd.parcel_send.slot = item if isinstance(item, int) else item.Slot
        cmd.parcel_send.to = to
        cmd.parcel_send.note = note[:127]
        cmd.parcel_send.quantity = quantity
        return await self.command(cmd)

    async def retrieve_parcel(self, npc: Spawn | int, parcel: "Parcel") -> CommandResult:
        """Take a parcel (Merchant.Parcels) from an open parcel merchant's window into your bags."""
        cmd = pb.Command()
        cmd.parcel_retrieve.npc_id = npc if isinstance(npc, int) else npc.ID
        cmd.parcel_retrieve.parcel_slot = parcel.Slot
        cmd.parcel_retrieve.item_id = parcel.ItemID
        return await self.command(cmd)

    async def destroy(self, item: Item | int) -> CommandResult:
        """Destroy an item (all of a stack), as the client's Destroy button: pick it up (whatever was
        on the cursor goes where it was) and destroy what's on the cursor."""
        slot = item if isinstance(item, int) else item.Slot
        if slot != CURSOR_SLOT:
            moved = await self.move_item(slot, CURSOR_SLOT)
            if not moved:
                return moved
            await asyncio.sleep(0.5)
        return await self.move_item(CURSOR_SLOT, -1)

    async def move_item(self, from_slot: int, to_slot: int, quantity: int = 0) -> CommandResult:
        """Move an item, swapping with whatever is there: equip it, or put a bag in a general slot."""
        cmd = pb.Command()
        cmd.move_item.from_slot = from_slot
        cmd.move_item.to_slot = to_slot
        cmd.move_item.quantity = quantity
        return await self.command(cmd)

    async def give_to_bot(self, bot_name: str, item: Item | int, slot: int | None = None,
                          timeout: float = 5) -> CommandResult:
        """Hand an item from your inventory to one of your bots (^inventorygive), optionally into a
        worn slot. Whatever it wore there comes back to your cursor. Not while engaged."""
        from_slot = item if isinstance(item, int) else item.Slot
        if from_slot != CURSOR_SLOT:
            # the bot gets whatever is on the cursor, so it must be empty first
            if any(i.Slot == CURSOR_SLOT for i in self.Inventory()):
                return CommandResult(False, "something else is on the cursor")
            moved = await self.move_item(from_slot, CURSOR_SLOT)
            if not moved:
                return moved
            await asyncio.sleep(0.5)
        before = next((b.Equipment for b in self.BotGear() if b.Name.lower() == bot_name.lower()), ())
        said: list[str] = []

        def watch(line: str) -> None:  # what the server or the bot says about it
            low = line.lower()
            if bot_name.lower() in low or any(w in low for w in ("trade", "engaged", "cannot", "can't", "unable", "lore")):
                said.append(line)

        self._handlers["line"].append(watch)
        try:
            result = await self.DoCommand(f"/bot ^inventorygive byname {bot_name}" + (f" {slot}" if slot is not None else ""))
            if not result:
                return result
            deadline = asyncio.get_running_loop().time() + timeout
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.3)
                now = next((b.Equipment for b in self.BotGear() if b.Name.lower() == bot_name.lower()), ())
                if now != before:
                    return CommandResult(True)
            return CommandResult(False, f"{bot_name} didn't take it" + (f": {said[-1]}" if said else " (nothing said)"))
        finally:
            if watch in self._handlers["line"]:
                self._handlers["line"].remove(watch)

    async def _pack(self, command: str, until, timeout: float = 4) -> list[str]:
        """Send a ^pack command and collect what it says ("pack ..." lines) until until(line) or timeout."""
        said: list[str] = []
        done = asyncio.Event()

        def watch(line: str) -> None:
            text = line.strip()
            if text.startswith("pack"):
                said.append(text)
                if until(text):
                    done.set()

        self._handlers["line"].append(watch)
        try:
            result = await self.DoCommand(f"/bot ^pack {command}")
            if not result:
                return [f"pack: {result.error}"]
            try:
                await asyncio.wait_for(done.wait(), timeout)
            except asyncio.TimeoutError:
                pass
            return said
        finally:
            if watch in self._handlers["line"]:
                self._handlers["line"].remove(watch)

    async def pack_give(self, bot_name: str, item: Item | int, timeout: float = 4) -> CommandResult:
        """Put an item from your inventory into one of your bots' packs (^pack: its general slots and the
        bags in them, carried, not worn): onto a stack of the same, a bag into a free slot, anything else
        into a bag with room. A bag must be empty. Not while engaged or trading."""
        from_slot = item if isinstance(item, int) else item.Slot
        if from_slot != CURSOR_SLOT:
            if any(i.Slot == CURSOR_SLOT for i in self.Inventory()):
                return CommandResult(False, "something else is on the cursor")
            moved = await self.move_item(from_slot, CURSOR_SLOT)
            if not moved:
                return moved
            await asyncio.sleep(0.4)
        said = await self._pack(f"give byname {bot_name}", lambda t: ":" in t, timeout)
        last = said[-1] if said else ""
        if " took " in last:
            return CommandResult(True)
        return CommandResult(False, last or f"{bot_name} said nothing")

    async def pack_list(self, bot_name: str, timeout: float = 4) -> tuple[list[PackItem], int]:
        """What one of your bots carries in its pack ([PackItem], best read once per town trip), and how
        many more things it has room for."""
        said = await self._pack(f"list byname {bot_name}", lambda t: "room for" in t, timeout)
        items, room = [], 0
        for text in said:
            if "room for" in text:
                try:
                    room = int(text.rsplit("room for", 1)[1].split()[0])
                except (ValueError, IndexError):
                    pass
                continue
            parts = text.split(" ", 5)  # pack <slot> <item id> <count> <bag|item> <name>
            if len(parts) == 6 and parts[1].lstrip("-").isdigit() and parts[4] in ("bag", "item"):
                items.append(PackItem(int(parts[1]), int(parts[2]), int(parts[3]), parts[5], parts[4] == "bag"))
        return items, room

    async def pack_take(self, bot_name: str, slot: int, timeout: float = 4) -> CommandResult:
        """Take back what's in a pack slot (PackItem.Slot) of one of your bots: it comes to your cursor
        (put it away with move_item). A bag only when it's empty; not a lore item you already have."""
        if any(i.Slot == CURSOR_SLOT for i in self.Inventory()):
            return CommandResult(False, "something else is on the cursor")
        said = await self._pack(f"take {slot} byname {bot_name}", lambda t: ":" in t, timeout)
        last = said[-1] if said else ""
        if " gave back " in last:
            return CommandResult(True)
        return CommandResult(False, last or f"{bot_name} said nothing")

    async def scribe(self, scroll: Item, book_slot: int | None = None) -> CommandResult:
        """Scribe a spell scroll from your inventory into the spellbook, as the client: pick it up,
        write it into a free page."""
        page = self.free_book_slot() if book_slot is None else book_slot
        if page is None:
            return CommandResult(False, "the spellbook is full")
        if scroll.Slot != CURSOR_SLOT:
            moved = await self.move_item(scroll.Slot, CURSOR_SLOT)
            if not moved:
                return moved
            await asyncio.sleep(0.5)
        cmd = pb.Command()
        cmd.scribe.book_slot = page
        cmd.scribe.spell_id = scroll.ScrollSpell
        return await self.command(cmd)

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

    async def zone_to(self, short_name: str, timeout: float | None = None, number: int = 0) -> ZoneChange:
        """Walk to this zone's zone line for a neighbouring zone (see Zone.Exits) and through it: the one
        with the shortest walk from here, or zone point `number` (a zone with several ways into another).

        Returns once you're in the new zone (ARRIVED), or why not (REFUSED, TIMEOUT). The timeout
        defaults to the walk to the nearest such zone line at your run speed (at least 5 minutes).
        """
        if timeout is None:
            me, zone = self._state.me, self.Zone
            far = [math.dist((me.x, me.y), (e.X if abs(e.X) < 999990 else me.x, e.Y if abs(e.Y) < 999990 else me.y))
                   for e in (zone.Exits if zone else ()) if e.Zone == short_name] if me else []
            timeout = max(300.0, self.walk_time(min(far), 60)) if far else 300.0
        done = self.wait_zoned(timeout)  # listening before we start walking
        cmd = pb.Command()
        cmd.zone_to.zone = short_name
        cmd.zone_to.number = number
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
            if fut in self._zone_waiters:  # (a lost connection clears the waiters itself)
                self._zone_waiters.remove(fut)
            return ZoneChange("REFUSED", short_name, 0, result.error)
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return ZoneChange("TIMEOUT", short_name, 0, f"no zone change within {timeout:.0f}s")

    def walk_time(self, distance: float, margin: float = 30.0) -> float:
        """A timeout for walking `distance` units at your run speed: routes wind (half as far again
        as the straight line), plus `margin` seconds for doors, lifts and the start. With no speed
        known (rooted, or an older server) it assumes 10 units a second."""
        me = self._state.me
        speed = me.run_speed if me and me.run_speed > 0 else 10.0
        return margin + distance * 1.5 / max(speed, 3.0)

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
        if word == "/pet":
            return await self.pet(rest)
        if word in ("/disc", "/discipline") and rest.strip().isdigit():
            return await self.discipline(int(rest))
        if word == "/doability":
            return await self.ability(int(rest) if rest.strip().isdigit() else rest)
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
        "zone" a ZoneChange, "death" a Death (yours), "skill" a SkillUp (also a line, as the client prints it)."""
        if kind not in self._handlers:
            raise ValueError(f"unknown event kind {kind!r}; use one of {sorted(self._handlers)}")

        def register(fn: Callable) -> Callable:
            self._handlers[kind].append(fn)
            return fn

        return register

    def off(self, kind: str, fn: Callable) -> None:
        """Unregister a handler added with on()."""
        if fn in self._handlers.get(kind, []):
            self._handlers[kind].remove(fn)

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
        if kind == "merchant":
            mv = event.merchant
            merchant = Merchant(mv.npc_id, tuple(Item.from_pb(i) for i in mv.items), mv.parcel_merchant,
                                tuple(Parcel(p.slot, p.item_id, p.name, p.quantity, getattr(p, "from"), p.note, p.sent)
                                      for p in mv.parcels))
            if mv.open:
                for fut in self._merchant_waiters.pop(mv.npc_id, []):
                    if not fut.done():
                        fut.set_result(merchant)
            return
        if kind == "loot":
            lt = event.loot
            res = LootResult(lt.corpse_id, lt.ok, lt.error, tuple(lt.items), lt.platinum, lt.gold, lt.silver, lt.copper,
                             tuple(lt.left))
            for fut in self._loot_waiters.pop(lt.corpse_id, []):
                if not fut.done():
                    fut.set_result(res)
            return
        if kind == "skill":
            sk = event.skill
            up = SkillUp(sk.skill_id, sk.name, sk.value)
            for fn in self._handlers["skill"]:
                await self._call(fn, up)
            for fn in self._handlers["line"]:  # as the client prints it, for #event and line watchers
                await self._call(fn, up.Line)
            for pattern, fn in self._patterns:
                captures = pattern.match(up.Line)
                if captures is not None:
                    await self._call(fn, *captures)
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
        if kind == "move" and event.move.plan_only:
            m = event.move
            plan = (m.route_length, m.swim_length) if m.status == pb.MOVE_ARRIVED else None
            waiters, self._plan_waiters = self._plan_waiters, []
            for fut in waiters:
                if not fut.done():
                    fut.set_result(plan)
            return
        if kind == "move":
            m = event.move
            nav = tuple(NavNote(n.kind, (n.x, n.y, n.z), (n.to_x, n.to_y, n.to_z), (n.closest_x, n.closest_y, n.closest_z))
                        for n in m.nav)
            done = MoveResult(pb.MoveStatus.Name(m.status).removeprefix("MOVE_"), m.x, m.y, m.z, Nav=nav)
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
