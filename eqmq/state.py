"""State mirror: applies Snapshot/StateDelta frames to an internal model.

Scripts only ever see the frozen TLO objects it hands out.
"""
from __future__ import annotations

from .proto import headless_pb2 as pb
from .tlo import BookSpell, BotGear, Item, Me, Spawn, Zone


class StateMirror:
    def __init__(self) -> None:
        self.me: pb.Self | None = None
        self.zone: pb.ZoneInfo | None = None
        self.spawns: dict[int, pb.Spawn] = {}
        self.book: list[BookSpell] = []
        self.inventory: list[Item] = []
        self.bot_gear: list[BotGear] = []
        # (the frozen Spawns are built once per change, not per call: building every spawn of the zone on each Spawns() was three
        # quarters of a 20-leader runner's CPU, profiled 21 Nov)
        self._ver = 0                                          # bumped by every frame applied
        self._built: dict[int, tuple[pb.Spawn, Spawn]] = {}    # spawn id: the message it was built from, and the Spawn
        self._all: tuple[int, list[Spawn]] = (-1, [])          # all_spawns() as of _ver
        # (and Me, and each search's answer, once per frame: a 36-leader runner was a whole core, 25 Nov, Me.from_pb and Spawns() a fifth
        # of it, asked many times between two frames)
        self._me: tuple[int, Me | None] = (-1, None)
        self.searches: tuple[int, dict] = (-1, {})            # Bot.Spawns(search)'s answers as of _ver
        self._frame_kept: tuple[int, dict] = (-1, {})         # per_frame(): Group, Raid, Zone as of _ver

    @property
    def ready(self) -> bool:
        return self.me is not None

    def apply(self, frame: pb.ServerFrame) -> None:
        self._ver += 1
        kind = frame.WhichOneof("payload")
        if kind == "snapshot":
            snap = frame.snapshot
            self.me = pb.Self()
            self.me.CopyFrom(snap.me)
            self.zone = pb.ZoneInfo()
            self.zone.CopyFrom(snap.zone)
            self.spawns = {s.id: s for s in snap.spawns}
            self._set_book(snap.book)
            self._set_inventory(snap.inventory)
            self.bot_gear = [BotGear.from_pb(b) for b in snap.bots.bots]
        elif kind == "delta":
            delta = frame.delta
            if self.me is None:
                return  # deltas before a snapshot can't be applied
            self.me.CopyFrom(delta.me)
            for s in delta.spawns_changed:
                self.spawns[s.id] = s
            for spawn_id in delta.spawns_removed:
                self.spawns.pop(spawn_id, None)
            if delta.HasField("book"):
                self._set_book(delta.book)
            if delta.HasField("inventory"):
                self._set_inventory(delta.inventory)
            if delta.HasField("bots"):
                self.bot_gear = [BotGear.from_pb(b) for b in delta.bots.bots]

    def _set_book(self, book: pb.SpellBook) -> None:
        self.book = [BookSpell(s.spell_id, s.name, s.level, s.slot) for s in book.spells]

    def _set_inventory(self, inventory: pb.Inventory) -> None:
        self.inventory = [Item.from_pb(i) for i in inventory.items]  # carried and banked

    # ---- frozen views ----

    def me_tlo(self) -> Me | None:
        if self._me[0] == self._ver:
            return self._me[1]
        m = Me.from_pb(self.me) if self.me else None
        self._me = (self._ver, m)
        return m

    def searched(self) -> dict:
        """The searches' answers kept for this frame (Bot.Spawns): emptied when a frame is applied."""
        if self.searches[0] != self._ver:
            self.searches = (self._ver, {})
        return self.searches[1]

    def zone_tlo(self) -> Zone | None:
        return self.per_frame("zone", lambda: Zone.from_pb(self.zone) if self.zone else None)

    def per_frame(self, what: str, build):
        """build()'s answer kept until the next frame (Group, Raid, Zone: asked many times between two frames)."""
        if self._frame_kept[0] != self._ver:
            self._frame_kept = (self._ver, {})
        kept = self._frame_kept[1]
        if what not in kept:
            kept[what] = build()
        return kept[what]

    def spawn_tlo(self, spawn_id: int) -> Spawn | None:
        s = self.spawns.get(spawn_id) if spawn_id else None  # nothing real has id 0
        if s is None or self.me is None:
            return None
        return self._tlo(s, self.me.x, self.me.y, self.me.z)

    def _tlo(self, s: pb.Spawn, mx: float, my: float, mz: float) -> Spawn:
        """The frozen Spawn of this message: the one built before when the message is the same, moved to where we are now."""
        b = self._built.get(s.id)
        if b is None or b[0] is not s:
            t = Spawn.from_pb(s, mx, my, mz)
            self._built[s.id] = (s, t)
            return t
        t = b[1]
        if t._me_x != mx or t._me_y != my or t._me_z != mz:
            # (only where we stand changed: a copy with it, not a rebuild from the message)
            t = object.__new__(Spawn)
            d = t.__dict__
            d.update(b[1].__dict__)
            d["_me_x"], d["_me_y"], d["_me_z"] = mx, my, mz
            self._built[s.id] = (s, t)
        return t

    def all_spawns(self) -> list[Spawn]:
        if self.me is None:
            return []
        if self._all[0] == self._ver:
            return list(self._all[1])
        mx, my, mz = self.me.x, self.me.y, self.me.z
        out = [self._tlo(s, mx, my, mz) for i, s in self.spawns.items() if i and s.id]
        if len(self._built) > len(self.spawns) + 64:   # (gone spawns' entries dropped now and then)
            self._built = {i: b for i, b in self._built.items() if self.spawns.get(i) is b[0]}
        self._all = (self._ver, out)
        return list(out)
