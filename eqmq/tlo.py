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
            OwnerID=s.owner_id, Headless=s.headless, _me_x=me_x, _me_y=me_y, _me_z=me_z,
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
        )


@dataclass(frozen=True)
class Zone:
    ID: int
    InstanceID: int
    ShortName: str
    Name: str          # long name, as MQ2's Zone.Name

    @staticmethod
    def from_pb(z: pb.ZoneInfo) -> "Zone":
        return Zone(ID=z.id, InstanceID=z.instance_id, ShortName=z.short_name, Name=z.long_name)
