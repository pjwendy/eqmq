"""MQ2-style Top-Level Objects: frozen, read-only views of game state.

Names follow MacroQuest (vocabulary only, no MQ2 code). Coordinates are in-game: Loc prints
"Y, X, Z" the way /loc does.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .proto import headless_pb2 as pb

_SPAWN_TYPES = {
    pb.SPAWN_TYPE_PLAYER: "PC",
    pb.SPAWN_TYPE_NPC: "NPC",
    pb.SPAWN_TYPE_BOT: "Bot",
    pb.SPAWN_TYPE_PLAYER_CORPSE: "Corpse",
    pb.SPAWN_TYPE_NPC_CORPSE: "Corpse",
}


def _pct(cur: int, mx: int) -> int:
    return int(cur * 100 / mx) if mx > 0 else 0


# con colours and faction standings, as the client names them
CON_COLORS = {2: "green", 4: "blue", 6: "grey", 10: "white", 13: "red", 15: "yellow", 18: "lightblue", 20: "white"}
FACTIONS = {1: "ally", 2: "warmly", 3: "kindly", 4: "amiable", 5: "indifferent", 6: "apprehensive",
            7: "dubious", 8: "threatening", 9: "scowls"}


@dataclass(frozen=True)
class Gem:
    Slot: int        # 1-based, as /cast 1 and MQ2's Me.Gem[1]
    ID: int
    Name: str
    Ready: bool      # not refreshing, not casting, not memorising


@dataclass(frozen=True)
class Buff:
    ID: int
    Name: str
    Ticks: int       # 6-second ticks left; -1 permanent

    @property
    def Duration(self) -> float:
        """Seconds left (inf if permanent)."""
        return math.inf if self.Ticks < 0 else self.Ticks * 6.0


@dataclass(frozen=True)
class BookSpell:
    ID: int
    Name: str
    Level: int


@dataclass(frozen=True)
class Item:
    Slot: int
    ID: int
    Name: str
    Charges: int
    Container: bool


@dataclass(frozen=True)
class Spawn:
    ID: int
    Name: str
    Type: str          # "PC", "NPC", "Pet", "Bot", "Corpse"
    Level: int
    ClassID: int
    RaceID: int
    X: float
    Y: float
    Z: float
    Heading: float
    PctHPs: int
    OwnerID: int
    Headless: bool
    TargetID: int = 0  # who it has targeted; for an NPC in combat, who it's hitting
    _me_x: float = 0.0
    _me_y: float = 0.0
    _me_z: float = 0.0

    @property
    def CleanName(self) -> str:
        return self.Name

    @property
    def Loc(self) -> str:
        return f"{self.Y:.2f}, {self.X:.2f}, {self.Z:.2f}"

    @property
    def Distance(self) -> float:
        """2D distance from you, as MQ2's Spawn.Distance."""
        return math.hypot(self.X - self._me_x, self.Y - self._me_y)

    @property
    def Distance3D(self) -> float:
        return math.dist((self.X, self.Y, self.Z), (self._me_x, self._me_y, self._me_z))

    @staticmethod
    def from_pb(s: pb.Spawn, me_x: float, me_y: float, me_z: float) -> "Spawn":
        type_name = _SPAWN_TYPES.get(s.type, "Unknown")
        if type_name == "NPC" and s.owner_id:
            type_name = "Pet"
        return Spawn(
            ID=s.id, Name=s.name, Type=type_name, Level=s.level, ClassID=s.class_id,
            RaceID=s.race_id, X=s.x, Y=s.y, Z=s.z, Heading=s.heading, PctHPs=s.hp_pct,
            OwnerID=s.owner_id, Headless=s.headless, TargetID=s.target_id, _me_x=me_x, _me_y=me_y, _me_z=me_z,
        )


