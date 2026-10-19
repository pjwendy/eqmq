"""State mirror: applies Snapshot/StateDelta frames to an internal model.

Scripts only ever see the frozen TLO objects it hands out.
"""
from __future__ import annotations

from .proto import headless_pb2 as pb
from .tlo import BookSpell, Item, Me, Spawn, Zone


class StateMirror:
    def __init__(self) -> None:
        self.me: pb.Self | None = None
        self.zone: pb.ZoneInfo | None = None
        self.spawns: dict[int, pb.Spawn] = {}
        self.book: list[BookSpell] = []
        self.inventory: list[Item] = []

    @property
    def ready(self) -> bool:
        return self.me is not None

    def apply(self, frame: pb.ServerFrame) -> None:
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

    def _set_book(self, book: pb.SpellBook) -> None:
        self.book = [BookSpell(s.spell_id, s.name, s.level) for s in book.spells]

    def _set_inventory(self, inventory: pb.Inventory) -> None:
        self.inventory = [Item.from_pb(i) for i in inventory.items]

    # ---- frozen views ----

    def me_tlo(self) -> Me | None:
        return Me.from_pb(self.me) if self.me else None

    def zone_tlo(self) -> Zone | None:
        return Zone.from_pb(self.zone) if self.zone else None

    def spawn_tlo(self, spawn_id: int) -> Spawn | None:
        s = self.spawns.get(spawn_id)
        if s is None or self.me is None:
            return None
        return Spawn.from_pb(s, self.me.x, self.me.y, self.me.z)

    def all_spawns(self) -> list[Spawn]:
        if self.me is None:
            return []
        mx, my, mz = self.me.x, self.me.y, self.me.z
        return [Spawn.from_pb(s, mx, my, mz) for s in self.spawns.values()]