@dataclass(frozen=True)
class Me:
    ID: int
    Name: str
    Level: int
    ClassID: int
    RaceID: int
    CurrentHPs: int
    MaxHPs: int
    CurrentMana: int
    MaxMana: int
    CurrentEndurance: int
    MaxEndurance: int
    X: float
    Y: float
    Z: float
    Heading: float
    TargetID: int
    Sitting: bool
    Combat: bool       # auto-attack on
    CastingID: int     # 0 if not casting
    Gems: tuple = ()   # Gem, by slot
    Buffs: tuple = ()  # Buff
    Platinum: int = 0
    Gold: int = 0
    Silver: int = 0
    Copper: int = 0
    Haters: tuple = ()  # spawn ids of NPCs with you on their hate list

    @property
    def PctHPs(self) -> int:
        return _pct(self.CurrentHPs, self.MaxHPs)

    @property
    def PctMana(self) -> int:
        return _pct(self.CurrentMana, self.MaxMana)

    @property
    def PctEndurance(self) -> int:
        return _pct(self.CurrentEndurance, self.MaxEndurance)

    @property
    def Standing(self) -> bool:
        return not self.Sitting

    @property
    def Casting(self) -> bool:
        return self.CastingID != 0

    def Gem(self, n: int | str) -> Gem | None:
        """Gem n (1-based), or the gem holding a spell by name (case-insensitive)."""
        for g in self.Gems:
            if (isinstance(n, int) and g.Slot == n) or (isinstance(n, str) and g.Name.lower() == n.lower()):
                return g
        return None

    def Buff(self, name: str) -> Buff | None:
        """Your buff whose name contains `name` (case-insensitive)."""
        return next((b for b in self.Buffs if name.lower() in b.Name.lower()), None)

    @property
    def Engaged(self) -> bool:
        """In combat: some NPC has you on its hate list."""
        return bool(self.Haters)

    @property
    def Money(self) -> int:
        """All carried coin, in copper."""
        return ((self.Platinum * 10 + self.Gold) * 10 + self.Silver) * 10 + self.Copper

    @property
    def Loc(self) -> str:
        return f"{self.Y:.2f}, {self.X:.2f}, {self.Z:.2f}"

    @staticmethod
    def from_pb(m: pb.Self) -> "Me":
        return Me(
            ID=m.spawn_id, Name=m.name, Level=m.level, ClassID=m.class_id, RaceID=m.race_id,
            CurrentHPs=m.hp, MaxHPs=m.max_hp, CurrentMana=m.mana, MaxMana=m.max_mana,
            CurrentEndurance=m.endurance, MaxEndurance=m.max_endurance, X=m.x, Y=m.y, Z=m.z,
            Heading=m.heading, TargetID=m.target_id, Sitting=m.sitting, Combat=m.auto_attack,
            CastingID=m.casting_spell_id,
            Gems=tuple(Gem(g.slot + 1, g.spell_id, g.name, g.ready) for g in m.gems),
            Buffs=tuple(Buff(b.spell_id, b.name, b.ticks) for b in m.buffs),
            Platinum=m.platinum, Gold=m.gold, Silver=m.silver, Copper=m.copper, Haters=tuple(m.haters),
        )


@dataclass(frozen=True)
class GroupMember:
    Name: str
    ID: int          # spawn id, 0 if not in this zone
    Leader: bool
    Bot: bool        # an EQEmu bot


@dataclass(frozen=True)
class Group:
    """As MQ2's Group TLO. Member(0) is you; Members counts everyone else."""
    All: tuple[GroupMember, ...]
    _me: str = ""

    @property
    def Members(self) -> int:
        return max(0, len(self.All) - 1)

    @property
    def Leader(self) -> GroupMember | None:
        return next((m for m in self.All if m.Leader), None)

    def Member(self, n: int | str) -> GroupMember | None:
        """Member(0) is you, Member(1..5) the others; or look one up by name."""
        if isinstance(n, str):
            return next((m for m in self.All if m.Name.lower() == n.lower()), None)
        others = [m for m in self.All if m.Name != self._me]
        me = [m for m in self.All if m.Name == self._me]
        ordered = me + others
        return ordered[n] if 0 <= n < len(ordered) else None

    @staticmethod
    def from_pb(m: pb.Self) -> "Group | None":
        if not m.group:
            return None
        return Group(tuple(GroupMember(g.name, g.spawn_id, g.leader, g.bot) for g in m.group), _me=m.name)


@dataclass(frozen=True)
class Zone:
    ID: int
    InstanceID: int
    ShortName: str
    Name: str          # long name, as MQ2's Zone.Name

    @staticmethod
    def from_pb(z: pb.ZoneInfo) -> "Zone":
        return Zone(ID=z.id, InstanceID=z.instance_id, ShortName=z.short_name, Name=z.long_name)
